"""Read-only patch analysis utilities."""

from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import re

from .regex import match_line
from .validators import count_hunk_lines, is_binary_diff


@dataclass
class HunkInfo:
    """Information about a single hunk."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    context: str
    added_lines: int
    removed_lines: int
    context_lines: int
    line_number: int  # line number in the patch file


@dataclass
class FileInfo:
    """Information about a single file in a patch."""
    source_path: str
    dest_path: str
    is_new: bool
    is_deleted: bool
    is_renamed: bool
    is_binary: bool
    mode: Optional[str]
    hunks: List[HunkInfo]
    line_number: int  # line number in the patch file where this diff starts


@dataclass
class PatchInfo:
    """Complete information about a patch."""
    files: List[FileInfo]
    total_additions: int
    total_deletions: int
    total_files: int
    binary_files: int
    renamed_files: int
    new_files: int
    deleted_files: int
    errors: List[str]  # any errors or warnings found during analysis


def analyze_patch(patch_lines: List[str], strict: bool = False) -> PatchInfo:
    """
    Parse patch for analysis/validation without modification.

    Args:
        patch_lines: Lines of the patch file
        strict: If True, be more strict about validation

    Returns:
        PatchInfo object with analysis results
    """
    files = []
    errors = []

    current_file = None
    current_hunks = []
    i = 0

    while i < len(patch_lines):
        line = patch_lines[i]
        match_groups, line_type = match_line(line)

        if line_type == "DIFF_LINE":
            # save previous file if any
            if current_file:
                current_file.hunks = current_hunks
                files.append(current_file)

            # start new file
            source = match_groups[0]
            dest = match_groups[1]

            # strip a/ and b/ prefixes
            if source.startswith("a/"):
                source = source[2:]
            if dest.startswith("b/"):
                dest = dest[2:]

            current_file = FileInfo(
                source_path=source,
                dest_path=dest,
                is_new=False,
                is_deleted=False,
                is_renamed=source != dest,
                is_binary=False,
                mode=None,
                hunks=[],
                line_number=i + 1
            )
            current_hunks = []

        elif line_type == "MODE_LINE" and current_file:
            # extract mode from the line
            mode_match = re.search(r'mode ([0-7]{6})', line)
            mode = mode_match.group(1) if mode_match else "100644"
            current_file.mode = mode

            if "new file mode" in line:
                current_file.is_new = True
            elif "deleted file mode" in line:
                current_file.is_deleted = True

        elif line_type == "BINARY_LINE" and current_file:
            current_file.is_binary = True

        elif line_type == "FILE_HEADER_START" and current_file:
            if match_groups[0] == "/dev/null":
                current_file.is_new = True

        elif line_type == "FILE_HEADER_END" and current_file:
            if match_groups[0] == "/dev/null":
                current_file.is_deleted = True

        elif line_type == "HUNK_HEADER" and current_file:
            # parse hunk header
            try:
                old_start = int(match_groups[0]) if match_groups[0] else 0
                old_count = int(match_groups[1]) if match_groups[1] else 1
                new_start = int(match_groups[2]) if match_groups[2] else 0
                new_count = int(match_groups[3]) if match_groups[3] else 1
                context = match_groups[4] if len(match_groups) > 4 else ""

                # collect hunk lines until next header or diff
                hunk_lines = []
                j = i + 1
                while j < len(patch_lines):
                    next_line = patch_lines[j]
                    _, next_type = match_line(next_line)
                    if next_type in ("HUNK_HEADER", "DIFF_LINE"):
                        break
                    hunk_lines.append(next_line)
                    j += 1

                added, removed, context_count = count_hunk_lines(hunk_lines)

                hunk = HunkInfo(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    context=context,
                    added_lines=added,
                    removed_lines=removed,
                    context_lines=context_count,
                    line_number=i + 1
                )

                # validate counts if strict
                if strict:
                    if old_count != removed + context_count:
                        errors.append(
                            f"Line {i + 1}: Hunk old count mismatch: "
                            f"expected {old_count}, got {removed + context_count}"
                        )
                    if new_count != added + context_count:
                        errors.append(
                            f"Line {i + 1}: Hunk new count mismatch: "
                            f"expected {new_count}, got {added + context_count}"
                        )

                current_hunks.append(hunk)
                i = j - 1  # will be incremented at end of loop
            except (ValueError, IndexError) as e:
                errors.append(f"Line {i + 1}: Failed to parse hunk header: {e}")

        i += 1

    # don't forget the last file
    if current_file:
        current_file.hunks = current_hunks
        files.append(current_file)

    # calculate statistics
    total_additions = sum(
        sum(h.added_lines for h in f.hunks)
        for f in files if not f.is_binary
    )
    total_deletions = sum(
        sum(h.removed_lines for h in f.hunks)
        for f in files if not f.is_binary
    )

    return PatchInfo(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
        total_files=len(files),
        binary_files=sum(1 for f in files if f.is_binary),
        renamed_files=sum(1 for f in files if f.is_renamed),
        new_files=sum(1 for f in files if f.is_new),
        deleted_files=sum(1 for f in files if f.is_deleted),
        errors=errors
    )


def find_potential_issues(patch_lines: List[str]) -> List[str]:
    """
    Scan patch for potential issues that might need fixing.

    Returns:
        List of warning messages
    """
    warnings = []

    # check for missing headers
    has_diff_header = False
    has_file_headers = False
    has_hunks = False

    for line in patch_lines:
        if line.startswith("diff "):
            has_diff_header = True
        elif line.startswith("---") or line.startswith("+++"):
            has_file_headers = True
        elif line.startswith("@@"):
            has_hunks = True

    if has_hunks and not has_diff_header:
        warnings.append("Patch has hunks but no diff header")

    if has_hunks and not has_file_headers:
        warnings.append("Patch has hunks but no file headers (--- and +++ lines)")

    # check for inconsistent line endings
    line_endings = set()
    for line in patch_lines:
        if line.endswith('\r\n'):
            line_endings.add('CRLF')
        elif line.endswith('\n'):
            line_endings.add('LF')
        elif line.endswith('\r'):
            line_endings.add('CR')

    if len(line_endings) > 1:
        warnings.append(f"Inconsistent line endings found: {', '.join(line_endings)}")

    # check for malformed hunk headers
    for i, line in enumerate(patch_lines):
        if line.startswith("@@"):
            if not re.match(r'@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@', line):
                warnings.append(f"Line {i + 1}: Potentially malformed hunk header")

    # check for truncated patches
    if patch_lines and patch_lines[-1].startswith(('+', '-')) and not patch_lines[-1].endswith('\n'):
        warnings.append("Patch appears to be truncated (last line is a change without newline)")

    return warnings


def get_patch_summary(patch_lines: List[str]) -> str:
    """
    Generate a human-readable summary of the patch.

    Returns:
        Multi-line string summary
    """
    info = analyze_patch(patch_lines)

    lines = []
    lines.append(f"Patch Summary:")
    lines.append(f"  Files modified: {info.total_files}")

    if info.new_files:
        lines.append(f"  New files: {info.new_files}")
    if info.deleted_files:
        lines.append(f"  Deleted files: {info.deleted_files}")
    if info.renamed_files:
        lines.append(f"  Renamed files: {info.renamed_files}")
    if info.binary_files:
        lines.append(f"  Binary files: {info.binary_files}")

    lines.append(f"  Lines added: {info.total_additions}")
    lines.append(f"  Lines removed: {info.total_deletions}")

    if info.errors:
        lines.append(f"\nIssues found:")
        for error in info.errors[:5]:  # show first 5 errors
            lines.append(f"  - {error}")
        if len(info.errors) > 5:
            lines.append(f"  ... and {len(info.errors) - 5} more")

    return "\n".join(lines)