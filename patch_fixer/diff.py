import os
import re
import warnings
from pathlib import Path

from requests import options

from patch_fixer.hunk import Hunk
from patch_fixer.regex import match_line, regexes
from patch_fixer.patch_fixer import reconstruct_file_header, regenerate_index
from patch_fixer.utils import normalize_line, split_ab


def validate_headers(headers, line_type_counts, current_file, dest_file, original_path, mode, similarity):
    for line_type, count in line_type_counts.items():
        if count > 1:
            raise ValueError(f"Duplicate {line_type} header found")

    diff_line = headers["DIFF_LINE"]
    a, b = regexes["DIFF_LINE"].match(diff_line).groups()
    look_for_rename = a != b

    # set up convenience booleans
    binary_file = "BINARY_FILE" in headers
    mode_exists = "MODE_LINE" in headers
    index_exists = "INDEX_LINE" in headers
    from_exists = "RENAME_FROM" in headers
    to_exists = "RENAME_TO" in headers
    start_exists = "FILE_HEADER_START" in headers
    end_exists = "FILE_HEADER_END" in headers
    new_file = current_file == "/dev/null"
    deleted_file = dest_file == "/dev/null"

    # check for incompatible header combinations
    if binary_file and from_exists:
        raise NotImplementedError("Renaming binary files not yet supported")
    if binary_file and start_exists:
        raise NotImplementedError(
            "A header block with both 'binary files differ' and "
            "file start/end headers is a confusing state "
            "from which there is no obvious way to recover."
        )

    # fix rename and file headers
    if look_for_rename:
        if to_exists and not from_exists:
            headers["RENAME_FROM"] = f"rename from {a}\n"
        elif from_exists and not to_exists:
            headers["RENAME_TO"] = f"rename to {b}\n"
    else:
        if current_file != dest_file and not (new_file or deleted_file):
            look_for_rename = True
            headers["RENAME_FROM"] = f"rename from {current_file}\n"
            headers["RENAME_TO"] = f"rename to {dest_file}\n"
            diff_line = f"diff --git a/{current_file} b/{dest_file}"

    if not look_for_rename or similarity != 100:
        if not start_exists:
            headers["FILE_HEADER_START"] = f"--- {a}\n"
        if not end_exists:
            headers["FILE_HEADER_END"] = f"+++ {b}\n"

    # always start with diff line
    fixed_headers = [diff_line]

    # validate mode line if needed
    if not mode:
        mode = "100644"
    if mode_exists:
        mode_line = headers["MODE_LINE"]
        if new_file and "deleted" in mode_line:
            mode_line = f"new file mode {mode}\n"
        elif deleted_file and "new" in mode_line:
            mode_line = f"deleted file mode {mode}\n"
        fixed_headers.append(mode_line)
    elif new_file:
        fixed_headers.append(f"new file mode {mode}")
    elif deleted_file:
        fixed_headers.append(f"deleted file mode {mode}")

    # rename comes before index if both are present (renamed file with changes)
    if look_for_rename:
        fixed_headers.append(headers["RENAME_FROM"])
        fixed_headers.append(headers["RENAME_TO"])

    if index_exists:
        fixed_headers.append(headers["INDEX_LINE"])
    else:
        fixed_headers.append(regenerate_index(current_file, dest_file, original_path))

    if binary_file:
        binary_line = headers["BINARY_LINE"]
        c, d = regexes["BINARY_LINE"].match(binary_line).groups()
        if (a, b) != (c, d) and c != "/dev/null" and d != "/dev/null":
            # go with diff line version if the filepaths conflict
            binary_line = f"binary files {a} and {b} differ\n"
        fixed_headers.append(binary_line)

    if similarity != 100:
        fixed_headers.append(headers["FILE_HEADER_START"])
        fixed_headers.append(headers["FILE_HEADER_END"])

    return fixed_headers


