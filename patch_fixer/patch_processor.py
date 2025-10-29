"""Helper functions for processing patch components in fix_patch."""

import os
import re
import warnings
from pathlib import Path
from typing import List, Tuple, Optional

from git import Repo

from .errors import MissingHunkError, OutOfOrderHunk, EmptyHunk
from .hunk import capture_hunk
from .regex import match_line
from .utils import normalize_line, split_ab, read_file_with_fallback_encoding
from .validators import validate_mode_line, validate_file_header


def process_diff_line(line: str, match_groups: tuple) -> Tuple[str, str, bool]:
    """
    Process a diff line and extract file information.

    Parameters
    ----------
    line : str
        The diff line
    match_groups : tuple
        Regex match groups from the diff line

    Returns
    -------
    tuple
        (source_file, dest_file, look_for_rename)
    """
    a, b = split_ab(match_groups)
    look_for_rename = (a != b)
    return a, b, look_for_rename


def process_mode_line(line: str, last_diff_idx: int, current_idx: int) -> str:
    """
    Process a mode line and validate it appears after diff.

    Parameters
    ----------
    line : str
        The mode line
    last_diff_idx : int
        Index of the last diff line
    current_idx : int
        Current line index

    Returns
    -------
    str
        Normalized mode line

    Raises
    ------
    NotImplementedError
        If mode line doesn't immediately follow diff line
    """
    if last_diff_idx != current_idx - 1:
        raise NotImplementedError("Missing diff line not yet supported")
    return normalize_line(line)


def process_index_line(line: str, match_groups: tuple) -> Tuple[str, bool]:
    """
    Process an index line and check for similarity.

    Parameters
    ----------
    line : str
        The index line
    match_groups : tuple
        Regex match groups

    Returns
    -------
    tuple
        (normalized_line, is_similarity)
    """
    # mode should be present in index line for all operations except file deletion
    # for deletions, the mode is omitted since the file no longer exists
    index_line = normalize_line(line).strip()
    if not index_line.endswith("..0000000") and not re.search(r' [0-7]{6}$', index_line):
        # TODO: this is the right idea, but a poor implementation
        pass

    return normalize_line(line), False


def process_similarity_line(line: str, match_groups: tuple) -> Tuple[str, int]:
    """
    Process a similarity index line.

    Parameters
    ----------
    line : str
        The similarity line
    match_groups : tuple
        Regex match groups

    Returns
    -------
    tuple
        (normalized_line, similarity_percentage)
    """
    similarity = int(match_groups[0]) if match_groups[0] else 100
    return normalize_line(line), similarity


def process_rename_from(
        line: str,
        match_groups: tuple,
        look_for_rename: bool,
        binary_file: bool,
        missing_index: bool,
        last_index_idx: int,
        current_idx: int
) -> Tuple[str, Path, List[str], List[str]]:
    """
    Process a 'rename from' header.

    Parameters
    ----------
    line : str
        The rename from line
    match_groups : tuple
        Regex match groups
    look_for_rename : bool
        Whether we're expecting a rename
    binary_file : bool
        Whether this is a binary file
    missing_index : bool
        Whether the index line is missing
    last_index_idx : int
        Index of the last index line
    current_idx : int
        Current line index

    Returns
    -------
    tuple
        (current_file, current_path, fixed_lines, original_lines)
    """
    if not look_for_rename:
        # handle case where rename from appears without corresponding index line
        # this may indicate a malformed patch, but we can try to continue
        warnings.warn(
            f"Warning: 'rename from' found without expected index line at line {current_idx + 1}"
        )
    if binary_file:
        raise NotImplementedError("Renaming binary files not yet supported")

    fixed_lines = []
    if last_index_idx != current_idx - 1 and not missing_index:
        fixed_lines.append(normalize_line("similarity index 100%\n"))

    current_file = match_groups[0]
    current_path = Path(current_file).absolute()

    if not current_path.is_file():
        raise IsADirectoryError(
            f"Rename from header points to a directory, not a file: {current_file}"
        )

    fixed_lines.append(normalize_line(line))
    return current_file, current_path, fixed_lines, []


def process_rename_to(
        line: str,
        match_groups: tuple,
        missing_index: bool,
        last_index_idx: int,
        current_idx: int,
        file_loaded: bool
) -> Tuple[str, Path]:
    """
    Process a 'rename to' header.

    Parameters
    ----------
    line : str
        The rename to line
    match_groups : tuple
        Regex match groups
    missing_index : bool
        Whether the index line is missing
    last_index_idx : int
        Index of the last index line
    current_idx : int
        Current line index
    file_loaded : bool
        Whether the file has been loaded

    Returns
    -------
    tuple
        (dest_file, dest_path)
    """
    if last_index_idx != current_idx - 2:
        if not missing_index:
            raise NotImplementedError("Missing `rename from` header not yet supported.")

    if not file_loaded:
        # if we're not looking for a rename but encounter "rename to",
        # this indicates a malformed patch - log warning but continue
        warnings.warn(
            f"Warning: unexpected 'rename to' found at line {current_idx + 1} without corresponding 'rename from'"
        )

    dest_file = match_groups[0]
    dest_path = Path(dest_file).absolute()

    if dest_file and dest_path.is_dir():
        raise IsADirectoryError(
            f"rename to points to a directory, not a file: {dest_file}"
        )

    return dest_file, dest_path


def reconstruct_file_header(diff_line: str, header_type: str) -> str:
    """
    Reconstruct file header based on last diff line.

    Parameters
    ----------
    diff_line : str
        The diff line to base the header on
    header_type : str
        Either "FILE_HEADER_START" or "FILE_HEADER_END"

    Returns
    -------
    str
        Reconstructed header line
    """
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


def regenerate_index(old_path: str, new_path: str, cur_dir: Path) -> str:
    """
    Regenerate a missing index line.

    Parameters
    ----------
    old_path : str
        Path to the old file
    new_path : str
        Path to the new file
    cur_dir : Path
        Current directory (must be a git repo)

    Returns
    -------
    str
        Regenerated index line
    """
    repo = Repo(cur_dir)

    # common git file modes: 100644 (regular file), 100755 (executable file),
    # 120000 (symbolic link), 160000 (submodule), 040000 (tree/directory)
    # TODO: guess mode based on above information
    mode = " 100644"

    # file deletion
    if new_path == "/dev/null":
        old_sha = repo.git.hash_object(old_path)
        new_sha = "0000000"
        mode = ""  # deleted file can't have a mode
    else:
        raise NotImplementedError(
            "Regenerating index not yet supported in the general case, "
            "as this would require manually applying the patch first."
        )

    return f"index {old_sha}..{new_sha}{mode}\n"


def load_original_file(
        current_path: Path,
        original_path: Path,
        dir_mode: bool,
        current_file: str,
        original: str
) -> List[str]:
    """
    Load the original file content.

    Parameters
    ----------
    current_path : Path
        Path to the current file
    original_path : Path
        Path to the original file/directory
    dir_mode : bool
        Whether we're in directory mode
    current_file : str
        Current file name
    original : str
        Original path argument

    Returns
    -------
    List[str]
        Lines from the original file (without newlines)

    Raises
    ------
    FileNotFoundError
        If the file doesn't exist or doesn't match the expected path
    """
    if dir_mode or current_path == original_path:
        file_lines = read_file_with_fallback_encoding(current_path)
        return [l.rstrip('\n') for l in file_lines]
    else:
        raise FileNotFoundError(
            f"Filename {current_file} in header does not match argument {original}"
        )