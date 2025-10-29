"""Pure transformation functions for patch components."""

import re
from typing import List, Tuple, Optional

from .validators import validate_hunk_header, count_hunk_lines
from .hunk import find_hunk_start
from .errors import MissingHunkError, OutOfOrderHunk


def fix_hunk_header(
        hunk_lines: List[str],
        original_lines: List[str],
        offset: int = 0,
        last_hunk_pos: int = 0,
        fuzzy: bool = False
) -> Tuple[str, int, int]:
    """
    Fix line numbers in hunk header based on actual file content.

    Args:
        hunk_lines: Lines of the hunk including header
        original_lines: Lines from the original file
        offset: Current line number offset from previous hunks
        last_hunk_pos: Position where the last hunk ended
        fuzzy: Whether to use fuzzy matching

    Returns:
        Tuple of (fixed_header, new_offset, new_last_hunk_pos)
    """
    if not hunk_lines:
        raise ValueError("Empty hunk")

    # parse the original header
    try:
        old_start, old_count, new_start, new_count, context = validate_hunk_header(hunk_lines[0])
    except:
        # if header is malformed, try to reconstruct
        context = ""
        if "@@" in hunk_lines[0]:
            parts = hunk_lines[0].split("@@")
            if len(parts) > 2:
                context = "@@".join(parts[2:]).rstrip()
        old_start = 1
        old_count = len([l for l in hunk_lines[1:] if not l.startswith('+')])
        new_count = len([l for l in hunk_lines[1:] if not l.startswith('-')])

    # find where this hunk actually belongs
    hunk_content = hunk_lines[1:] if len(hunk_lines) > 1 else []

    if not original_lines:  # new file
        actual_old_start = 0
        actual_old_count = 0
        actual_new_start = 1
        actual_new_count = new_count
    elif old_count == 0:  # pure addition
        actual_old_start = old_start
        actual_old_count = 0
        actual_new_start = old_start + offset
        actual_new_count = new_count
    else:
        # find the hunk in the original file
        try:
            found_pos = find_hunk_start(hunk_content, original_lines[last_hunk_pos:], fuzzy)
            actual_old_start = last_hunk_pos + found_pos + 1  # Convert to 1-indexed
        except MissingHunkError:
            # try from beginning if not found after last position
            try:
                found_pos = find_hunk_start(hunk_content, original_lines, fuzzy)
                actual_old_start = found_pos + 1
            except MissingHunkError:
                # fall back to original position
                actual_old_start = old_start

        actual_old_count = old_count
        actual_new_start = actual_old_start + offset
        actual_new_count = new_count

    # update offset for next hunk
    new_offset = offset + (new_count - old_count)
    new_last_pos = actual_old_start - 1 + old_count  # 0-indexed position

    # format the header
    old_part = f"{actual_old_start},{actual_old_count}" if actual_old_count != 1 else str(actual_old_start)
    new_part = f"{actual_new_start},{actual_new_count}" if actual_new_count != 1 else str(actual_new_start)

    fixed_header = f"@@ -{old_part} +{new_part} @@{context}\n"

    return fixed_header, new_offset, new_last_pos


def fix_file_paths(header_lines: List[str]) -> List[str]:
    """
    Normalize file paths in patch headers.

    Ensures consistent a/ and b/ prefixes and handles special cases.
    """
    fixed = []

    for line in header_lines:
        if line.startswith("diff --git"):
            # ensure a/ and b/ prefixes
            parts = line.split()
            if len(parts) >= 4:
                src = parts[2]
                dst = parts[3]

                if not src.startswith("a/") and src != "/dev/null":
                    src = f"a/{src}"
                if not dst.startswith("b/") and dst != "/dev/null":
                    dst = f"b/{dst}"

                fixed.append(f"diff --git {src} {dst}\n")
            else:
                fixed.append(line)

        elif line.startswith("---"):
            # handle source file header
            parts = line.split(None, 1)
            if len(parts) > 1:
                path = parts[1].rstrip()
                if path != "/dev/null" and not path.startswith("a/"):
                    path = f"a/{path}"
                fixed.append(f"--- {path}\n")
            else:
                fixed.append(line)

        elif line.startswith("+++"):
            # handle destination file header
            parts = line.split(None, 1)
            if len(parts) > 1:
                path = parts[1].rstrip()
                if path != "/dev/null" and not path.startswith("b/"):
                    path = f"b/{path}"
                fixed.append(f"+++ {path}\n")
            else:
                fixed.append(line)

        else:
            fixed.append(line)

    return fixed


