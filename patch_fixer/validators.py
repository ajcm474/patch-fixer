"""Pure validation functions for patch components."""

import re
from typing import Tuple, Optional, Dict, Any

from .regex import match_line, regexes
from .errors import InvalidPatchError


def validate_hunk_header(header_line: str) -> Tuple[int, int, int, int, str]:
    """
    Validate and parse hunk header.

    Returns:
        Tuple of (old_start, old_count, new_start, new_count, context)

    Raises:
        InvalidPatchError: If header is malformed
    """
    match_groups, line_type = match_line(header_line)
    if line_type != "HUNK_HEADER":
        raise InvalidPatchError(f"Invalid hunk header: {header_line}")

    old_start = int(match_groups[0]) if match_groups[0] else 0
    old_count = int(match_groups[1]) if match_groups[1] else 1
    new_start = int(match_groups[2]) if match_groups[2] else 0
    new_count = int(match_groups[3]) if match_groups[3] else 1
    context = match_groups[4] if len(match_groups) > 4 else ""

    return old_start, old_count, new_start, new_count, context


def validate_diff_header(diff_line: str) -> Tuple[str, str]:
    """
    Validate and parse diff header.

    Returns:
        Tuple of (source_file, dest_file)

    Raises:
        InvalidPatchError: If header is malformed
    """
    match_groups, line_type = match_line(diff_line)
    if line_type != "DIFF_LINE":
        raise InvalidPatchError(f"Invalid diff header: {diff_line}")

    source = match_groups[0]
    dest = match_groups[1]

    # strip a/ and b/ prefixes if present
    if source.startswith("a/"):
        source = source[2:]
    if dest.startswith("b/"):
        dest = dest[2:]

    return source, dest


def validate_file_header(header_line: str, header_type: str) -> str:
    """
    Validate file header (--- or +++ line).

    Returns:
        The file path from the header

    Raises:
        InvalidPatchError: If header is malformed
    """
    match_groups, line_type = match_line(header_line)

    if header_type == "start" and line_type != "FILE_HEADER_START":
        raise InvalidPatchError(f"Invalid file start header: {header_line}")
    elif header_type == "end" and line_type != "FILE_HEADER_END":
        raise InvalidPatchError(f"Invalid file end header: {header_line}")

    file_path = match_groups[0]

    # handle special paths
    if file_path in ("/dev/null", "nul"):
        return file_path

    # strip a/ or b/ prefix if present
    if file_path.startswith(("a/", "b/")):
        file_path = file_path[2:]

    return file_path


def validate_index_line(index_line: str) -> Dict[str, Any]:
    """
    Validate and parse index line.

    Returns:
        Dict with 'old_hash', 'new_hash', 'mode', and 'similarity' keys

    Raises:
        InvalidPatchError: If line is malformed
    """
    match_groups, line_type = match_line(index_line)
    if line_type != "INDEX_LINE":
        raise InvalidPatchError(f"Invalid index line: {index_line}")

    result = {
        'old_hash': None,
        'new_hash': None,
        'mode': None,
        'similarity': None
    }

    # check if this is a similarity line
    if "similarity index" in index_line:
        # the regex captures the similarity percentage in group 0
        if match_groups and match_groups[0]:
            result['similarity'] = int(match_groups[0])
    else:
        # regular index line - parse manually since regex doesn't capture
        index_match = re.match(r'^index ([0-9a-f]{7,64})\.\.([0-9a-f]{7,64})(?: ([0-7]{6}))?$', index_line)
        if index_match:
            result['old_hash'] = index_match.group(1)
            result['new_hash'] = index_match.group(2)
            if index_match.group(3):
                result['mode'] = index_match.group(3)

    return result


def validate_mode_line(mode_line: str) -> Tuple[str, str]:
    """
    Validate and parse mode line.

    Returns:
        Tuple of (operation, mode) where operation is 'new', 'deleted', or 'mode'

    Raises:
        InvalidPatchError: If line is malformed
    """
    match_groups, line_type = match_line(mode_line)
    if line_type != "MODE_LINE":
        raise InvalidPatchError(f"Invalid mode line: {mode_line}")

    # extract the mode number manually
    mode_match = re.search(r'mode ([0-7]{6})', mode_line)
    mode = mode_match.group(1) if mode_match else "100644"

    if "new file mode" in mode_line:
        return "new", mode
    elif "deleted file mode" in mode_line:
        return "deleted", mode
    else:
        raise InvalidPatchError(f"Unrecognized mode line: {mode_line}")


def is_binary_diff(patch_lines: list) -> bool:
    """Check if a patch represents a binary file diff."""
    for line in patch_lines[:20]:  # Check first 20 lines
        if "Binary files" in line or "binary patch" in line.lower():
            return True
    return False


def count_hunk_lines(hunk_lines: list) -> Tuple[int, int, int]:
    """
    Count the number of added, removed, and context lines in a hunk.

    Returns:
        Tuple of (added_count, removed_count, context_count)
    """
    added = 0
    removed = 0
    context = 0

    for line in hunk_lines:
        if line.startswith('+'):
            added += 1
        elif line.startswith('-'):
            removed += 1
        elif line.startswith(' ') or line.strip() == "":
            context += 1

    return added, removed, context