#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

path_regex = r'(?:/[A-Za-z0-9_.-]+)*'
regexes = {
    "DIFF_LINE": re.compile(rf'diff --git (a{path_regex}+) (b{path_regex}+)'),
    "MODE_LINE": re.compile(rf'(new|deleted) file mode [0-7]{6}'),
    "INDEX_LINE": re.compile(r'index [0-9a-f]{7}\.\.[0-9a-f]{7} [0-7]{6}'),
    "BINARY_LINE": re.compile(rf'Binary files (a{path_regex}+) and (b{path_regex}+) differ'),
    "FILE_HEADER_START": re.compile(rf'--- (a{path_regex}+|/dev/null)'),
    "FILE_HEADER_END": re.compile(rf'\+\+\+ (b{path_regex}+|/dev/null)'),
    "HUNK_HEADER": re.compile(r'^@@ -(\d+),(\d+) \+(\d+),(\d+) @@')
}

def normalize_line(line):
    if line.startswith(('---', '+++', '@@')):
        return line
    if line.startswith('+'):
        # safe to normalize new content
        return '+' + line[1:].rstrip() + "\n"
    if line.startswith((' ', '-')):
        # preserve exactly (only normalize line endings)
        return line.rstrip("\r\n") + "\n"
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
        return 0  # fallback to start if no context
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
    a = a.replace("a/", "./")
    b = b.replace("b/", "./")
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


def fix_patch(patch_lines, original):
    dir_mode = os.path.isdir(original)

    # make relative paths in the diff work
    os.chdir(Path(original).parent)

    fixed_lines = []
    current_hunk = []
    current_file = None
    offset = 0      # running tally of how perturbed the new line numbers are
    last_hunk = 0   # start of last hunk (fixed lineno in changed file)
    last_diff = 0   # start of last diff (lineno in patch file itself)
    last_mode = 0   # most recent "new file mode" or "deleted file mode" line
    last_index = 0  # most recent "index <hex>..<hex> <file_permissions>" line
    file_start_header = False
    file_end_header = False

    for i, line in enumerate(patch_lines):
        match_groups, line_type = match_line(line)
        match line_type:
            case "DIFF_LINE":
                a, b = split_ab(match_groups)
                if a != b:
                    raise ValueError(f"Diff paths do not match: \n{a}\n{b}")
                fixed_lines.append(line)
                last_diff = i
                file_start_header = False
                file_end_header = False
            case "MODE_LINE":
                last_mode = i
                if last_diff != i - 1:
                    raise NotImplementedError("Missing diff line not yet supported")
                fixed_lines.append(line)
            case "INDEX_LINE":
                last_index = i
                fixed_lines.append(line)
            case "BINARY_LINE":
                raise NotImplementedError("Binary files not supported yet")
            case "FILE_HEADER_START":
                if last_index != i - 1:
                    raise NotImplementedError("Missing index line not yet supported")
                file_end_header = False
                if current_file and not dir_mode:
                    raise ValueError("Diff references multiple files but only one provided.")
                current_file = match_groups[0]
                offset = 0
                last_hunk = 0
                if current_file == "/dev/null":
                    if last_diff > last_mode:
                        raise NotImplementedError("Missing mode line not yet supported")
                    fixed_lines.append(line)
                    file_start_header = True
                    continue
                if not os.path.exists(current_file):
                    raise FileNotFoundError(f"File header start points to non-existent file: {current_file}")
                if dir_mode or Path(current_file) == Path(original):
                    with open(current_file, encoding='utf-8') as f:
                        original_lines = [l.rstrip('\n') for l in f.readlines()]
                    fixed_lines.append(line)
                    file_start_header = True
                else:
                    raise FileNotFoundError(f"Filename {current_file} in header does not match command line argument {original}")
            case "FILE_HEADER_END":
                dest_file = match_groups[0]
                if not file_start_header:
                    if dest_file == "/dev/null":
                        if last_diff > last_mode:
                            raise NotImplementedError("Missing mode line not yet supported")
                        a = reconstruct_file_header(patch_lines[last_diff], "FILE_HEADER_START")
                        fixed_lines.append(a)
                    else:
                        # reconstruct file start header based on end header
                        a = dest_file.replace("b", "a")
                        fixed_lines.append(f"--- {a}")
                    file_start_header = True
                elif current_file == "/dev/null":
                    current_file = dest_file
                    if not os.path.exists(current_file):
                        raise FileNotFoundError(f"File header end points to non-existent file: {current_file}")
                    elif dest_file == "/dev/null":
                        raise ValueError("File headers cannot both be /dev/null")
                    if dir_mode or Path(current_file) == Path(original):
                        # TODO: in dir mode, verify that current file exists in original path
                        with open(current_file, encoding='utf-8') as f:
                            original_lines = [l.rstrip('\n') for l in f.readlines()]
                        fixed_lines.append(line)
                        file_end_header = True
                    else:
                        raise FileNotFoundError(f"Filename {current_file} in header does not match command line argument {original}")
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
                        fixed_lines.append(a)
                        file_start_header = True
                        current_file = split_ab(match_line(diff_line))[0]
                    b = reconstruct_file_header(diff_line, "FILE_HEADER_END")
                    fixed_lines.append(b)
                    file_end_header = True

                # compute line counts
                old_count = sum(1 for l in current_hunk if l.startswith((' ', '-')))
                new_count = sum(1 for l in current_hunk if l.startswith((' ', '+')))
                offset += (new_count - old_count)

                # compute starting line in original file
                old_start = find_hunk_start(current_hunk, original_lines) + 1

                # if the line number descends, we either have a bad match or a new file
                if old_start < last_hunk:
                    raise NotImplementedError(f"Giving up; hunk not found in {current_file}: \n\n{current_hunk}")
                else:
                    new_start = old_start + offset

                last_hunk = old_start

                # write corrected header
                fixed_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@\n"
                fixed_lines.append(fixed_header)
                fixed_lines.extend(current_hunk)
                current_hunk = []
            case _:
                # TODO: fuzzy string matching
                # this is a normal line, add to current hunk
                current_hunk.append(normalize_line(line))

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

