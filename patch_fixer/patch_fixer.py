#!/usr/bin/env python3
import os
import re
import warnings
from pathlib import Path

from git import Repo

from patch_fixer.errors import MissingHunkError, OutOfOrderHunk, EmptyHunk
from patch_fixer.regex import regexes, match_line
from patch_fixer.utils import normalize_line, fuzzy_line_similarity, split_ab, read_file_with_fallback_encoding


def find_hunk_start(context_lines, original_lines, fuzzy=False):
    """Search original_lines for context_lines and return start line index (0-based)."""
    ctx = []
    for line in context_lines:
        if regexes["END_LINE"].match(line):
            # "\ No newline at end of file" is just git metadata; skip
            continue
        elif line.startswith(" "):
            ctx.append(line.lstrip(" "))
        elif line.startswith("-"):
            # can't use lstrip; we want to keep other dashes in the line
            ctx.append(line[1:])
        elif line.isspace() or line == "":
            ctx.append(line)
    if not ctx:
        raise ValueError("Cannot search for empty hunk.")

    # first try exact matching
    for i in range(len(original_lines) - len(ctx) + 1):
        # this part will fail if the diff is malformed beyond hunk header
        equal_lines = [original_lines[i + j].strip() == ctx[j].strip() for j in range(len(ctx))]
        if all(equal_lines):
            return i

    # if fuzzy matching is enabled and exact match failed, try fuzzy match
    if fuzzy:
        best_match_score = 0.0
        best_match_pos = 0

        for i in range(len(original_lines) - len(ctx) + 1):
            total_similarity = 0.0
            for j in range(len(ctx)):
                similarity = fuzzy_line_similarity(original_lines[i + j], ctx[j])
                total_similarity += similarity

            avg_similarity = total_similarity / len(ctx)
            if avg_similarity > best_match_score and avg_similarity > 0.6:
                best_match_score = avg_similarity
                best_match_pos = i

        if best_match_score > 0.6:
            return best_match_pos

    raise MissingHunkError(context_lines)


def reconstruct_file_header(diff_line, header_type):
    # reconstruct file header based on last diff line
    diff_groups, diff_type = match_line(diff_line)
    assert diff_type == "DIFF_LINE", "Indexing error in last diff calculation"
    a, b = diff_groups
    match header_type:
        case "FILE_HEADER_START":
            return f"--- {a}\n"
        case "FILE_HEADER_END":
            return f"+++ {b}\n"
        case _:
            raise ValueError(f"Unsupported header type: {header_type}")


def find_all_hunk_starts(hunk_lines, search_lines, fuzzy=False):
    """Return all line indices in search_lines where this hunk matches."""
    matches = []
    start = 0
    while True:
        try:
            idx = find_hunk_start(hunk_lines, search_lines[start:], fuzzy=fuzzy)
            matches.append(start + idx)
            start += idx + 1
        except MissingHunkError:
            break
    return matches


