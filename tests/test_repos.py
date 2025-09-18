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

import git
import requests
from git import Repo
import pytest

REPOS = {
    ("asottile", "astpretty"): ("5b68c7e", "5a8296f"),
    ("numpy", "numpy"): ("dca33b3", "5f82966"),
    ("pallets", "click"): ("93c6966", "e11a1ef"),
    ("scipy", "scipy"): ("c2220c0", "4ca6dd9"),
    ("yaml", "pyyaml"): ("48838a3", "a2d19c0"),
}

CACHE_DIR = Path.home() / ".patch-testing"


def verify_commit_exists(self, repo: Repo, commit_hash: str) -> None:
    """Verify that a commit exists in the repository."""
    try:
        repo.commit(commit_hash)
    except git.exc.BadName:
        print(f"Commit {commit_hash} does not exist in {repo}.")
        sys.exit(1)
    except ValueError as e:
        # Commit belongs to a deleted branch (let caller handle it)
        raise e
    except Exception as e:
        print(f"❌ Error verifying commit {commit_hash}: {e}")
        sys.exit(1)


def download_commit_zip(self, commit_hash: str, dest_path: Path) -> None:
    """Download and extract the repo snapshot at a given commit via GitHub's zip URL."""
    url = f"https://github.com/{self.repo_path}/archive/{commit_hash}.zip"
    print(f"⬇️  Downloading snapshot from {url}")

    try:
        r = requests.get(url, stream=True)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to download commit snapshot: {e}")
        sys.exit(1)

    # Extract the zip into dest_path
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        # GitHub wraps contents in a top-level folder named like repo-<hash>
        top_level = z.namelist()[0].split("/")[0]
        z.extractall(dest_path.parent)

        # Move extracted folder to dest_path
        extracted_path = dest_path.parent / top_level
        if dest_path.exists():
            shutil.rmtree(dest_path)
        extracted_path.rename(dest_path)

    print(f"✅ Snapshot extracted to {dest_path}")

@pytest.mark.parametrize(
    "repo_group, repo_name, old_commit, new_commit",
    [(*repo, *commits) for repo, commits in REPOS.items()]
)
def test_integration_equality(repo_group, repo_name, old_commit, new_commit):
    """ Make sure the patch fixer doesn't corrupt valid diffs. """
    repo_head = CACHE_DIR / repo_name
    if Path.exists(repo_head):
        # if repo has been cached, use that
        pass    # TODO
    else:
        repo_url = f"https://github.com/{repo_group}/{repo_name}.git"
        repo = Repo.clone_from(repo_url, repo_head)
        pass