def normalize_line_endings(lines: List[str]) -> List[str]:
    """Ensure all lines have consistent line endings."""
    normalized = []
    for line in lines:
        # remove any existing line ending
        clean = line.rstrip('\r\n')
        # add Unix line ending
        if clean or line.endswith(('\n', '\r\n', '\r')):
            normalized.append(clean + '\n')
        else:
            normalized.append(clean)
    return normalized


def add_final_newlines(patch_lines: List[str]) -> List[str]:
    """
    Process 'No newline at end of file' markers correctly.

    Ensures that when such markers are present, the preceding line
    doesn't have a newline character.
    """
    fixed = []
    i = 0

    while i < len(patch_lines):
        line = patch_lines[i]

        # check if next line is a "no newline" marker
        if i + 1 < len(patch_lines) and "No newline at end of file" in patch_lines[i + 1]:
            # current line should not end with newline
            fixed.append(line.rstrip('\r\n'))
            i += 1  # Skip the marker line
        else:
            fixed.append(line)

        i += 1

    return fixed


def fix_malformed_headers(patch_lines: List[str]) -> List[str]:
    """
    Attempt to fix common header malformations.

    This includes:
    - Missing diff headers
    - Incorrect file path formats
    - Missing index lines
    """
    fixed = []
    in_diff = False

    for i, line in enumerate(patch_lines):
        # detect start of a new diff block
        if line.startswith("diff "):
            in_diff = True

            # ensure it's properly formatted
            if not line.startswith("diff --git"):
                # try to extract file names and reformat
                parts = line.split()
                if len(parts) >= 3:
                    # guess the source and dest files
                    src = parts[-2] if len(parts) > 2 else "unknown"
                    dst = parts[-1] if len(parts) > 1 else src
                    line = f"diff --git a/{src} b/{dst}\n"

        # ensure file headers have proper prefixes
        elif line.startswith("---") and in_diff:
            parts = line.split(None, 1)
            if len(parts) > 1 and parts[1].strip() not in ("/dev/null", "nul"):
                path = parts[1].strip()
                if not path.startswith("a/"):
                    line = f"--- a/{path}\n"

        elif line.startswith("+++") and in_diff:
            parts = line.split(None, 1)
            if len(parts) > 1 and parts[1].strip() not in ("/dev/null", "nul"):
                path = parts[1].strip()
                if not path.startswith("b/"):
                    line = f"+++ b/{path}\n"

        fixed.append(line)

    return fixed


def split_patch_by_file(patch_lines: List[str]) -> List[Tuple[str, List[str]]]:
    """
    Split a patch into individual file patches.

    Returns:
        List of tuples (filename, patch_lines_for_file)
    """
    files = []
    current_file = None
    current_lines = []

    for line in patch_lines:
        if line.startswith("diff "):
            # save previous file if any
            if current_file and current_lines:
                files.append((current_file, current_lines))

            # start new file
            # extract filename from diff line
            match = re.search(r'diff.*?a/(.*?)\s+b/', line)
            if match:
                current_file = match.group(1)
            else:
                # fallback: try to extract any filename
                parts = line.split()
                current_file = parts[-1] if parts else "unknown"
                if current_file.startswith("b/"):
                    current_file = current_file[2:]

            current_lines = [line]
        elif current_lines is not None:
            current_lines.append(line)

    # don't forget the last file
    if current_file and current_lines:
        files.append((current_file, current_lines))

    return files