def capture_hunk(current_hunk, original_lines, offset, last_hunk, old_header, fuzzy=False):
    """
    Try to locate the hunk's true position in the original file.

    If multiple possible matches exist, pick the one closest to the expected
    (possibly corrupted) line number derived from the old hunk header.
    """
    if not current_hunk:
        raise EmptyHunk

    # extract needed info from old header match groups
    expected_old_start = int(old_header[0]) if old_header else 0
    try:
        hunk_context = old_header[4]
    except IndexError:
        hunk_context = ""

    # presence or absence of end line shouldn't affect line counts
    if regexes["END_LINE"].match(current_hunk[-1]):
        hunk_len = len(current_hunk) - 1
    else:
        hunk_len = len(current_hunk)

    # compute line counts
    context_count = sum(1 for l in current_hunk if l.startswith(' '))
    minus_count = sum(1 for l in current_hunk if l.startswith('-'))
    plus_count = sum(1 for l in current_hunk if l.startswith('+'))

    old_count = context_count + minus_count
    new_count = context_count + plus_count

    if minus_count == hunk_len:     # file deletion
        old_start = 1
        new_start = 0
    elif plus_count == hunk_len:    # file creation
        old_start = 0
        new_start = 1
    else:                           # file modification
        search_index = last_hunk
        search_lines = original_lines[search_index:]

        # gather *all* possible matches
        matches = find_all_hunk_starts(current_hunk, search_lines, fuzzy=fuzzy)
        if matches:
            # rebase to file line numbers (1-indexed later)
            candidate_positions = [m + search_index for m in matches]

            if expected_old_start:
                # choose the one closest to the expected position
                old_start = min(
                    candidate_positions,
                    key=lambda pos: abs(pos + 1 - expected_old_start),
                ) + 1  # convert to 1-indexed
            else:
                # pick first match if no expected line info
                old_start = candidate_positions[0] + 1
        else:
            # try from start of file, excluding lines already searched
            search_index += hunk_len
            search_lines = original_lines[:search_index]
            matches = find_all_hunk_starts(current_hunk, search_lines, fuzzy=fuzzy)
            if not matches:
                raise MissingHunkError(current_hunk)
            if expected_old_start:
                old_start = (
                    min(matches, key=lambda pos: abs(pos + 1 - expected_old_start)) + 1
                )
            else:
                old_start = matches[0] + 1

        if old_start < last_hunk + 1:
            raise OutOfOrderHunk(current_hunk, original_lines[last_hunk])

        if new_count == 0:
            # complete deletion of remaining content
            new_start = 0
        else:
            new_start = old_start + offset

    offset += (new_count - old_count)

    last_hunk += (old_start - last_hunk)

    # use condensed header if it's only one line
    old_part = f"{old_start},{old_count}" if old_count != 1 else f"{old_start}"
    new_part = f"{new_start},{new_count}" if new_count != 1 else f"{new_start}"

    fixed_header = f"@@ -{old_part} +{new_part} @@{hunk_context}\n"

    return fixed_header, offset, last_hunk


def regenerate_index(old_path, new_path, cur_dir):
    repo = Repo(cur_dir)

    # Common git file modes: 100644 (regular file), 100755 (executable file),
    # 120000 (symbolic link), 160000 (submodule), 040000 (tree/directory)
    # TODO: guess mode based on above information
    mode = " 100644"

    # file deletion
    if new_path == "/dev/null":
        old_sha = repo.git.hash_object(old_path)
        new_sha = "0000000"
        mode = ""   # deleted file can't have a mode

    else:
        raise NotImplementedError(
            "Regenerating index not yet supported in the general case, "
            "as this would require manually applying the patch first."
        )

    return f"index {old_sha}..{new_sha}{mode}\n"


