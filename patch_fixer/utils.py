from patch_fixer.errors import BadCarriageReturn


def normalize_line(line):
    """Normalize line endings while preserving whitespace."""
    if not isinstance(line, str):
        raise TypeError(f"Cannot normalize non-string object {line}")

    # edge case: empty string
    if line == "":
        return "\n"

    # special malformed ending: ...\n\r
    if line.endswith("\n\r"):
        raise BadCarriageReturn(f"carriage return after line feed: {line}")

    # handle CRLF and simple CR/LF endings
    if line.endswith("\r\n"):
        core = line[:-2]
    elif line.endswith("\r"):
        core = line[:-1]
    elif line.endswith("\n"):
        core = line[:-1]
    else:
        core = line

    # check for interior CR/LF (anything before the final terminator)
    if "\n" in core:
        raise ValueError(f"line feed in middle of line: {line}")
    if "\r" in core:
        raise BadCarriageReturn(f"carriage return in middle of line: {line}")

    return core + "\n"


def fuzzy_line_similarity(line1, line2, threshold=0.8):
    """Calculate similarity between two lines using a simple ratio."""
    l1, l2 = line1.strip(), line2.strip()

    # empty strings are identical
    if len(l1) == 0 and len(l2) == 0:
        return 1.0

    if l1 == l2:
        return 1.0

    if len(l1) == 0 or len(l2) == 0:
        return 0.0

    # count common characters
    common = 0
    for char in set(l1) & set(l2):
        common += min(l1.count(char), l2.count(char))

    total_chars = len(l1) + len(l2)
    return (2.0 * common) / total_chars if total_chars > 0 else 0.0


def split_ab(match_groups):
    a, b = match_groups
    a = f"./{a[2:]}"
    b = f"./{b[2:]}"
    return a, b


def read_file_with_fallback_encoding(file_path):
    """Read file with UTF-8, falling back to other encodings if needed."""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']

    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue

    # If all encodings fail, read as binary and replace problematic characters
    with open(file_path, 'rb') as f:
        content = f.read()
        # Decode with UTF-8, replacing errors
        text_content = content.decode('utf-8', errors='replace')
        return text_content.splitlines(keepends=True)
