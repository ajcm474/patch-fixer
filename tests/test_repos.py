"""
Big picture idea:

1. Have a list of open source repos and specific commit pairs
2. For each repo (if not already cached):
    a. Clone outside this directory
    b. Reset to newer commit
    c. Git diff older commit
    d. Write to tests/<repo>-<old_hash>-<new_hash>-diff.txt
3. For each diff in tests/
    a. Run test_generator.py on it to create several invalid versions
    b. Verify that patch_fixer.py generates a valid diff from each invalid one
        i. Reset local copy of repo to older commit before testing
        ii. Git apply the diff, make sure it doesn't error out
        iii. Compare to repo at newer commit, excluding binary files
"""
import io
import shutil
import sys
import zipfile
from pathlib import Path

import requests
from git import Repo
import pytest

from patch_fixer import fix_patch

REPOS = {
    ("apache", "airflow"): ("26f6e54","2136f56"),   # big repo
    ("asottile", "astpretty"): ("5b68c7e", "5a8296f"),
    ("astral-sh", "ruff"): ("7fee877", "11dae2c"),
    ("gabrielecirulli", "2048"): ("878098f", "478b6ec"),    # adds binary files
    ("mrdoob", "three.js"): ("5f3a718", "b97f111"),         # replaces images
    ("myriadrf", "LimeSDR-Mini"): ("0bb75e7", "fb012c8"),   # gigantic diffs
    ("numpy", "numpy"): ("dca33b3", "5f82966"),
    ("pallets", "click"): ("93c6966", "e11a1ef"),
    ("psf", "black"): ("8d9d18c", "903bef5"),   # whole year's worth of changes
    ("PyCQA", "flake8"): ("8bdec0b", "d45bdc0"),    # two years of changes
    ("scipy", "scipy"): ("c2220c0", "4ca6dd9"),
    ("tox-dev", "tox"): ("fb3fe66", "01442da"),     # four years
    ("yaml", "pyyaml"): ("48838a3", "a2d19c0"),
    ("zertovitch", "hac"): ("c563d18", "17207ee")   # renamed binary files
}

CACHE_DIR = Path.home() / ".patch-testing"


class DeletedBranchError(ValueError):
    def __init__(self, commit_hash):
        self.commit_hash = commit_hash
        super().__init__()


def verify_commit_exists(repo: Repo, commit_hash: str) -> None:
    """Verify that a commit exists in the repository."""
    try:
        repo.commit(commit_hash)
    except ValueError:
        # commit belongs to a deleted branch (let caller handle it)
        raise DeletedBranchError(commit_hash)


def download_commit_zip(repo_url, commit_hash: str, dest_path: Path) -> None:
    """Download and extract the repo snapshot at a given commit via GitHub's zip URL."""
    url = f"{repo_url}/archive/{commit_hash}.zip"
    print(f"Downloading snapshot from {url}")

    try:
        r = requests.get(url, stream=True)
        r.raise_for_status()
    except Exception as e:
        # TODO: don't use bare except
        print(f"Failed to download commit snapshot: {e}")
        sys.exit(1)

    # extract the zip into dest_path
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        # GitHub wraps contents in a top-level folder named like repo-<hash>
        top_level = z.namelist()[0].split("/")[0]
        z.extractall(dest_path.parent)

        # move extracted folder to dest_path
        extracted_path = dest_path.parent / top_level
        if dest_path.exists():
            shutil.rmtree(dest_path)
        extracted_path.rename(dest_path)

    print(f"Snapshot extracted to {dest_path}")


def clone_repos(repo_group, repo_name, old_commit, new_commit):
    repo_new_path = CACHE_DIR / f"{repo_name}-{new_commit}"
    repo_old_path = CACHE_DIR / f"{repo_name}-{old_commit}"

    # if repo has been cached, use that
    old_exists = Path.exists(repo_old_path)
    new_exists = Path.exists(repo_new_path)
    if old_exists or new_exists:
        if not old_exists:
            shutil.copytree(repo_new_path, repo_old_path)
        if not new_exists:
            shutil.copytree(repo_old_path, repo_new_path)

        # TODO: handle deleted branches here too
        repo_old = Repo(repo_old_path)
        repo_new = Repo(repo_new_path)
        repo_old.git.reset("--hard", old_commit)
        repo_new.git.reset("--hard", new_commit)

    # otherwise, clone it and make a copy for each commit
    else:
        repo_url = f"https://github.com/{repo_group}/{repo_name}.git"
        repo_new = Repo.clone_from(repo_url, repo_new_path)

        try:
            verify_commit_exists(repo_new, new_commit)
            repo_new.git.reset("--hard", new_commit)
        except DeletedBranchError:
            download_commit_zip(repo_url[:-4], new_commit, repo_new_path)
            # no sense keeping around an object that points to HEAD
            repo_new = Repo(repo_new_path)

        # prevent downloading the repo twice if we can help it
        shutil.copytree(repo_new_path, repo_old_path)
        repo_old = Repo(repo_old_path)
        try:
            verify_commit_exists(repo_old, old_commit)
            repo_old.git.reset("--hard", old_commit)
        except DeletedBranchError:
            download_commit_zip(repo_url[:-4], old_commit, repo_old_path)

    return repo_old, repo_old_path, repo_new, repo_new_path


@pytest.mark.parametrize(
    "repo_group, repo_name, old_commit, new_commit",
    [(*repo, *commits) for repo, commits in REPOS.items()]
)
def test_integration_equality(repo_group, repo_name, old_commit, new_commit):
    """ Make sure the patch fixer doesn't corrupt valid diffs. """
    (
        repo_old,
        repo_old_path,
        repo_new,
        repo_new_path
    ) = clone_repos(repo_group, repo_name, old_commit, new_commit)

    expected = repo_new.git.diff(old_commit, new_commit)
    input_lines = expected.splitlines(keepends=True)
    fixed_lines = fix_patch(input_lines, repo_old_path)
    actual = "".join(fixed_lines)

    assert actual == expected
