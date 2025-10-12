"""
Idea:

1. main function takes in:
    a. patch file
    b. list of files to split out
2. reads patch file, splits based on file headers (assumed to be valid)
3. for each file being patched:
    a. if the file is in the list, send its hunks to output 1
    b. otherwise send its hunks to output 2
    c. hunks include all header lines so each output is a valid diff

Could share some functionality with refactored, modular version of fix_patch
"""

import re
from typing import List, Tuple

from .regex import match_line
from .utils import normalize_line, split_ab


def get_file_path_from_diff(line: str) -> str:
    """Extract the file path from a diff line."""
    match_groups, line_type = match_line(line)
    if line_type != "DIFF_LINE":
        raise ValueError(f"Expected DIFF_LINE but got {line_type}")

    # get the 'a' path (source file)
    a_path, _ = split_ab(match_groups)
    return a_path


def split_patch(patch_lines: List[str], files_to_include: List[str]) -> Tuple[List[str], List[str]]:
    """
    Split a patch into two parts based on a list of files to include.

    Parameters
    ----------
    patch_lines : List[str]
        Lines of the patch file to split.
    files_to_include : List[str]
        List of file paths (relative, starting with ./) to include in the first output.
        Files not in this list go to the second output.

    Returns
    -------
    included_lines : List[str]
        Lines for the patch containing only the included files.
    excluded_lines : List[str]
        Lines for the patch containing all other files.

    Notes
    -----
    The function preserves all header information for each file's hunks
    to ensure both output patches are valid. File paths are normalized
    to start with './' for comparison purposes.

    Raises
    ------
    ValueError
        If the patch format is invalid or cannot be parsed.
    """
    if not patch_lines:
        raise ValueError("Empty patch provided")

    # normalize file paths to include
    normalized_include = set()
    for path in files_to_include:
        if not path.startswith("./"):
            path = f"./{path}"
        normalized_include.add(path)

    included_lines = []
    excluded_lines = []
    current_file_lines = []
    current_file_path = None
    in_file_block = False

    for line in patch_lines:
        match_groups, line_type = match_line(line)

        if line_type == "DIFF_LINE":
            # start of a new file block
            if in_file_block and current_file_lines:
                # output the previous file block
                if current_file_path in normalized_include:
                    included_lines.extend(current_file_lines)
                else:
                    excluded_lines.extend(current_file_lines)

            # start collecting new file block
            current_file_lines = [normalize_line(line)]
            current_file_path = get_file_path_from_diff(line)
            in_file_block = True

        elif in_file_block:
            # continue collecting lines for current file
            current_file_lines.append(normalize_line(line))

        else:
            # lines before any diff (shouldn't happen in well-formed patches)
            # add to both outputs to preserve any global headers
            normalized = normalize_line(line)
            included_lines.append(normalized)
            excluded_lines.append(normalized)

    # don't forget the last file block
    if in_file_block and current_file_lines:
        if current_file_path in normalized_include:
            included_lines.extend(current_file_lines)
        else:
            excluded_lines.extend(current_file_lines)

    # handle edge case where no files were split (no diff lines)
    if not in_file_block:
        # patch had no diff lines at all
        return patch_lines, []

    return included_lines, excluded_lines