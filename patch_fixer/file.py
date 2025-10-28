import re
import sys

from . import fix_patch
from .diff import Diff
from .errors import DiffNotFoundError
from .utils import read_file_raw


class PatchFile:
    def __init__(self, patch_path, original_path, **kwargs):
        self.fixed_lines = None
        self.diffs = None
        self.patch_path = patch_path
        self.options = kwargs
        self.options["original"] = original_path

        try:
            self.content = read_file_raw(patch_path)
        except (IOError, FileNotFoundError):
            print(
                f"Error: could not read patch file at {patch_path}",
                file=sys.stderr
            )

        if not self.content:
            raise DiffNotFoundError(f"Patch file is empty: {patch_path}")

    def split_by_diff(self):
        self.diffs = [
            Diff(raw_diff, **self.options).content for raw_diff in
            re.split(
                r'(?=^diff --git )',
                self.content,
                flags=re.MULTILINE
            )[1:]   # remove empty first part
        ]
        if not self.diffs:
            raise DiffNotFoundError(
                f"Patch file does not contain any diff blocks: {self.patch_path}"
            )
        self.fixed_lines = "".join("".join(diff) for diff in self.diffs)

    def split_by_line(self):
        patch_lines = self.content.splitlines(keepends=True)
        self.fixed_lines = fix_patch(patch_lines, self.patch_path)
