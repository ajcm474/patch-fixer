"""Tests for the transformers module."""

import pytest
from patch_fixer.transformers import (
    fix_hunk_header,
    fix_file_paths,
    normalize_line_endings,
    add_final_newlines,
    fix_malformed_headers,
    split_patch_by_file
)


class TestTransformers:

    def test_fix_hunk_header_basic(self):
        """Test fixing a basic hunk header."""
        hunk_lines = [
            "@@ -1,2 +1,3 @@\n",
            " line 1\n",
            " line 2\n",
            "+line 3\n"
        ]
        original_lines = ["line 1", "line 2"]

        fixed_header, new_offset, new_last_pos = fix_hunk_header(
            hunk_lines, original_lines
        )

        assert fixed_header == "@@ -1,2 +1,3 @@\n"
        assert new_offset == 1  # One line added
        assert new_last_pos == 2  # Last position at line 2

    def test_fix_hunk_header_with_offset(self):
        """Test fixing hunk header with existing offset."""
        hunk_lines = [
            "@@ -5,2 +7,2 @@\n",
            " line 5\n",
            " line 6\n"
        ]
        original_lines = [""] * 4 + ["line 5", "line 6"]

        fixed_header, new_offset, new_last_pos = fix_hunk_header(
            hunk_lines, original_lines, offset=2, last_hunk_pos=0
        )

        assert "@@ -5,2 +7,2 @@" in fixed_header

    def test_fix_file_paths_missing_prefixes(self):
        """Test adding missing a/ and b/ prefixes."""
        headers = [
            "diff --git file.txt file.txt\n",
            "--- file.txt\n",
            "+++ file.txt\n"
        ]

        fixed = fix_file_paths(headers)
        assert fixed[0] == "diff --git a/file.txt b/file.txt\n"
        assert fixed[1] == "--- a/file.txt\n"
        assert fixed[2] == "+++ b/file.txt\n"

    def test_fix_file_paths_dev_null(self):
        """Test that /dev/null is not modified."""
        headers = [
            "diff --git a/file.txt b/file.txt\n",
            "--- /dev/null\n",
            "+++ b/file.txt\n"
        ]

        fixed = fix_file_paths(headers)
        assert fixed[1] == "--- /dev/null\n"  # Should not add prefix

    def test_normalize_line_endings(self):
        """Test normalizing mixed line endings."""
        lines = [
            "line 1\r\n",   # windows
            "line 2\n",     # unix
            "line 3\r",     # mac os9
            "line 4"        # no ending
        ]

        normalized = normalize_line_endings(lines)
        assert all(line.endswith('\n') or line == "line 4" for line in normalized)
        assert normalized[0] == "line 1\n"
        assert normalized[1] == "line 2\n"
        assert normalized[2] == "line 3\n"
        assert normalized[3] == "line 4\n"

    def test_add_final_newlines(self):
        """Test handling 'No newline at end of file' markers."""
        patch = [
            "+last line\n",
            "\\ No newline at end of file\n",
            "--- a/file.txt\n"
        ]

        fixed = add_final_newlines(patch)
        assert fixed[0] == "+last line"  # Newline removed
        assert len(fixed) == 2  # Marker line removed

    def test_fix_malformed_headers_missing_git(self):
        """Test fixing diff headers missing --git."""
        patch = [
            "diff a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n"
        ]

        fixed = fix_malformed_headers(patch)
        assert "diff --git" in fixed[0]

    def test_split_patch_by_file(self):
        """Test splitting patch into individual files."""
        patch = [
            "diff --git a/file1.txt b/file1.txt\n",
            "--- a/file1.txt\n",
            "+++ b/file1.txt\n",
            "@@ -1 +1 @@\n",
            "-old\n",
            "+new\n",
            "diff --git a/file2.txt b/file2.txt\n",
            "--- a/file2.txt\n",
            "+++ b/file2.txt\n",
            "@@ -1 +1 @@\n",
            " content\n"
        ]

        files = split_patch_by_file(patch)
        assert len(files) == 2
        assert files[0][0] == "file1.txt"
        assert files[1][0] == "file2.txt"
        assert len(files[0][1]) == 6  # first file's lines
        assert len(files[1][1]) == 5  # second file's lines

    def test_split_patch_by_file_with_rename(self):
        """Test splitting patch with renamed files."""
        patch = [
            "diff --git a/old.txt b/new.txt\n",
            "rename from old.txt\n",
            "rename to new.txt\n"
        ]

        files = split_patch_by_file(patch)
        assert len(files) == 1
        # should extract from the diff line
        assert files[0][0] in ["old.txt", "new.txt"]