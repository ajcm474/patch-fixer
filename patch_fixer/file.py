import re
import sys

from .diff import Diff
from .errors import DiffNotFoundError
from .utils import read_file_raw


class PatchFile:
    def __init__(self, filepath, **kwargs):
        self.original_lines = None
        self.diffs = None
        self.filepath = filepath
        self.options = kwargs

        try:
            self.content = read_file_raw(filepath)
        except (IOError, FileNotFoundError):
            print(f"Error: could not read patch file at {filepath}", file=sys.stderr)

        if not self.content:
            raise DiffNotFoundError(f"Patch file is empty: {filepath}")

    def split_by_diff(self):
        self.diffs = [
            Diff(raw_diff, **self.options) for raw_diff in
            re.split(
                r'(?=^diff --git )',
                self.content,
                flags=re.MULTILINE
            )[1:]   # remove empty first part
        ]
        if not self.diffs:
            raise DiffNotFoundError(f"File does not contain any diff blocks: {self.filepath}")

    def split_by_line(self):
        self.original_lines = self.content.splitlines(keepends=True)
