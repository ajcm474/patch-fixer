"""Tests for the CLI module."""

import os
import tempfile
from unittest.mock import patch

import pytest

from patch_fixer.cli import main


class TestCLI:
    """Test cases for CLI functionality."""

    def test_no_command(self, capsys):
        """Test that help is shown when no command is provided."""
        with patch('sys.argv', ['patch-fixer']):
            result = main()
            assert result == 1
            captured = capsys.readouterr()
            assert 'usage: patch-fixer' in captured.out
            assert 'Available commands' in captured.out

        def test_fix_command(self):
            """Test the fix command in directory mode."""
            with tempfile.TemporaryDirectory() as tmpdir:
                # create test files
                original_file = os.path.join(tmpdir, 'original.txt')
                with open(original_file, 'w') as f:
                    f.write("line1\nline2\nline3\n")

                broken_patch = os.path.join(tmpdir, 'broken.patch')
                with open(broken_patch, 'w') as f:
                    f.write("""diff --git a/original.txt b/original.txt
    --- a/original.txt
    +++ b/original.txt
    @@ -1,3 +1,3 @@
     line1
    -line2
    +modified line2
     line3
    """)

                output_patch = os.path.join(tmpdir, 'fixed.patch')

                # use directory mode to work around bug in file mode
                with patch('sys.argv', ['patch-fixer', 'fix', tmpdir, broken_patch, output_patch]):
                    result = main()

                assert result == 0
                assert os.path.exists(output_patch)

                with open(output_patch) as f:
                    content = f.read()
                    assert 'diff --git' in content
                    assert 'modified line2' in content

    def test_split_command_with_files(self):
        """Test the split command with files specified on command line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_patch = os.path.join(tmpdir, 'input.patch')
            with open(input_patch, 'w') as f:
                f.write("""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1,1 +1,1 @@
-old1
+new1
diff --git a/file2.txt b/file2.txt
--- a/file2.txt
+++ b/file2.txt
@@ -1,1 +1,1 @@
-old2
+new2
""")

            included = os.path.join(tmpdir, 'included.patch')
            excluded = os.path.join(tmpdir, 'excluded.patch')

            with patch('sys.argv', ['patch-fixer', 'split', input_patch, included, excluded,
                                    '-f', 'file1.txt']):
                result = main()

            assert result == 0
            assert os.path.exists(included)
            assert os.path.exists(excluded)

            with open(included) as f:
                content = f.read()
                assert 'file1.txt' in content
                assert 'new1' in content
                assert 'file2.txt' not in content

            with open(excluded) as f:
                content = f.read()
                assert 'file2.txt' in content
                assert 'new2' in content
                assert 'file1.txt' not in content

    def test_split_command_with_include_file(self):
        """Test the split command with include file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # create include file
            include_list = os.path.join(tmpdir, 'include.txt')
            with open(include_list, 'w') as f:
                f.write("file1.txt\n")

            input_patch = os.path.join(tmpdir, 'input.patch')
            with open(input_patch, 'w') as f:
                f.write("""diff --git a/file1.txt b/file1.txt
--- a/file1.txt
+++ b/file1.txt
@@ -1,1 +1,1 @@
-old1
+new1
diff --git a/file2.txt b/file2.txt
--- a/file2.txt
+++ b/file2.txt
@@ -1,1 +1,1 @@
-old2
+new2
""")

            included = os.path.join(tmpdir, 'included.patch')
            excluded = os.path.join(tmpdir, 'excluded.patch')

            with patch('sys.argv', ['patch-fixer', 'split', input_patch, included, excluded,
                                    '-i', include_list]):
                result = main()

            assert result == 0
            assert os.path.exists(included)
            assert os.path.exists(excluded)

            with open(included) as f:
                content = f.read()
                assert 'file1.txt' in content

            with open(excluded) as f:
                content = f.read()
                assert 'file2.txt' in content

    def test_error_handling(self, capsys):
        """Test error handling in CLI."""
        with patch('sys.argv', ['patch-fixer', 'fix', 'nonexistent', 'nonexistent', 'out']):
            result = main()
            assert result == 1
            captured = capsys.readouterr()
            assert 'Error:' in captured.err