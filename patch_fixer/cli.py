#!/usr/bin/env python3
"""Command-line interface for patch-fixer."""

import argparse
import sys
from pathlib import Path

from .patch_fixer import fix_patch
from .split import split_patch


def fix_command(args):
    """Handle the fix command."""
    with open(args.broken_patch, encoding='utf-8') as f:
        patch_lines = f.readlines()

    fixed_lines = fix_patch(
        patch_lines,
        args.original,
        fuzzy=args.fuzzy,
        add_newline=args.add_newline
    )

    with open(args.output, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)

    print(f"Fixed patch written to {args.output}")
    return 0


def split_command(args):
    """Handle the split command."""
    with open(args.patch_file, encoding='utf-8') as f:
        patch_lines = f.readlines()

    # read files to include from file or command line
    if args.include_file:
        with open(args.include_file, encoding='utf-8') as f:
            files_to_include = [line.strip() for line in f if line.strip()]
    else:
        files_to_include = args.files or []

    included, excluded = split_patch(patch_lines, files_to_include)

    # write output files
    with open(args.included_output, 'w', encoding='utf-8') as f:
        f.writelines(included)

    with open(args.excluded_output, 'w', encoding='utf-8') as f:
        f.writelines(excluded)

    print(f"Patch split into:")
    print(f"  Included: {args.included_output} ({len(included)} lines)")
    print(f"  Excluded: {args.excluded_output} ({len(excluded)} lines)")

    return 0


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog='patch-fixer',
        description='Fix broken git patches or split them by file lists.'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # fix command
    fix_parser = subparsers.add_parser(
        'fix',
        help='Fix a broken patch file'
    )
    fix_parser.add_argument(
        'original',
        help='Original file or directory that the patch applies to'
    )
    fix_parser.add_argument(
        'broken_patch',
        help='Path to the broken patch file'
    )
    fix_parser.add_argument(
        'output',
        help='Path where the fixed patch will be written'
    )
    fix_parser.add_argument(
        '--fuzzy',
        action='store_true',
        help='Enable fuzzy string matching when finding hunks in original files'
    )
    fix_parser.add_argument(
        '--add-newline',
        action='store_true',
        help='Add final newline when processing "No newline at end of file" markers'
    )

    # split command
    split_parser = subparsers.add_parser(
        'split',
        help='Split a patch file based on file lists'
    )
    split_parser.add_argument(
        'patch_file',
        help='Path to the patch file to split'
    )
    split_parser.add_argument(
        'included_output',
        help='Output file for included files'
    )
    split_parser.add_argument(
        'excluded_output',
        help='Output file for excluded files'
    )
    split_parser.add_argument(
        '-f', '--files',
        nargs='*',
        help='Files to include (can specify multiple)'
    )
    split_parser.add_argument(
        '-i', '--include-file',
        help='File containing list of files to include (one per line)'
    )

    # parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # dispatch to appropriate command
    try:
        if args.command == 'fix':
            return fix_command(args)
        elif args.command == 'split':
            return split_command(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())