#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

from git import Repo

path_regex = r'(?:/[A-Za-z0-9_.-]+)*'
regexes = {
    "DIFF_LINE": re.compile(rf'diff --git (a{path_regex}+) (b{path_regex}+)'),
    "MODE_LINE": re.compile(r'(new|deleted) file mode [0-7]{6}'),
    "INDEX_LINE": re.compile(r'index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: [0-7]{6})?|similarity index ([0-9]+)%'),
    "BINARY_LINE": re.compile(rf'Binary files (a{path_regex}+|/dev/null) and (b{path_regex}+|/dev/null) differ'),
    "RENAME_FROM": re.compile(rf'rename from ({path_regex})'),
    "RENAME_TO": re.compile(rf'rename to ({path_regex})'),
    "FILE_HEADER_START": re.compile(rf'--- (a{path_regex}+|/dev/null)'),
    "FILE_HEADER_END": re.compile(rf'\+\+\+ (b{path_regex}+|/dev/null)'),
    "HUNK_HEADER": re.compile(r'^@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$'),
    "END_LINE": re.compile(r'\\ No newline at end of file')
}


class MissingHunkError(Exception):
    pass


def normalize_line(line):
    if line.startswith('+'):
        # safe to normalize new content
        return '+' + line[1:].rstrip() + "\n"
    else:
        # preserve exactly (only normalize line endings)
        return line.rstrip("\r\n") + "\n"

def find_hunk_start(context_lines, original_lines):
    """Search original_lines for context_lines and return start line index (0-based)."""
    ctx = []
    for line in context_lines:
        if line.startswith(" "):
            ctx.append(line.lstrip(" "))
        elif line.startswith("-"):
            ctx.append(line.lstrip("-"))
        elif line.isspace() or line == "":
            ctx.append(line)
    if not ctx:
        raise ValueError("Cannot search for empty hunk.")
    for i in range(len(original_lines) - len(ctx) + 1):
        # this part will fail if the diff is malformed beyond hunk header
        equal_lines = [original_lines[i+j].strip() == ctx[j].strip() for j in range(len(ctx))]
        if all(equal_lines):
            return i
    return 0


def match_line(line):
    for line_type, regex in regexes.items():
        match = regex.match(line)
        if match:
            return match.groups(), line_type
    return None, None


def split_ab(match_groups):
    a, b = match_groups
    a = f"./{a[2:]}"
    b = f"./{b[2:]}"
    return a, b


def reconstruct_file_header(diff_line, header_type):
    # reconstruct file header based on last diff line
    diff_groups, diff_type = match_line(diff_line)
    assert diff_type == "DIFF_LINE", "Indexing error in last diff calculation"
    a, b = diff_groups
    match header_type:
        case "FILE_HEADER_START":
            return f"--- {a}"
        case "FILE_HEADER_END":
            return f"+++ {b}"
        case _:
            raise ValueError(f"Unsupported header type: {header_type}")


def capture_hunk(current_hunk, original_lines, offset, last_hunk, hunk_context):
    # compute line counts
    old_count = sum(1 for l in current_hunk if l.startswith((' ', '-')))
    new_count = sum(1 for l in current_hunk if l.startswith((' ', '+')))

    # compute starting line in original file
    old_start = find_hunk_start(current_hunk, original_lines) + 1

    # if the line number descends, we either have a bad match or a new file
    if old_start < last_hunk:
        raise MissingHunkError
    else:
        new_start = old_start + offset

    offset += (new_count - old_count)

    last_hunk = old_start

    # write corrected header
    fixed_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{hunk_context}\n"

    return fixed_header, offset, last_hunk


def regenerate_index(old_path, new_path, cur_dir):
    repo = Repo(cur_dir)
    mode = " 100644"     # TODO: check if mode can be a different number

    # file creation
    if old_path == "/dev/null":
        assert new_path != "/dev/null", "Paths cannot both be /dev/null"
        old_sha = "0000000"
        new_sha = repo.git.hash_object(new_path)

    # file deletion
    elif new_path == "/dev/null":
        old_sha = repo.git.hash_object(old_path)
        new_sha = "0000000"
        mode = ""   # deleted file can't have a mode

    else:
        raise NotImplementedError(
            "Regenerating index not yet supported in the general case, "
            "as this would require manually applying the patch first."
        )

    return f"index {old_sha}..{new_sha}{mode}"


