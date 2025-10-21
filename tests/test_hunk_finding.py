#!/usr/bin/env python3

import pytest
from patch_fixer.hunk import find_hunk_start, capture_hunk
from patch_fixer.errors import MissingHunkError


class TestImprovedHunkFinding:
    """Test improved hunk finding functionality."""

    def test_format_hunk_for_error(self):
        """Test that format_hunk_for_error only shows context and deletion lines."""
        hunk_lines = [
            " \tcontext line 1\n",
            "-\tdeleted line\n",
            "+\tadded line 1\n",
            "+\tadded line 2\n",
            " \tcontext line 2\n"
        ]

        error = MissingHunkError(hunk_lines)
        result = error.format_hunk_for_error()
        expected = " \tcontext line 1\n-\tdeleted line\n \tcontext line 2\n"
        assert result == expected

    def test_exact_match_prioritized(self):
        """Test that exact matches are found before whitespace-tolerant ones."""
        original_lines = [
            "exact match\n",
            "function    test()   {\n",  # whitespace different
            "exact match\n"
        ]

        context_lines = [
            " exact match\n"
        ]

        # should find first exact match, not the whitespace-tolerant one
        result = find_hunk_start(context_lines, original_lines, fuzzy=False)
        assert result == 0

    def test_hunk_not_found_raises_error(self):
        """Test that missing hunks raise ValueError instead of returning 0."""
        original_lines = [
            "completely different\n",
            "content here\n"
        ]

        context_lines = [
            " nonexistent line\n"
        ]

        with pytest.raises(MissingHunkError):
            find_hunk_start(context_lines, original_lines, fuzzy=False)

    def test_capture_hunk_handles_missing_hunk(self):
        """Test that capture_hunk properly handles missing hunks."""
        original_lines = [
            "existing line\n"
        ]

        # hunk that won't be found
        hunk_lines = [
            " nonexistent context\n",
            "+new line\n"
        ]

        with pytest.raises(MissingHunkError):
            capture_hunk(hunk_lines, original_lines, 0, 0, "", False)

    def test_addition_only_hunk(self):
        """Test that addition-only hunks are handled correctly."""
        original_lines = [
            "line 1\n",
            "line 2\n"
        ]

        # only additions, no context
        hunk_lines = [
            "+new line 1\n",
            "+new line 2\n"
        ]

        # should handle addition-only hunks without searching for context
        header, offset, last_hunk = capture_hunk(hunk_lines, original_lines, 0, 0, "", False)
        assert header == "@@ -0,0 +1,2 @@\n"

    def test_fuzzy_fallback_when_exact_fails(self):
        """Test that fuzzy matching works when exact matching fails."""
        original_lines = [
            "line one\n",  # different words
            "line two\n",
            "line three\n"
        ]

        context_lines = [
            " line 1\n",  # similar but different
            " line 2\n"
        ]

        # exact should fail
        with pytest.raises(MissingHunkError):
            find_hunk_start(context_lines, original_lines, fuzzy=False)

        # fuzzy should succeed
        result = find_hunk_start(context_lines, original_lines, fuzzy=True)
        assert result == 0  # should find fuzzy match

    def test_deletion_lines_in_context(self):
        """Test that deletion lines are properly used for context matching."""
        original_lines = [
            "keep this\n",
            "delete this\n",
            "keep this too\n"
        ]

        context_lines = [
            " keep this\n",
            "-delete this\n",  # deletion line should match original
            " keep this too\n"
        ]

        result = find_hunk_start(context_lines, original_lines, fuzzy=False)
        assert result == 0

    def test_mixed_whitespace_types(self):
        """Test handling of mixed tabs and spaces."""
        original_lines = [
            "\t\tfunction() {\n",  # tabs
            "    var x = 1;\n",  # spaces
            "\t    return x;\n",  # mixed
            "\t}\n"
        ]

        context_lines = [
            " \t\tfunction() {\n",  # different leading whitespace
            "     var x = 1;\n",  # different indentation
            " \treturn x;\n",  # normalized whitespace
            " }\n"
        ]

        # whitespace-tolerant matching should handle this
        result = find_hunk_start(context_lines, original_lines, fuzzy=False)
        assert result == 0