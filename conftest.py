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