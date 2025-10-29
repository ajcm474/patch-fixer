#!/usr/bin/env python3
import os
import re
import warnings
from pathlib import Path

from git import Repo

from patch_fixer.errors import MissingHunkError, OutOfOrderHunk, EmptyHunk
from patch_fixer.hunk import capture_hunk
from patch_fixer.regex import match_line
from patch_fixer.utils import normalize_line, split_ab, read_file_with_fallback_encoding
from patch_fixer.patch_processor import (
    process_diff_line,
    process_mode_line,
    process_index_line,
    process_similarity_line,
    process_rename_from,
    process_rename_to,
    reconstruct_file_header,
    regenerate_index,
    load_original_file
)


class PatchState:
    """State tracking for patch processing."""

    def __init__(self):
        self.fixed_lines = []
        self.current_hunk = []
        self.current_file = None
        self.first_hunk = True
        self.offset = 0
        self.last_hunk = 0
        self.last_diff = 0
        self.last_mode = 0
        self.last_index = 0
        self.file_start_header = False
        self.file_end_header = False
        self.look_for_rename = False
        self.missing_index = False
        self.binary_file = False
        self.current_hunk_header = ()
        self.original_lines = []
        self.file_loaded = False
        self.similarity = 0


def handle_diff_line(state, line, match_groups, i):
    """Process a DIFF_LINE."""
    # finish previous hunk if any
    if not state.first_hunk:
        try:
            fixed_header, state.offset, state.last_hunk = capture_hunk(
                state.current_hunk, state.original_lines,
                state.offset, state.last_hunk,
                state.current_hunk_header
            )
            state.fixed_lines.append(fixed_header)
            state.fixed_lines.extend(state.current_hunk)
        except (MissingHunkError, OutOfOrderHunk) as e:
            e.add_file(state.current_file)
            raise e
        state.current_hunk = []

    # process new diff
    a, b = split_ab(match_groups)
    state.look_for_rename = (a != b)
    state.fixed_lines.append(normalize_line(line))

    # reset state for new file
    state.last_diff = i
    state.file_start_header = False
    state.file_end_header = False
    state.first_hunk = True
    state.binary_file = False
    state.file_loaded = False
    state.similarity = 0


def handle_mode_line(state, line, i):
    """Process a MODE_LINE."""
    if state.last_diff != i - 1:
        raise NotImplementedError("Missing diff line not yet supported")
    state.last_mode = i
    state.fixed_lines.append(normalize_line(line))


def handle_index_line(state, line, match_groups, i):
    """Process an INDEX_LINE."""
    # check if mode is missing
    index_line = normalize_line(line).strip()
    if not index_line.endswith("..0000000") and ' ' not in index_line.split('..')[-1]:
        # TODO: add mode if missing
        pass

    state.last_index = i
    state.fixed_lines.append(normalize_line(line))
    state.missing_index = False


def handle_similarity_line(state, line, match_groups, i):
    """Process a SIMILARITY_LINE."""
    state.similarity = int(match_groups[0]) if match_groups[0] else 100
    state.look_for_rename = True
    state.last_index = i
    state.fixed_lines.append(normalize_line(line))
    state.missing_index = False


def handle_binary_line(state, line, remove_binary):
    """Process a BINARY_LINE."""
    if remove_binary:
        raise NotImplementedError("Ignoring binary files not yet supported")
    state.binary_file = True
    state.fixed_lines.append(normalize_line(line))


def handle_rename_from(state, line, match_groups, i, dir_mode, original_path, original):
    """Process a RENAME_FROM line."""
    if not state.look_for_rename:
        warnings.warn(f"Warning: 'rename from' found without expected index line at line {i + 1}")

    if state.binary_file:
        raise NotImplementedError("Renaming binary files not yet supported")

    if state.last_index != i - 1:
        state.missing_index = True
        state.fixed_lines.append(normalize_line("similarity index 100%\n"))
        state.last_index = i - 1

    state.look_for_rename = False
    state.current_file = match_groups[0]
    current_path = Path(state.current_file).absolute()
    state.offset = 0
    state.last_hunk = 0

    if not current_path.is_file():
        raise IsADirectoryError(f"Rename from header points to a directory, not a file: {state.current_file}")

    if dir_mode or current_path == original_path:
        file_lines = read_file_with_fallback_encoding(current_path)
        state.original_lines = [l.rstrip('\n') for l in file_lines]
        state.fixed_lines.append(normalize_line(line))
        state.file_loaded = True
    else:
        raise FileNotFoundError(
            f"Filename {state.current_file} in `rename from` header does not match argument {original}")


