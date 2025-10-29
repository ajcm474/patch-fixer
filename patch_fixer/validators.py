"""Pure validation functions for patch components."""

import re
from typing import Tuple, Optional, Dict, Any

from .regex import match_line, regexes
from .errors import InvalidPatchError
from .utils import split_ab


def validate_hunk_header(header_line: str) -> Tuple[int, int, int, int, str]:
    """
    Validate and parse hunk header.

    Parameters
    ----------
    header_line : str
        The hunk header line to parse

    Returns
    -------
    tuple
        (old_start, old_count, new_start, new_count, context)

    Raises
    ------
    InvalidPatchError
        If header is malformed
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

    Parameters
    ----------
    diff_line : str
        The diff header line to parse

    Returns
    -------
    tuple
        (source_file, dest_file) with prefixes removed

    Raises
    ------
    InvalidPatchError
        If header is malformed
    """
    match_groups, line_type = match_line(diff_line)
    if line_type != "DIFF_LINE":
        raise InvalidPatchError(f"Invalid diff header: {diff_line}")

    source, dest = match_groups

    # remove a/ and b/ prefixes
    if source.startswith("a/"):
        source = source[2:]
    if dest.startswith("b/"):
        dest = dest[2:]

    return source, dest


def validate_file_header(header_line: str, header_type: str) -> str:
    """
    Validate file header (--- or +++ line).

    Parameters
    ----------
    header_line : str
        The file header line to parse
    header_type : str
        Either "start" for --- lines or "end" for +++ lines

    Returns
    -------
    str
        The file path from the header

    Raises
    ------
    InvalidPatchError
        If header is malformed
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

    # remove a/ or b/ prefix
    if file_path.startswith("a/"):
        return file_path[2:]
    elif file_path.startswith("b/"):
        return file_path[2:]

    return file_path


def validate_index_line(index_line: str) -> Dict[str, Any]:
    """
    Validate and parse index line.

    Parameters
    ----------
    index_line : str
        The index line to parse

    Returns
    -------
    dict
        Dict with 'old_hash', 'new_hash', and 'mode' keys

    Raises
    ------
    InvalidPatchError
        If line is malformed
    """
    match_groups, line_type = match_line(index_line)
    if line_type != "INDEX_LINE":
        raise InvalidPatchError(f"Invalid index line: {index_line}")

    return {
        'old_hash': match_groups[0],
        'new_hash': match_groups[1],
        'mode': match_groups[2] if len(match_groups) > 2 else None
    }


def validate_similarity_line(similarity_line: str) -> int:
    """
    Validate and parse similarity index line.

    Parameters
    ----------
    similarity_line : str
        The similarity line to parse

    Returns
    -------
    int
        The similarity percentage

    Raises
    ------
    InvalidPatchError
        If line is malformed
    """
    match_groups, line_type = match_line(similarity_line)
    if line_type != "SIMILARITY_LINE":
        raise InvalidPatchError(f"Invalid similarity line: {similarity_line}")

    return int(match_groups[0])


def validate_mode_line(mode_line: str) -> Tuple[str, str]:
    """
    Validate and parse mode line.

    Parameters
    ----------
    mode_line : str
        The mode line to parse

    Returns
    -------
    tuple
        (operation, mode) where operation is 'new', 'deleted', or 'mode'

    Raises
    ------
    InvalidPatchError
        If line is malformed
    """
    match_groups, line_type = match_line(mode_line)
    if line_type != "MODE_LINE":
        raise InvalidPatchError(f"Invalid mode line: {mode_line}")

    # now the regex captures both operation and mode
    operation = match_groups[0]
    mode = match_groups[1] if match_groups[1] else "100644"

    return operation, mode


def is_binary_diff(patch_lines: list) -> bool:
    """
    Check if a patch represents a binary file diff.

    Parameters
    ----------
    patch_lines : list
        Lines from the patch

    Returns
    -------
    bool
        True if this is a binary diff
    """
    for line in patch_lines[:20]:  # check first 20 lines
        if "Binary files" in line or "binary patch" in line.lower():
            return True
    return False


def count_hunk_lines(hunk_lines: list) -> Tuple[int, int, int]:
    """
    Count the number of added, removed, and context lines in a hunk.

    Parameters
    ----------
    hunk_lines : list
        Lines from the hunk (excluding header)

    Returns
    -------
    tuple
        (added_count, removed_count, context_count)
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