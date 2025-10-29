"""Tests for the analyzer module."""

import pytest
from patch_fixer.analyzer import (
    analyze_patch,
    find_potential_issues,
    get_patch_summary,
    PatchInfo,
    FileInfo,
    HunkInfo
)


class TestAnalyzer:

    def test_analyze_simple_patch(self):
        """Test analyzing a simple patch."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,3 +1,4 @@\n",
            " line 1\n",
            " line 2\n",
            "+added line\n",
            " line 3\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 1
        assert info.total_additions == 1
        assert info.total_deletions == 0
        assert len(info.files) == 1
        assert info.files[0].source_path == "file.txt"
        assert info.files[0].dest_path == "file.txt"
        assert not info.files[0].is_new
        assert not info.files[0].is_deleted
        assert len(info.files[0].hunks) == 1

    def test_analyze_new_file(self):
        """Test analyzing a new file patch."""
        patch = [
            "diff --git a/new.txt b/new.txt\n",
            "new file mode 100644\n",
            "--- /dev/null\n",
            "+++ b/new.txt\n",
            "@@ -0,0 +1,2 @@\n",
            "+line 1\n",
            "+line 2\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 1
        assert info.new_files == 1
        assert info.files[0].is_new
        assert info.files[0].mode == "100644"

    def test_analyze_deleted_file(self):
        """Test analyzing a deleted file patch."""
        patch = [
            "diff --git a/old.txt b/old.txt\n",
            "deleted file mode 100644\n",
            "--- a/old.txt\n",
            "+++ /dev/null\n",
            "@@ -1,2 +0,0 @@\n",
            "-line 1\n",
            "-line 2\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 1
        assert info.deleted_files == 1
        assert info.files[0].is_deleted

    def test_analyze_renamed_file(self):
        """Test analyzing a renamed file patch."""
        patch = [
            "diff --git a/old.txt b/new.txt\n",
            "similarity index 100%\n",
            "rename from old.txt\n",
            "rename to new.txt\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 1
        assert info.renamed_files == 1
        assert info.files[0].is_renamed
        assert info.files[0].source_path == "old.txt"
        assert info.files[0].dest_path == "new.txt"

    def test_analyze_binary_file(self):
        """Test analyzing a binary file patch."""
        patch = [
            "diff --git a/image.png b/image.png\n",
            "Binary files a/image.png and b/image.png differ\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 1
        assert info.binary_files == 1
        assert info.files[0].is_binary

    def test_analyze_multi_file_patch(self):
        """Test analyzing a patch with multiple files."""
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
            "@@ -1 +1,2 @@\n",
            " line\n",
            "+added\n"
        ]

        info = analyze_patch(patch)
        assert info.total_files == 2
        assert info.total_additions == 2
        assert info.total_deletions == 1
        assert len(info.files) == 2

    def test_find_potential_issues_missing_headers(self):
        """Test finding issues with missing headers."""
        patch = [
            "@@ -1 +1 @@\n",
            "-old\n",
            "+new\n"
        ]

        warnings = find_potential_issues(patch)
        assert any("no diff header" in w for w in warnings)
        assert any("no file headers" in w for w in warnings)

    def test_find_potential_issues_inconsistent_line_endings(self):
        """Test finding inconsistent line endings."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\r\n",  # CRLF
            "+++ b/file.txt\n",  # LF
        ]

        warnings = find_potential_issues(patch)
        assert any("Inconsistent line endings" in w for w in warnings)

    def test_find_potential_issues_malformed_hunk(self):
        """Test finding malformed hunk headers."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "@@ malformed header @@\n",
            " content\n"
        ]

        warnings = find_potential_issues(patch)
        assert any("malformed hunk header" in w for w in warnings)

    def test_get_patch_summary(self):
        """Test generating patch summary."""
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,2 +1,3 @@\n",
            " line 1\n",
            "-line 2\n",
            "+line 2 modified\n",
            "+line 3 added\n"
        ]

        summary = get_patch_summary(patch)
        assert "Files modified: 1" in summary
        assert "Lines added: 2" in summary
        assert "Lines removed: 1" in summary

    def test_analyze_strict_mode(self):
        """Test strict mode validation."""
        # Patch with incorrect line counts
        patch = [
            "diff --git a/file.txt b/file.txt\n",
            "--- a/file.txt\n",
            "+++ b/file.txt\n",
            "@@ -1,3 +1,3 @@\n",  # claims 3 lines but only has 2
            " line 1\n",
            "+added\n"
        ]

        info = analyze_patch(patch, strict=True)
        assert len(info.errors) > 0
        assert any("count mismatch" in e for e in info.errors)