def handle_rename_to(state, line, match_groups, i):
    """Process a RENAME_TO line."""
    if state.last_index != i - 2:
        if state.missing_index:
            state.missing_index = False
            state.last_index = i - 2
        else:
            raise NotImplementedError("Missing `rename from` header not yet supported.")

    if not state.file_loaded:
        warnings.warn(f"Warning: unexpected 'rename to' found at line {i + 1} without corresponding 'rename from'")

    state.current_file = match_groups[0]
    current_path = Path(state.current_file).absolute()

    if state.current_file and current_path.is_dir():
        raise IsADirectoryError(f"rename to points to a directory, not a file: {state.current_file}")

    state.fixed_lines.append(normalize_line(line))
    state.look_for_rename = False


def handle_file_header_start(state, line, match_groups, i, patch_lines, dir_mode, original_path, original):
    """Process a FILE_HEADER_START (---) line."""
    if state.look_for_rename:
        raise NotImplementedError("Replacing file header with rename not yet supported.")

    if state.binary_file:
        raise NotImplementedError(
            "A header block with both 'Binary files differ' and file start/end headers is a confusing state")

    state.current_file = match_groups[0]
    if state.current_file == "/dev/null":
        state.fixed_lines.append(normalize_line(line))
        state.file_start_header = True
        return

    # strip prefix
    if state.current_file.startswith("a/"):
        state.current_file = state.current_file[2:]
    else:
        line = line.replace(state.current_file, f"a/{state.current_file}")

    current_path = Path(state.current_file).absolute()

    if not current_path.exists():
        # check if this is a file creation
        if i + 1 < len(patch_lines):
            next_groups, next_type = match_line(patch_lines[i + 1])
            if next_type == "FILE_HEADER_END" and next_groups[0] != "/dev/null":
                # file creation - skip the error
                state.fixed_lines.append(normalize_line(line))
                state.file_start_header = True
                state.original_lines = []
                state.file_loaded = True
                return
        raise FileNotFoundError(f"File header start points to non-existent file: {state.current_file}")

    if not current_path.is_file():
        raise IsADirectoryError(f"File header start points to a directory, not a file: {state.current_file}")

    if dir_mode or current_path == original_path:
        file_lines = read_file_with_fallback_encoding(current_path)
        state.original_lines = [l.rstrip('\n') for l in file_lines]
        state.file_loaded = True
    else:
        raise FileNotFoundError(f"Filename {state.current_file} in header does not match argument {original}")

    state.fixed_lines.append(normalize_line(line))
    state.file_start_header = True
    state.offset = 0
    state.last_hunk = 0


