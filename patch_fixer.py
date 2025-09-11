#!/usr/bin/env python3
import os
import re
import sys

path_regex = r'(?:/[A-Za-z0-9_.-]+)*'
HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')
FILE_HEADER_START = re.compile(rf'--- a({path_regex}+|/dev/null)')
FILE_HEADER_END = re.compile(rf'\+\+\+ b({path_regex}+)')
DIFF_LINE = re.compile(rf'diff --git a({path_regex}+) b({path_regex}+)')
INDEX_LINE = re.compile(r'index [0-9a-f]{7}\.\.[0-9a-f]{7} [0-7]{6}')
BINARY_LINE = re.compile(rf'Binary files a({path_regex}+) and b({path_regex}+) differ')

def get_matches_with_lineno(regex: re.Pattern[str], raw_text: str):
    """
    Returns the matches and which lines they were found on.

    Parameters
    ----------
    regex : re.Pattern[str]
        The pattern to be matched
    raw_text : str
        Text to be matched against, read straight from a file

    Returns
    -------
    line_numbers : list
    matches : list
    """
    line_numbers = []
    matches = []
    for match in regex.finditer(raw_text):
        start = match.start()
        # compute line number by counting newlines up to this point
        lineno = raw_text.count("\n", 0, start) + 1
        line_numbers.append(lineno)
        matches.append(match.group())
    return line_numbers, matches

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

def fix_patch_with_original(patch_lines, original_lines):
    fixed_lines = []
    i = 0
    offset = 0  # running tally of how perturbed the new line numbers are
    prev_start = 0

    while i < len(patch_lines):
        line = patch_lines[i]
        if line.startswith(('---', '+++')):
            fixed_lines.append(line)
            i += 1
            continue

        # collect hunk body until next header or EOF
        body = []
        while i < len(patch_lines) and not HUNK_HEADER.match(patch_lines[i]) \
              and not patch_lines[i].startswith(('---', '+++')):
            body.append(normalize_line(patch_lines[i]))
            i += 1
        if not body:
            # avoid infinite loop
            i += 1
            continue

        # compute line counts
        old_count = sum(1 for l in body if l.startswith((' ', '-')))
        new_count = sum(1 for l in body if l.startswith((' ', '+')))
        offset += (new_count - old_count)

        # compute starting line in original file
        old_start = find_hunk_start(body, original_lines) + 1

        # if the line number descends, we either have a bad match or a new file
        if old_start < prev_start:
            pass
        else:
            new_start = old_start + offset

        prev_start = old_start

        # write corrected header
        fixed_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@\n"
        fixed_lines.append(fixed_header)
        fixed_lines.extend(body)

    return fixed_lines


def validate_file_headers(patch_raw, original):
    fixed_lines = []
    dir_mode = os.path.isdir(original)

    start_lines, file_header_starts = get_matches_with_lineno(FILE_HEADER_START, patch_raw)
    end_lines, file_header_ends = get_matches_with_lineno(FILE_HEADER_END, patch_raw)

    if not start_lines or not end_lines:
        raise NotImplementedError("This script does not currently add missing file headers")
    if len(start_lines) != len(end_lines):
        raise NotImplementedError("This script does not currently fix mismatched file header counts")

    if dir_mode:
        raise NotImplementedError("Directory mode not supported yet")
    else:
        if len(start_lines) > 1:
            raise ValueError("Cannot apply more than one file header to a single file.")
        if file_header_starts[0] != original:
            raise ValueError(f"File header {file_header_starts[0]} "
                             f"does not match name of input file {original}.\n"
                             f"Please double check that you're applying the right diff.")

    # TODO: remove this when the function has been properly implemented
    fixed_lines = patch_raw.split("\n")

    return fixed_lines


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <original_file> <broken.patch> <fixed.patch>")
        sys.exit(1)

    original = sys.argv[1]
    patch_file = sys.argv[2]
    output_file = sys.argv[3]

    dir_mode = os.path.isdir(original)

    with open(patch_file, encoding='utf-8') as f:
        patch_raw = f.read()

    # Validate and fix file headers
    patch_lines = validate_file_headers(patch_raw, original)

    if dir_mode:
        pass
    else:
        with open(original, encoding='utf-8') as f:
            original_lines = [l.rstrip('\n') for l in f.readlines()]

        fixed_lines = fix_patch_with_original(patch_lines, original_lines)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)

    print(f"Fixed patch written to {output_file}")

if __name__ == "__main__":
    main()