def parse_header(header, **kwargs):
    original = kwargs.get("original")
    dir_mode = os.path.isdir(original)
    original_path = Path(original).absolute()

    header_lines = [line for line in header.splitlines(keepends=True)]
    headers = {line_type: False for line_type in regexes.keys()}
    line_type_counts = {line_type: 0 for line_type in regexes.keys()}

    rename_from, rename_to, current_file, dest_file = None, None, None, None
    original_lines = []
    mode = 0
    similarity = 0

    for i, line in enumerate(header_lines):
        match_groups, line_type = match_line(line)
        fixed_line = normalize_line(line)
        match line_type:
            case "DIFF_LINE" | "BINARY_LINE" | "HUNK_HEADER" | "END_LINE":
                pass
            case "MODE_LINE":
                mode = match_groups[0]
            case "INDEX_LINE":
                if "similarity" in line:
                    similarity = int(match_groups[0])
                else:
                    old_index = match_groups[0]
                    new_index = match_groups[1]
                    if len(match_groups) == 2:
                        if mode and int(f"0x{new_index}") != 0:
                            # add missing mode
                            fixed_line = f"{old_index}..{new_index} {mode}\n"
                    elif mode and int(match_groups[2]) != mode:
                        raise ValueError(
                            f"mode line file mode {mode} does not match "
                            f"index line file mode {match_groups[2]}"
                        )
                    elif not mode:
                        mode = match_groups[2]
            case "RENAME_FROM":
                rename_from = match_groups[0]
                rename_from_path = Path(rename_from).absolute()
                if not dir_mode and rename_from_path != original_path:
                    raise FileNotFoundError(
                        f"Filename {rename_from} in `rename from` header "
                        f"does not match argument {original}"
                    )
            case "RENAME_TO":
                rename_to = match_groups[0]
                rename_to_path = Path(rename_to).absolute()
                if rename_to and rename_to_path.is_dir():
                    raise IsADirectoryError(
                        f"rename to points to a directory, not a file: {rename_to}"
                    )
            case "FILE_HEADER_START":
                current_file = match_groups[0]
                if current_file == "/dev/null":
                    break
                if current_file.startswith("a/"):
                    current_file = current_file[2:]
                else:
                    fixed_line = fixed_line.replace(current_file, f"a/{current_file}")
                current_path = Path(current_file).absolute()
                if not current_path.exists():
                    raise FileNotFoundError(
                        f"File header start points to non-existent file: {current_file}"
                    )
                if not current_path.is_file():
                    raise IsADirectoryError(
                        f"File header start points to a directory, not a file: {current_file}"
                    )
                if not dir_mode and current_path != original_path:
                    raise FileNotFoundError(
                        f"Filename {current_file} in header does not match argument {original}"
                    )
            case "FILE_HEADER_END":
                dest_file = match_groups[0]
                dest_path = Path(dest_file).absolute()
                if dest_file.startswith("b/"):
                    dest_file = dest_file[2:]
                elif dest_file != "/dev/null":
                    fixed_line = fixed_line.replace(dest_file, f"b/{dest_file}")
                if current_file == "/dev/null":
                    if dest_file == "/dev/null":
                        raise ValueError(
                            "File headers cannot both be /dev/null"
                        )
                    elif dest_path.exists():
                        raise FileExistsError(
                            f"File header start /dev/null implies file creation, "
                            f"but file header end would overwrite existing file: {dest_file}"
                        )
                    current_file = dest_file
                    current_path = Path(current_file).absolute()
                    if not dir_mode and current_path != original_path:
                        raise FileNotFoundError(
                            f"Filename {current_file} in header does not match argument {original}"
                        )
                elif dest_file == "/dev/null":
                    current_path = Path(current_file).absolute()
                    if not current_path.exists():
                        raise FileNotFoundError(
                            f"The file being 'deleted' does not exist: {current_file}"
                        )
            case _:
                warnings.warn(f"Unrecognized header line: {line}")
                continue

        headers[line_type] = fixed_line
        line_type_counts[line_type] += 1

    fixed_header = validate_headers(headers, line_type_counts, current_file, dest_file, original_path, mode, similarity)

    return fixed_header, original_lines


class Diff:
    def __init__(self, raw_content, **kwargs):
        self.content = raw_content
        self.options = kwargs

        parts = re.split(r'^@@ [0-9, +-] @@.*$', self.content, flags=re.MULTILINE)
        self.header_lines, self.original_lines = parse_header(parts[0], **kwargs)
        self.hunks = [Hunk(hunk) for hunk in parts[1:]]

    def __str__(self):
        return self.content