def fix_patch(patch_lines, original, remove_binary=False, fuzzy=False, add_newline=False):
    dir_mode = os.path.isdir(original)
    original_path = Path(original).absolute()

    # make relative paths in the diff work
    if dir_mode:
        os.chdir(original_path)
    else:
        os.chdir(original_path.parent)

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
    missing_index = False
    binary_file = False
    current_hunk_header = ()
    original_lines = []
    file_loaded = False

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
                        ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, current_hunk_header, fuzzy=fuzzy)
                    except (MissingHunkError, OutOfOrderHunk) as e:
                        e.add_file(current_file)
                        raise e
                    fixed_lines.append(fixed_header)
                    fixed_lines.extend(current_hunk)
                    current_hunk = []
                a, b = split_ab(match_groups)
                if a != b:
                    look_for_rename = True
                fixed_lines.append(normalize_line(line))
                last_diff = i
                file_start_header = False
                file_end_header = False
                first_hunk = True
                binary_file = False
                file_loaded = False
            case "MODE_LINE":
                if last_diff != i - 1:
                    raise NotImplementedError("Missing diff line not yet supported")
                last_mode = i
                fixed_lines.append(normalize_line(line))
            case "INDEX_LINE":
                # mode should be present in index line for all operations except file deletion
                # for deletions, the mode is omitted since the file no longer exists
                index_line = normalize_line(line).strip()
                if not index_line.endswith("..0000000") and not re.search(r' [0-7]{6}$', index_line):
                    # TODO: this is the right idea, but a poor implementation
                    pass
                last_index = i
                if "similarity" in index_line:
                    look_for_rename = True
                fixed_lines.append(normalize_line(line))
                missing_index = False
            case "BINARY_LINE":
                if remove_binary:
                    raise NotImplementedError("Ignoring binary files not yet supported")
                binary_file = True
                fixed_lines.append(normalize_line(line))
            case "RENAME_FROM":
                if not look_for_rename:
                    # handle case where rename from appears without corresponding index line
                    # this may indicate a malformed patch, but we can try to continue
                    warnings.warn(f"Warning: 'rename from' found without expected index line at line {i+1}")
                if binary_file:
                    raise NotImplementedError("Renaming binary files not yet supported")
                if last_index != i - 1:
                    missing_index = True    # need this for existence check in RENAME_TO block
                    fixed_index = "similarity index 100%\n"
                    fixed_lines.append(normalize_line(fixed_index))
                    last_index = i - 1
                look_for_rename = False
                current_file = match_groups[0]
                current_path = Path(current_file).absolute()
                offset = 0
                last_hunk = 0
                if not current_path.is_file():
                    raise IsADirectoryError(f"Rename from header points to a directory, not a file: {current_file}")
                if dir_mode or current_path == original_path:
                    file_lines = read_file_with_fallback_encoding(current_path)
                    original_lines = [l.rstrip('\n') for l in file_lines]
                    fixed_lines.append(normalize_line(line))
                    file_loaded = True
                else:
                    raise FileNotFoundError(f"Filename {current_file} in `rename from` header does not match argument {original}")
            case "RENAME_TO":
                if last_index != i - 2:
                    if missing_index:
                        missing_index = False
                        last_index = i - 2
                    else:
                        raise NotImplementedError("Missing `rename from` header not yet supported.")
                if not file_loaded:
                    # if we're not looking for a rename but encounter "rename to",
                    # this indicates a malformed patch - log warning but continue
                    warnings.warn(
                        f"Warning: unexpected 'rename to' found at line {i + 1} without corresponding 'rename from'"
                    )
                current_file = match_groups[0]
                current_path = Path(current_file).absolute()
                if current_file and current_path.is_dir():
                    raise IsADirectoryError(f"rename to points to a directory, not a file: {current_file}")
                fixed_lines.append(normalize_line(line))
                look_for_rename = False
            case "FILE_HEADER_START":
                if look_for_rename:
                    raise NotImplementedError("Replacing file header with rename not yet supported.")
                if binary_file:
                    raise NotImplementedError("A header block with both 'Binary files differ' and "
                                              "file start/end headers is a confusing state"
                                              "\nfrom which there is no obvious way to recover.")
                if last_index != i - 1:
                    missing_index = True
                    last_index = i - 1
                file_end_header = False
                if current_file and not dir_mode:
                    raise ValueError("Diff references multiple files but only one provided.")
                current_file = match_groups[0]
                if not file_loaded:
                    offset = 0
                    last_hunk = 0
                if current_file == "/dev/null":
                    if last_diff > last_mode:
                        raise NotImplementedError("Missing mode line not yet supported")
                    fixed_lines.append(normalize_line(line))
                    file_start_header = True
                    file_loaded = False
                    continue
                if current_file.startswith("a/"):
                    current_file = current_file[2:]
                else:
                    line = line.replace(current_file, f"a/{current_file}")
                current_path = Path(current_file).absolute()
                if not current_path.exists():
                    raise FileNotFoundError(f"File header start points to non-existent file: {current_file}")
                if not current_path.is_file():
                    raise IsADirectoryError(f"File header start points to a directory, not a file: {current_file}")
                if not file_loaded:
                    if dir_mode or Path(current_file) == Path(original):
                        file_lines = read_file_with_fallback_encoding(current_path)
                        original_lines = [l.rstrip('\n') for l in file_lines]
                        file_loaded = True
                    else:
                        raise FileNotFoundError(f"Filename {current_file} in header does not match argument {original}")
                fixed_lines.append(normalize_line(line))
                file_start_header = True
            case "FILE_HEADER_END":
                if look_for_rename:
                    raise NotImplementedError("Replacing file header with rename not yet supported.")
                if binary_file:
                    raise NotImplementedError("A header block with both 'Binary files differ' and "
                                              "file start/end headers is a confusing state"
                                              "\nfrom which there is no obvious way to recover.")
                dest_file = match_groups[0]
                dest_path = Path(dest_file).absolute()
                if dest_file.startswith("b/"):
                    dest_file = dest_file[2:]
                elif dest_file != "/dev/null":
                    line = line.replace(dest_file, f"b/{dest_file}")
                if missing_index:
                    fixed_index = regenerate_index(current_file, dest_file, original_path)
                    fixed_lines.append(normalize_line(fixed_index))
                    last_index = i - 2
                if not file_start_header:
                    if dest_file == "/dev/null":
                        if last_diff > last_mode:
                            raise NotImplementedError("Missing mode line not yet supported")
                        a = reconstruct_file_header(patch_lines[last_diff], "FILE_HEADER_START")
                        fixed_lines.append(normalize_line(a))
                    else:
                        # reconstruct file start header based on end header
                        a = match_groups[0].replace("b", "a")
                        fixed_lines.append(normalize_line(f"--- {a}\n"))
                    file_start_header = True
                elif current_file == "/dev/null":
                    if dest_file == "/dev/null":
                        raise ValueError("File headers cannot both be /dev/null")
                    elif dest_path.exists():
                        raise FileExistsError(f"File header start /dev/null implies file creation, "
                                              f"but file header end would overwrite existing file: {dest_file}")
                    current_file = dest_file
                    current_path = Path(current_file).absolute()
                    if dir_mode or current_path == original_path:
                        original_lines = []
                        fixed_lines.append(normalize_line(line))
                        file_end_header = True
                    else:
                        raise FileNotFoundError(f"Filename {current_file} in header does not match argument {original}")
                elif dest_file == "/dev/null":
                    current_path = Path(current_file).absolute()
                    if not current_path.exists():
                        raise FileNotFoundError(f"The file being 'deleted' does not exist: {current_file}")
                    if last_mode <= last_diff:
                        fixed_lines.insert(last_diff + 1, "deleted file mode 100644\n")
                        last_index += 1
                    elif "deleted" not in fixed_lines[last_mode]:
                        fixed_lines[last_mode] = "deleted file mode 100644\n"
                    fixed_lines.append(normalize_line(line))
                    file_end_header = True
                elif current_file != dest_file:
                    # this is a rename, original_lines is already set from FILE_HEADER_START
                    fixed_lines.append(normalize_line(line))
                    file_end_header = True
                    first_hunk = True
                else:
                    fixed_lines.append(normalize_line(line))
                    file_end_header = True
            case "HUNK_HEADER":
                if binary_file:
                    raise ValueError("Binary file can't have a hunk header.")
                if look_for_rename:
                    raise ValueError(f"Rename header expected but not found.\n"
                                     f"Hint: look at lines {last_diff}-{i} of the input patch.")
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
                    current_hunk_header = match_groups
                    continue

                try:
                    (
                        fixed_header,
                        offset,
                        last_hunk
                    ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, current_hunk_header, fuzzy=fuzzy)
                except (MissingHunkError, OutOfOrderHunk) as e:
                    e.add_file(current_file)
                    raise e
                fixed_lines.append(fixed_header)
                fixed_lines.extend(current_hunk)
                current_hunk = []
                current_hunk_header = match_groups
            case "END_LINE":
                # if user requested, add a newline at end of file when this marker is present
                if add_newline:
                    fixed_lines.append("\n")
                else:
                    current_hunk.append(normalize_line(line))
            case _:
                # TODO: fix fuzzy string matching to be less granular
                # this is a normal line, add to current hunk
                current_hunk.append(normalize_line(line))

    # we need to process the last hunk since there's no new header to catch it
    try:
        (
            fixed_header,
            offset,
            last_hunk
        ) = capture_hunk(current_hunk, original_lines, offset, last_hunk, current_hunk_header, fuzzy=fuzzy)
    except EmptyHunk:
        return fixed_lines
    except (MissingHunkError, OutOfOrderHunk) as e:
        e.add_file(current_file)
        raise e
    fixed_lines.append(fixed_header)
    fixed_lines.extend(current_hunk)

    # if original file didn't end with a newline, strip out the newline here,
    # unless user explicitly requested to add final newline
    if (
        not add_newline and
        ((original_lines and not original_lines[-1].endswith("\n")) or
         (fixed_lines and len(original_lines) == 0))
    ):
        fixed_lines[-1] = fixed_lines[-1].rstrip("\n")

    return fixed_lines
