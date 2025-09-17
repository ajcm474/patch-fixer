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

repos = {
    "asottile/astpretty": ("5b68c7e", "5a8296f"),
    "numpy/numpy": ("dca33b3", "5f82966"),
    "pallets/click": ("93c6966", "e11a1ef"),
    "scipy/scipy": ("c2220c0", "4ca6dd9"),
    "yaml/pyyaml": ("48838a3", "a2d19c0"),
}