def handle_file_header_end(state, line, match_groups, i, patch_lines, original_path, dir_mode, original):
    """Process a FILE_HEADER_END (+++) line."""
    dest_file = match_groups[0]
    dest_path = Path(dest_file if not dest_file.startswith("b/") else dest_file[2:]).absolute()

    if dest_file.startswith("b/"):
        dest_file = dest_file[2:]
    elif dest_file != "/dev/null":
        line = line.replace(dest_file, f"b/{dest_file}")

    # handle missing index line
    if state.missing_index:
        fixed_index = regenerate_index(state.current_file, dest_file, original_path)
        state.fixed_lines.append(normalize_line(fixed_index))
        state.last_index = i - 2

    # handle missing file start header
    if not state.file_start_header:
        if dest_file == "/dev/null":
            if state.last_diff > state.last_mode:
                raise NotImplementedError("Missing mode line not yet supported")
            a = reconstruct_file_header(patch_lines[state.last_diff], "FILE_HEADER_START")
            state.fixed_lines.append(normalize_line(a))
        else:
            # reconstruct file start header based on end header
            a = match_groups[0].replace("b", "a")
            state.fixed_lines.append(normalize_line(f"--- {a}\n"))
        state.file_start_header = True
    elif state.current_file == "/dev/null":
        # file creation
        if dest_file == "/dev/null":
            raise ValueError("File headers cannot both be /dev/null")
        elif dest_path.exists():
            raise FileExistsError(
                f"File header start /dev/null implies file creation, but file header end would overwrite existing file: {dest_file}")

        state.current_file = dest_file
        current_path = Path(state.current_file).absolute()

        if dir_mode or current_path == original_path:
            state.original_lines = []
            state.fixed_lines.append(normalize_line(line))
            state.file_end_header = True
        else:
            raise FileNotFoundError(f"Filename {state.current_file} in header does not match argument {original}")
    elif dest_file == "/dev/null":
        # file deletion
        current_path = Path(state.current_file).absolute()
        if not current_path.exists():
            raise FileNotFoundError(f"The file being 'deleted' does not exist: {state.current_file}")

        # handle missing deleted file mode line
        if state.last_mode <= state.last_diff:
            state.fixed_lines.insert(state.last_diff + 1, "deleted file mode 100644\n")
            state.last_index += 1
        elif "deleted" not in state.fixed_lines[state.last_mode]:
            state.fixed_lines[state.last_mode] = "deleted file mode 100644\n"

        state.fixed_lines.append(normalize_line(line))
        state.file_end_header = True

        # load file if not already loaded
        if not state.file_loaded:
            if dir_mode or current_path == original_path:
                file_lines = read_file_with_fallback_encoding(current_path)
                state.original_lines = [l.rstrip('\n') for l in file_lines]
                state.file_loaded = True
            else:
                raise FileNotFoundError(f"Filename {state.current_file} in header does not match argument {original}")
    elif state.current_file != dest_file:
        # this is a rename, original_lines is already set from FILE_HEADER_START
        state.fixed_lines.append(normalize_line(line))
        state.file_end_header = True
        state.first_hunk = True
    else:
        state.fixed_lines.append(normalize_line(line))
        state.file_end_header = True


def handle_hunk_header(state, line, match_groups, i, patch_lines, fuzzy, pre_hunk_hook, post_hunk_hook, strict):
    """Process a HUNK_HEADER line."""
    if state.binary_file:
        raise ValueError("Binary file can't have a hunk header.")

    if state.look_for_rename:
        raise ValueError(
            f"Rename header expected but not found.\nHint: look at lines {state.last_diff}-{i} of the input patch.")

    # fix missing file headers before capturing the hunk
    if not state.file_end_header:
        diff_line = patch_lines[state.last_diff]
        if not state.file_start_header:
            a = reconstruct_file_header(diff_line, "FILE_HEADER_START")
            state.fixed_lines.append(normalize_line(a))
            state.file_start_header = True
            state.current_file = split_ab(match_line(diff_line)[0])[0]

        b = reconstruct_file_header(diff_line, "FILE_HEADER_END")
        state.fixed_lines.append(normalize_line(b))
        state.file_end_header = True

    # we can't fix the hunk header before we've captured a hunk
    if state.first_hunk:
        state.first_hunk = False
        state.current_hunk_header = match_groups
        return

    # apply pre-hunk hook if provided
    if pre_hunk_hook:
        hook_context = {
            'current_file': state.current_file,
            'original_lines': state.original_lines,
            'offset': state.offset,
            'last_hunk': state.last_hunk
        }
        state.current_hunk = pre_hunk_hook(state.current_hunk, hook_context)

    try:
        fixed_header, state.offset, state.last_hunk = capture_hunk(
            state.current_hunk, state.original_lines,
            state.offset, state.last_hunk,
            state.current_hunk_header, fuzzy=fuzzy
        )
    except (MissingHunkError, OutOfOrderHunk) as e:
        if strict:
            raise e
        e.add_file(state.current_file)
        raise e

    # apply post-hunk hook if provided
    if post_hunk_hook:
        hook_context = {
            'current_file': state.current_file,
            'fixed_header': fixed_header,
            'offset': state.offset,
            'last_hunk': state.last_hunk
        }
        state.current_hunk = post_hunk_hook(state.current_hunk, hook_context)

    state.fixed_lines.append(fixed_header)
    state.fixed_lines.extend(state.current_hunk)
    state.current_hunk = []
    state.current_hunk_header = match_groups


