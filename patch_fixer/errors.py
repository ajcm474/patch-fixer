

class HunkErrorBase(Exception):
    def __init__(self, hunk_lines, file="(unknown file)"):
        super().__init__()
        self.hunk = "".join(hunk_lines)
        self.file = file

    def format_hunk_for_error(self):
        """Format hunk for error messages, showing only context and deletion lines."""
        error_lines = []
        for line in self.hunk.splitlines(keepends=True):
            if line.startswith((' ', '-')):  # context or deletion lines
                error_lines.append(line)
            # skip addition lines (+) as they shouldn't be in the original file
        return ''.join(error_lines)

    def add_file(self, file):
        self.file = file


class MissingHunkError(HunkErrorBase):
    def __str__(self):
        return (
            f"Could not find hunk in {self.file}:"
            f"\n================================"
            f"\n{self.format_hunk_for_error()}"
            f"================================"
        )


class OutOfOrderHunk(HunkErrorBase):
    def __init__(self, hunk_lines, prev_header, file="(unknown file)"):
        super().__init__(hunk_lines, file)
        self.prev_header = prev_header

    def __str__(self):
        return (
            f"Out of order hunk in {self.file}:"
            f"\n==============================="
            f"\n{self.format_hunk_for_error()}"
            f"==============================="
            f"\nOccurs before previous hunk with header {self.prev_header}"
        )


class EmptyHunk(Exception):
    # don't inherit from HunkErrorBase since this is a sentinel exception
    # meant to catch the case where the very last hunk is empty
    pass


class BadCarriageReturn(ValueError):
    pass


class DiffNotFoundError(ValueError):
    pass