def fix_patch(patch_lines, original):
    dir_mode = os.path.isdir(original)
    original_path = Path(original).absolute()

    # make relative paths in the diff work
    os.chdir(original_path)

    fixed_lines = []
    current_hunk = []
    current_file = None
    first_hunk = True
    offset = 0      # running tally of how perturbed the new line numbers are
    last_hunk = 0   # start of last hunk (fixed lineno in changed file)
    last_diff = 0   # start of last diff (lineno in patch file itself)
    last_mode = 0   # most recent "new file mode" or "deleted file mode" line
    last_index = 0  # most recent "index <hex>..<hex> <file_permissions>" line
    file_start_header = False
    file_end_header = False
    look_for_rename = False
    similarity_index = None
    missing_index = False
    hunk_context = ""

    for i, line in enumerate(patch_lines):
        match_groups, line_type = match_line(line)
        match line_type:
            case "DIFF_LINE":
                if not first_hunk:
                    # process last hunk with header in previous file
                    try:
                        (
                            fixed_header,
                            offset,
                            last_hunk
                        ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, hunk_context)
                    except MissingHunkError:
                        raise NotImplementedError(f"Could not find hunk in {current_file}:"
                                                  f"\n\n{"\n".join(current_hunk)}")
                    fixed_lines.append(fixed_header)
                    fixed_lines.extend(current_hunk)
                    current_hunk = []
                a, b = split_ab(match_groups)
                if a != b:
                    raise ValueError(f"Diff paths do not match: \n{a}\n{b}")
                fixed_lines.append(normalize_line(line))
                last_diff = i
                file_start_header = False
                file_end_header = False
                first_hunk = True
            case "MODE_LINE":
                if last_diff != i - 1:
                    raise NotImplementedError("Missing diff line not yet supported")
                last_mode = i
                fixed_lines.append(normalize_line(line))
            case "INDEX_LINE":
                # TODO: verify that mode is present for anything but deletion
                last_index = i
                similarity_index = match_groups[0]
                if similarity_index:
                    look_for_rename = True
                fixed_lines.append(normalize_line(line))
                missing_index = False
            case "BINARY_LINE":
                raise NotImplementedError("Binary files not supported yet")
            case "RENAME_FROM":
                if not look_for_rename:
                    pass    # TODO: handle missing index line
                if last_index != i - 1:
                    missing_index = True    # need this for existence check in RENAME_TO block
                    similarity_index = 100  # TODO: is this a dangerous assumption?
                    fixed_index = "similarity index 100%"
                    fixed_lines.append(normalize_line(fixed_index))
                look_for_rename = False
                current_file = match_groups[0]
                current_path = Path(current_file).absolute()
                offset = 0
                last_hunk = 0
                if not Path.exists(current_path):
                    if similarity_index == 100:
                        fixed_lines.append(normalize_line(line))
                        look_for_rename = True
                        continue
                    raise NotImplementedError("Parsing files that were both renamed and modified is not yet supported.")
                if dir_mode or current_path == original_path:
                    with open(current_path, encoding='utf-8') as f:
                        original_lines = [l.rstrip('\n') for l in f.readlines()]
                    fixed_lines.append(normalize_line(line))
                    # TODO: analogous boolean to `file_start_header`?
                else:
                    raise FileNotFoundError(f"Filename {current_file} in `rename from` header does not match argument {original}")
            case "RENAME_TO":
                if last_index != i - 2:
                    if missing_index:
                        missing_index = False
                    else:
                        raise NotImplementedError("Missing `rename from` header not yet supported.")
                if look_for_rename:
                    # the old file doesn't exist, so we need to read this one
                    current_file = match_groups[0]
                    current_path = Path(current_file).absolute()
                    with open(current_path, encoding='utf-8') as f:
                        original_lines = [l.rstrip('\n') for l in f.readlines()]
                    fixed_lines.append(normalize_line(line))
                    look_for_rename = False
                pass
            case "FILE_HEADER_START":
                if look_for_rename:
                    raise NotImplementedError("Replacing file header with rename not yet supported.")
                if last_index != i - 1:
                    missing_index = True
                file_end_header = False
                if current_file and not dir_mode:
                    raise ValueError("Diff references multiple files but only one provided.")
                current_file = match_groups[0]
                offset = 0
                last_hunk = 0
                if current_file == "/dev/null":
                    if last_diff > last_mode:
                        raise NotImplementedError("Missing mode line not yet supported")
                    fixed_lines.append(normalize_line(line))
                    file_start_header = True
                    continue
                if current_file.startswith("a/"):
                    current_file = current_file[2:]
                else:
                    line = line.replace(current_file, f"a/{current_file}")
                current_path = Path(current_file).absolute()
                if not current_path.exists():
                    raise FileNotFoundError(f"File header start points to non-existent file: {current_file}")
                if dir_mode or Path(current_file) == Path(original):
                    with open(current_file, encoding='utf-8') as f:
                        original_lines = [l.rstrip('\n') for l in f.readlines()]
                    fixed_lines.append(normalize_line(line))
                    file_start_header = True
                else:
                    raise FileNotFoundError(f"Filename {current_file} in header does not match argument {original}")
            case "FILE_HEADER_END":
                if look_for_rename:
                    raise NotImplementedError("Replacing file header with rename not yet supported.")
                dest_file = match_groups[0]
                dest_path = Path(dest_file).absolute()
                if dest_file.startswith("b/"):
                    dest_file = dest_file[2:]
                elif dest_file != "/dev/null":
                    line = line.replace(dest_file, f"b/{dest_file}")
                if missing_index:
                    fixed_index = regenerate_index(current_file, dest_file, original_path)
                    fixed_lines.append(normalize_line(fixed_index))
                if not file_start_header:
                    if dest_file == "/dev/null":
                        if last_diff > last_mode:
                            raise NotImplementedError("Missing mode line not yet supported")
                        a = reconstruct_file_header(patch_lines[last_diff], "FILE_HEADER_START")
                        fixed_lines.append(normalize_line(a))
                    else:
                        # reconstruct file start header based on end header
                        a = match_groups[0].replace("b", "a")
                        fixed_lines.append(normalize_line(f"--- {a}"))
                    file_start_header = True
                elif current_file == "/dev/null":
                    if dest_file == "/dev/null":
                        raise ValueError("File headers cannot both be /dev/null")
                    elif not dest_path.exists():
                        raise FileNotFoundError(f"File header end points to non-existent file: {dest_file}")
                    current_file = dest_file
                    current_path = Path(current_file).absolute()
                    if dir_mode or current_path == original_path:
                        # TODO: in dir mode, verify that current file exists in original path
                        with open(current_path, encoding='utf-8') as f:
                            original_lines = [l.rstrip('\n') for l in f.readlines()]
                        fixed_lines.append(normalize_line(line))
                        file_end_header = True
                    else:
                        raise FileNotFoundError(f"Filename {current_file} in header does not match argument {original}")
                elif dest_file == "/dev/null":
                    raise NotImplementedError("File deletion not yet supported")
                elif current_file != dest_file:
                    raise ValueError(f"File headers do not match: \n{current_file}\n{dest_file}")
                pass
            case "HUNK_HEADER":
                # fix missing file headers before capturing the hunk
                if not file_end_header:
                    diff_line = patch_lines[last_diff]
                    if not file_start_header:
                        a = reconstruct_file_header(diff_line, "FILE_HEADER_START")
                        fixed_lines.append(normalize_line(a))
                        file_start_header = True
                        current_file = split_ab(match_line(diff_line))[0]
                    b = reconstruct_file_header(diff_line, "FILE_HEADER_END")
                    fixed_lines.append(normalize_line(b))
                    file_end_header = True

                # we can't fix the hunk header before we've captured a hunk
                if first_hunk:
                    first_hunk = False
                    hunk_context = match_groups[4]
                    continue

                try:
                    (
                        fixed_header,
                        offset,
                        last_hunk
                    ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, hunk_context)
                except MissingHunkError:
                    raise NotImplementedError(f"Could not find hunk in {current_file}:"
                                              f"\n\n{"\n".join(current_hunk)}")
                fixed_lines.append(fixed_header)
                fixed_lines.extend(current_hunk)
                current_hunk = []
                hunk_context = match_groups[4]
            case "END_LINE":
                # TODO: add newline at end of file if user requests
                fixed_lines.append(normalize_line(line))
            case _:
                # TODO: fuzzy string matching
                # this is a normal line, add to current hunk
                current_hunk.append(normalize_line(line))

    # we need to process the last hunk since there's no new header to catch it
    try:
        (
            fixed_header,
            offset,
            last_hunk
        ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, hunk_context)
    except MissingHunkError:
        raise NotImplementedError(f"Could not find hunk in {current_file}:"
                                  f"\n\n{"\n".join(current_hunk)}")
    fixed_lines.append(fixed_header)
    fixed_lines.extend(current_hunk)

    # if original file didn't end with a newline, strip out the newline here
    if not original_lines[-1].endswith("\n"):
        fixed_lines[-1] = fixed_lines[-1].rstrip("\n")

    return fixed_lines


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <original_file> <broken.patch> <fixed.patch>")
        sys.exit(1)

    original = sys.argv[1]
    patch_file = sys.argv[2]
    output_file = sys.argv[3]

    with open(patch_file, encoding='utf-8') as f:
        patch_lines = f.readlines()

    fixed_lines = fix_patch(patch_lines, original)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)

    print(f"Fixed patch written to {output_file}")

if __name__ == "__main__":
    main()