def handle_end_line(state, line, add_newline):
    """Process an END_LINE (No newline at end of file)."""
    if add_newline:
        # add newline directly to fixed_lines, not to current_hunk
        state.fixed_lines.append("\n")
    else:
        state.current_hunk.append(normalize_line(line))


def fix_patch(patch_lines, original, remove_binary=False, fuzzy=False, add_newline=False,
              strict=False, pre_hunk_hook=None, post_hunk_hook=None):
    """
    Fix a potentially malformed patch to make it applicable.

    Parameters
    ----------
    patch_lines : list
        List of lines from the patch file
    original : str or Path
        Path to the original file or directory being patched
    remove_binary : bool, optional
        If True, skip binary file patches (not implemented)
    fuzzy : bool, optional
        If True, use fuzzy matching for finding hunks
    add_newline : bool, optional
        If True, add final newlines when processing "No newline at end of file" markers
    strict : bool, optional
        If True, fail fast on serious issues instead of trying to fix
    pre_hunk_hook : callable, optional
        Function called before processing each hunk
    post_hunk_hook : callable, optional
        Function called after processing each hunk

    Returns
    -------
    fixed_lines
        List of fixed patch lines with newlines normalized to LF
    """
    dir_mode = os.path.isdir(original)
    original_path = Path(original).absolute()

    # make relative paths in the diff work
    if dir_mode:
        os.chdir(original_path)
    else:
        os.chdir(original_path.parent)

    state = PatchState()

    for i, line in enumerate(patch_lines):
        match_groups, line_type = match_line(line)

        match line_type:
            case "DIFF_LINE":
                handle_diff_line(state, line, match_groups, i)

            case "MODE_LINE":
                handle_mode_line(state, line, i)

            case "INDEX_LINE":
                handle_index_line(state, line, match_groups, i)

            case "SIMILARITY_LINE":
                handle_similarity_line(state, line, match_groups, i)

            case "BINARY_LINE":
                handle_binary_line(state, line, remove_binary)

            case "RENAME_FROM":
                handle_rename_from(state, line, match_groups, i, dir_mode, original_path, original)

            case "RENAME_TO":
                handle_rename_to(state, line, match_groups, i)

            case "FILE_HEADER_START":
                handle_file_header_start(state, line, match_groups, i, patch_lines, dir_mode, original_path, original)

            case "FILE_HEADER_END":
                handle_file_header_end(state, line, match_groups, i, patch_lines, original_path, dir_mode, original)

            case "HUNK_HEADER":
                handle_hunk_header(state, line, match_groups, i, patch_lines, fuzzy, pre_hunk_hook, post_hunk_hook,
                                   strict)

            case "END_LINE":
                handle_end_line(state, line, add_newline)

            case _:
                # regular hunk content line
                state.current_hunk.append(normalize_line(line))

    # handle the last hunk if any
    if not state.first_hunk:
        try:
            if pre_hunk_hook:
                hook_context = {
                    'current_file': state.current_file,
                    'original_lines': state.original_lines,
                    'offset': state.offset,
                    'last_hunk': state.last_hunk
                }
                state.current_hunk = pre_hunk_hook(state.current_hunk, hook_context)

            fixed_header, state.offset, state.last_hunk = capture_hunk(
                state.current_hunk, state.original_lines,
                state.offset, state.last_hunk,
                state.current_hunk_header, fuzzy=fuzzy
            )

            if post_hunk_hook:
                hook_context = {
                    'current_file': state.current_file,
                    'fixed_header': fixed_header,
                    'offset': state.offset,
                    'last_hunk': state.last_hunk
                }
                state.current_hunk = post_hunk_hook(state.current_hunk, hook_context)

            state.fixed_lines.append(fixed_header)
            state.fixed_lines.extend(state.current_hunk)
        except (MissingHunkError, OutOfOrderHunk, EmptyHunk) as e:
            if hasattr(e, 'add_file'):
                e.add_file(state.current_file)
            if not isinstance(e, EmptyHunk):
                raise e

    # if original file didn't end with a newline, strip out the newline here,
    # unless user explicitly requested to add final newline
    if (
            not add_newline and
            ((state.original_lines and not state.original_lines[-1].endswith("\n")) or
             (state.fixed_lines and len(state.original_lines) == 0))
    ):
        state.fixed_lines[-1] = state.fixed_lines[-1].rstrip("\n")

    return state.fixed_lines