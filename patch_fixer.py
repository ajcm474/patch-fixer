#!/usr/bin/env python3
import sys
import re

HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')

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
            i += 1
            continue

        # compute starting line in original file
        old_start = find_hunk_start(body, original_lines) + 1
        old_count = sum(1 for l in body if l.startswith((' ', '-')))
        new_count = sum(1 for l in body if l.startswith((' ', '+')))
        offset += (new_count - old_count)
        new_start = old_start + offset

        # write corrected header
        fixed_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@\n"
        fixed_lines.append(fixed_header)
        fixed_lines.extend(body)

    return fixed_lines

def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <original_file> <broken.patch> <fixed.patch>")
        sys.exit(1)

    original_file = sys.argv[1]
    patch_file = sys.argv[2]
    output_file = sys.argv[3]

    with open(original_file, encoding='utf-8') as f:
        original_lines = [l.rstrip('\n') for l in f.readlines()]

    with open(patch_file, encoding='utf-8') as f:
        patch_lines = f.readlines()

    fixed_lines = fix_patch_with_original(patch_lines, original_lines)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)

    print(f"Fixed patch written to {output_file}")

if __name__ == "__main__":
    main()

