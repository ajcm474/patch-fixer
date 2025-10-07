"""
Idea:

1. main function takes in:
    a. patch file
    b. list of files to split out
2. reads patch file, splits based on file headers (assumed to be valid)
3. for each file being patched:
    a. if the file is in the list, send its hunks to output 1
    b. otherwise send its hunks to output 2
    c. hunks include all header lines so each output is a valid diff

Could share some functionality with refactored, modular version of fix_patch
"""
