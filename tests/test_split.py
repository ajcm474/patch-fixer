"""Tests for the split_patch functionality."""

import pytest

from patch_fixer.split import split_patch


class TestSplitPatch:
    """Test cases for split_patch function."""

    def test_simple_split(self):
        """Test basic splitting with two files."""
        patch = [
            "diff --git a/file1.txt b/file1.txt\n",
            "index 1234567..abcdefg 100644\n",
            "--- a/file1.txt\n",
            "+++ b/file1.txt\n",
            "@@ -1,3 +1,3 @@\n",
            " line1\n",
            "-old line\n",
            "+new line\n",
            " line3\n",
            "diff --git a/file2.txt b/file2.txt\n",
            "index 2234567..bbcdefg 100644\n",
            "--- a/file2.txt\n",
            "+++ b/file2.txt\n",
            "@@ -1,2 +1,2 @@\n",
            "-removed\n",
            "+added\n",
        ]

        included, excluded = split_patch(patch, ["./file1.txt"])

        # check that file1 is in included
        assert "diff --git a/file1.txt b/file1.txt\n" in included
        assert "+new line\n" in included

        # check that file2 is in excluded
        assert "diff --git a/file2.txt b/file2.txt\n" in excluded
        assert "+added\n" in excluded

        # check that files are not mixed
        assert "file2.txt" not in "".join(included)
        assert "file1.txt" not in "".join(excluded)

    def test_split_with_multiple_includes(self):
        """Test splitting with multiple files to include."""
        patch = [
            "diff --git a/file1.txt b/file1.txt\n",
            "--- a/file1.txt\n",
            "+++ b/file1.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old1\n",
            "+new1\n",
            "diff --git a/file2.txt b/file2.txt\n",
            "--- a/file2.txt\n",
            "+++ b/file2.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old2\n",
            "+new2\n",
            "diff --git a/file3.txt b/file3.txt\n",
            "--- a/file3.txt\n",
            "+++ b/file3.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old3\n",
            "+new3\n",
        ]

        included, excluded = split_patch(patch, ["./file1.txt", "./file3.txt"])

        # verify file1 and file3 are included
        assert "file1.txt" in "".join(included)
        assert "file3.txt" in "".join(included)
        assert "+new1\n" in included
        assert "+new3\n" in included

        # verify file2 is excluded
        assert "file2.txt" in "".join(excluded)
        assert "+new2\n" in excluded
        assert "file1.txt" not in "".join(excluded)
        assert "file3.txt" not in "".join(excluded)

    def test_split_with_no_includes(self):
        """Test when no files match the include list."""
        patch = [
            "diff --git a/file1.txt b/file1.txt\n",
            "--- a/file1.txt\n",
            "+++ b/file1.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        included, excluded = split_patch(patch, ["./nonexistent.txt"])

        # all content should be in excluded
        assert len(included) == 0
        assert "file1.txt" in "".join(excluded)
        assert "+new\n" in excluded

    def test_split_with_all_includes(self):
        """Test when all files match the include list."""
        patch = [
            "diff --git a/file1.txt b/file1.txt\n",
            "--- a/file1.txt\n",
            "+++ b/file1.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        included, excluded = split_patch(patch, ["./file1.txt"])

        # all content should be in included
        assert "file1.txt" in "".join(included)
        assert "+new\n" in included
        assert len(excluded) == 0

    def test_split_preserves_headers(self):
        """Test that all necessary headers are preserved."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "index 1234567..abcdefg 100644\n",
            "new file mode 100644\n",
            "--- /dev/null\n",
            "+++ b/file.txt\n",
            "@@ -0,0 +1,2 @@\n",
            "+new file\n",
            "+content\n",
        ]

        included, excluded = split_patch(patch, ["./file.txt"])

        # check all headers are preserved
        assert "diff --git a/file.txt b/file.txt\n" in included
        assert "index 1234567..abcdefg 100644\n" in included
        assert "new file mode 100644\n" in included
        assert "--- /dev/null\n" in included
        assert "+++ b/file.txt\n" in included
        assert "@@ -0,0 +1,2 @@\n" in included

    def test_split_with_rename(self):
        """Test splitting patches with file renames."""
        patch = [
            "diff --git a/old.txt b/new.txt\n",
            "similarity index 95%\n",
            "rename from old.txt\n",
            "rename to new.txt\n",
            "index 1234567..abcdefg 100644\n",
            "--- a/old.txt\n",
            "+++ b/new.txt\n",
            "@@ -1,3 +1,3 @@\n",
            " same line\n",
            "-old content\n",
            "+new content\n",
        ]

        # include based on old name (source file)
        included, excluded = split_patch(patch, ["./old.txt"])

        assert "rename from old.txt\n" in included
        assert "rename to new.txt\n" in included
        assert len(excluded) == 0

    def test_split_with_binary_files(self):
        """Test splitting patches containing binary files."""
        patch = [
            "diff --git a/image.png b/image.png\n",
            "index 1234567..abcdefg 100644\n",
            "Binary files a/image.png and b/image.png differ\n",
            "diff --git a/text.txt b/text.txt\n",
            "--- a/text.txt\n",
            "+++ b/text.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        included, excluded = split_patch(patch, ["./image.png"])

        assert "Binary files a/image.png and b/image.png differ\n" in included
        assert "text.txt" in "".join(excluded)
        assert "image.png" not in "".join(excluded)

    def test_normalization_of_paths(self):
        """Test that file paths are normalized correctly."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        # test without ./ prefix
        included1, excluded1 = split_patch(patch, ["file.txt"])
        assert "file.txt" in "".join(included1)
        assert len(excluded1) == 0

        # test with ./ prefix
        included2, excluded2 = split_patch(patch, ["./file.txt"])
        assert "file.txt" in "".join(included2)
        assert len(excluded2) == 0

        # both should produce same result
        assert included1 == included2
        assert excluded1 == excluded2

    def test_empty_patch(self):
        """Test behavior with empty patch."""
        with pytest.raises(ValueError, match="Empty patch provided"):
            split_patch([], ["./file.txt"])

    def test_invalid_diff_format(self):
        """Test behavior with invalid diff format."""
        invalid_patch = [
            "not a valid diff line\n",
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        # should handle gracefully - non-diff lines before first diff
        included, excluded = split_patch(invalid_patch, ["./file.txt"])

        # the invalid line should be in both outputs (global header behavior)
        assert "not a valid diff line\n" in included
        assert "not a valid diff line\n" in excluded

    def test_no_files_in_include_list(self):
        """Test when include list is empty."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
        ]

        included, excluded = split_patch(patch, [])

        # everything should go to excluded
        assert len(included) == 0
        assert "file.txt" in "".join(excluded)

    def test_patch_with_no_diff_lines(self):
        """Test patch that has no actual diff lines."""
        patch = [
            "This is a comment\n",
            "Another comment\n",
        ]

        included, excluded = split_patch(patch, ["./file.txt"])

        # non-diff lines should appear in original form
        assert patch == included
        assert len(excluded) == 0

    def test_multiple_hunks_same_file(self):
        """Test that multiple hunks for the same file stay together."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old1\n",
            "+new1\n",
            "@@ -10,1 +10,1 @@\n",
            "-old2\n",
            "+new2\n",
            "@@ -20,1 +20,1 @@\n",
            "-old3\n",
            "+new3\n",
        ]

        included, excluded = split_patch(patch, ["./file.txt"])

        # all hunks should be in included
        assert "+new1\n" in included
        assert "+new2\n" in included
        assert "+new3\n" in included
        assert len(excluded) == 0

    def test_file_deletion(self):
        """Test splitting patches with file deletions."""
        patch = [
            "diff --git a/deleted.txt b/deleted.txt\n",
            "deleted file mode 100644\n",
            "index 1234567..0000000\n",
            "--- a/deleted.txt\n",
            "+++ /dev/null\n",
            "@@ -1,3 +0,0 @@\n",
            "-line1\n",
            "-line2\n",
            "-line3\n",
        ]

        included, excluded = split_patch(patch, ["./deleted.txt"])

        assert "deleted file mode 100644\n" in included
        assert "+++ /dev/null\n" in included
        assert "-line1\n" in included
        assert len(excluded) == 0

    def test_file_creation(self):
        """Test splitting patches with new file creation."""
        patch = [
            "diff --git a/new.txt b/new.txt\n",
            "new file mode 100644\n",
            "index 0000000..1234567\n",
            "--- /dev/null\n",
            "+++ b/new.txt\n",
            "@@ -0,0 +1,3 @@\n",
            "+line1\n",
            "+line2\n",
            "+line3\n",
        ]

        included, excluded = split_patch(patch, ["./new.txt"])

        assert "new file mode 100644\n" in included
        assert "--- /dev/null\n" in included
        assert "+line1\n" in included
        assert len(excluded) == 0

    def test_complex_patch(self):
        """Test a complex patch with various file operations."""
        patch = [
            "diff --git a/modified.txt b/modified.txt\n",
            "index 1234567..abcdefg 100644\n",
            "--- a/modified.txt\n",
            "+++ b/modified.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-old\n",
            "+new\n",
            "diff --git a/created.txt b/created.txt\n",
            "new file mode 100644\n",
            "index 0000000..2234567\n",
            "--- /dev/null\n",
            "+++ b/created.txt\n",
            "@@ -0,0 +1,1 @@\n",
            "+created content\n",
            "diff --git a/deleted.txt b/deleted.txt\n",
            "deleted file mode 100644\n",
            "index 3234567..0000000\n",
            "--- a/deleted.txt\n",
            "+++ /dev/null\n",
            "@@ -1,1 +0,0 @@\n",
            "-deleted content\n",
            "diff --git a/renamed_old.txt b/renamed_new.txt\n",
            "similarity index 90%\n",
            "rename from renamed_old.txt\n",
            "rename to renamed_new.txt\n",
            "index 4234567..5234567\n",
            "--- a/renamed_old.txt\n",
            "+++ b/renamed_new.txt\n",
            "@@ -1,1 +1,1 @@\n",
            "-before rename\n",
            "+after rename\n",
        ]

        # include modified and renamed files
        included, excluded = split_patch(patch, ["./modified.txt", "./renamed_old.txt"])

        # check included has modified and renamed
        assert "modified.txt" in "".join(included)
        assert "renamed_old.txt" in "".join(included)
        assert "+new\n" in included
        assert "+after rename\n" in included

        # check excluded has created and deleted
        assert "created.txt" in "".join(excluded)
        assert "deleted.txt" in "".join(excluded)
        assert "+created content\n" in excluded
        assert "-deleted content\n" in excluded

        # check no cross-contamination
        assert "created.txt" not in "".join(included)
        assert "deleted.txt" not in "".join(included)
        assert "modified.txt" not in "".join(excluded)
        assert "renamed" not in "".join(excluded)