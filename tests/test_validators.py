"""Tests for the validators module."""

import pytest
from patch_fixer.validators import (
    validate_hunk_header,
    validate_diff_header,
    validate_file_header,
    validate_index_line,
    validate_mode_line,
    is_binary_diff,
    count_hunk_lines
)
from patch_fixer.errors import InvalidPatchError


class TestValidators:

    def test_validate_hunk_header_simple(self):
        """Test parsing a simple hunk header."""
        header = "@@ -1,3 +1,4 @@\n"
        old_start, old_count, new_start, new_count, context = validate_hunk_header(header)
        assert old_start == 1
        assert old_count == 3
        assert new_start == 1
        assert new_count == 4
        assert context == ""

    def test_validate_hunk_header_with_context(self):
        """Test parsing a hunk header with context."""
        header = "@@ -10,5 +12,7 @@ def main():\n"
        old_start, old_count, new_start, new_count, context = validate_hunk_header(header)
        assert old_start == 10
        assert old_count == 5
        assert new_start == 12
        assert new_count == 7
        assert context == " def main():"

    def test_validate_hunk_header_single_line(self):
        """Test parsing a hunk header for single line changes."""
        header = "@@ -5 +5 @@\n"
        old_start, old_count, new_start, new_count, context = validate_hunk_header(header)
        assert old_start == 5
        assert old_count == 1  # default when count not specified
        assert new_start == 5
        assert new_count == 1

    def test_validate_hunk_header_invalid(self):
        """Test that invalid hunk headers raise errors."""
        with pytest.raises(InvalidPatchError):
            validate_hunk_header("not a hunk header\n")

    def test_validate_diff_header(self):
        """Test parsing diff headers."""
        header = "diff --git a/file.txt b/file.txt\n"
        source, dest = validate_diff_header(header)
        assert source == "file.txt"
        assert dest == "file.txt"

    def test_validate_diff_header_with_rename(self):
        """Test parsing diff headers with renamed files."""
        header = "diff --git a/old.txt b/new.txt\n"
        source, dest = validate_diff_header(header)
        assert source == "old.txt"
        assert dest == "new.txt"

    def test_validate_file_header_start(self):
        """Test parsing file start headers."""
        header = "--- a/file.txt\n"
        path = validate_file_header(header, "start")
        assert path == "file.txt"

    def test_validate_file_header_end(self):
        """Test parsing file end headers."""
        header = "+++ b/file.txt\n"
        path = validate_file_header(header, "end")
        assert path == "file.txt"

    def test_validate_file_header_dev_null(self):
        """Test parsing /dev/null in file headers."""
        header = "--- /dev/null\n"
        path = validate_file_header(header, "start")
        assert path == "/dev/null"

    def test_validate_index_line_regular(self):
        """Test parsing regular index lines."""
        line = "index 1234567..abcdef0 100644\n"
        result = validate_index_line(line)
        assert result['old_hash'] == "1234567"
        assert result['new_hash'] == "abcdef0"
        assert result['mode'] == "100644"

    def test_validate_similarity_line(self):
        """Test parsing similarity index lines."""
        from patch_fixer.validators import validate_similarity_line
        line = "similarity index 95%\n"
        similarity = validate_similarity_line(line)
        assert similarity == 95

    def test_validate_mode_line_new(self):
        """Test parsing new file mode lines."""
        line = "new file mode 100755\n"
        operation, mode = validate_mode_line(line)
        assert operation == "new"
        assert mode == "100755"

    def test_validate_mode_line_deleted(self):
        """Test parsing deleted file mode lines."""
        line = "deleted file mode 100644\n"
        operation, mode = validate_mode_line(line)
        assert operation == "deleted"
        assert mode == "100644"

    def test_is_binary_diff(self):
        """Test binary diff detection."""
        binary_patch = [
            "diff --git a/image.png b/image.png\n",
            "Binary files a/image.png and b/image.png differ\n"
        ]
        assert is_binary_diff(binary_patch) is True

        text_patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n"
        ]
        assert is_binary_diff(text_patch) is False

    def test_count_hunk_lines(self):
        """Test counting lines in a hunk."""
        hunk = [
            " context line\n",
            "-removed line\n",
            "+added line\n",
            "+another added\n",
            " more context\n"
        ]
        added, removed, context = count_hunk_lines(hunk)
        assert added == 2
        assert removed == 1
        assert context == 2