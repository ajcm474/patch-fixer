from io import StringIO

import pytest

from patch_fixer.errors import DiffNotFoundError
from patch_fixer.file import PatchFile


def test_empty_file_raises():
    empty_file = StringIO("")
    with pytest.raises(DiffNotFoundError):
        PatchFile(empty_file)


def test_file_with_no_diff():
    bogus_file = StringIO(
        "Hello. My name is Inigo Montoya. "
        "You killed my father. Prepare to die!"
    )
    bogus_patch = PatchFile(bogus_file)
    with pytest.raises(DiffNotFoundError):
        bogus_patch.split_by_diff()


def test_file_split_by_diff():
    diff = """diff --git a/hello.txt b/hello.txt
new file mode 100644
index 0000000...1234abc 100644
--- /dev/null
+++ b/hello.txt
@@ 0,0 1,2 @@
+print("hello")
+print('world')
diff --git a/hello.png b/hello.png
binary files a/hello.png and b/hello.png differ
index 1234abc...abc1234
diff --git a/delete.txt b/delete.txt
deleted file mode 100644
index 1234abc...0000000 100644
--- a/delete.txt
+++ /dev/null
@@ 1,2 0,0 @@
-print("goodbye")
-print('world')
"""
    part1 = (
        "diff --git a/hello.txt b/hello.txt\n"
        "new file mode 100644\n"
        "index 0000000...1234abc 100644\n"
        "--- /dev/null\n"
        "+++ b/hello.txt\n"
        "@@ 0,0 1,2 @@\n"
        '+print("hello")\n'
        "+print('world')\n"
    )
    part2 = (
        "diff --git a/hello.png b/hello.png\n"
        "binary files a/hello.png and b/hello.png differ\n"
        "index 1234abc...abc1234\n"
    )
    part3 = (
        "diff --git a/delete.txt b/delete.txt\n"
        "deleted file mode 100644\n"
        "index 1234abc...0000000 100644\n"
        "--- a/delete.txt\n"
        "+++ /dev/null\n"
        "@@ 1,2 0,0 @@\n"
        '-print("goodbye")\n'
        "-print('world')\n"
    )
    diff_file = StringIO(diff)
    patch = PatchFile(diff_file)
    patch.split_by_diff()
    assert len(patch.diffs) == 3
    assert str(patch.diffs[0]) == part1
    assert str(patch.diffs[1]) == part2
    assert str(patch.diffs[2]) == part3
