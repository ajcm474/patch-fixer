from patch_fixer.errors import MissingHunkError, EmptyHunk, OutOfOrderHunk
from patch_fixer.regex import regexes, match_line
from patch_fixer.utils import fuzzy_line_similarity, normalize_line


def find_hunk_start(context_lines, original_lines, fuzzy=False):
    """Search original_lines for context_lines and return start line index (0-based)."""
    ctx = []
    for line in context_lines:
        if regexes["END_LINE"].match(line):
            # "\ No newline at end of file" is just git metadata; skip
            continue
        elif line.startswith(" "):
            ctx.append(line.lstrip(" "))
        elif line.startswith("-"):
            # can't use lstrip; we want to keep other dashes in the line
            ctx.append(line[1:])
        elif line.isspace() or line == "":
            ctx.append(line)
    if not ctx:
        raise ValueError("Cannot search for empty hunk.")

    # first try exact matching
    for i in range(len(original_lines) - len(ctx) + 1):
        # this part will fail if the diff is malformed beyond hunk header
        equal_lines = [original_lines[i + j].strip() == ctx[j].strip() for j in range(len(ctx))]
        if all(equal_lines):
            return i

    # if fuzzy matching is enabled and exact match failed, try fuzzy match
    if fuzzy:
        best_match_score = 0.0
        best_match_pos = 0

        for i in range(len(original_lines) - len(ctx) + 1):
            total_similarity = 0.0
            for j in range(len(ctx)):
                similarity = fuzzy_line_similarity(original_lines[i + j], ctx[j])
                total_similarity += similarity

            avg_similarity = total_similarity / len(ctx)
            if avg_similarity > best_match_score and avg_similarity > 0.6:
                best_match_score = avg_similarity
                best_match_pos = i

        if best_match_score > 0.6:
            return best_match_pos

    raise MissingHunkError(context_lines)


def find_all_hunk_starts(hunk_lines, search_lines, fuzzy=False):
    """Return all line indices in search_lines where this hunk matches."""
    matches = []
    start = 0
    while True:
        try:
            idx = find_hunk_start(hunk_lines, search_lines[start:], fuzzy=fuzzy)
            matches.append(start + idx)
            start += idx + 1
        except MissingHunkError:
            break
    return matches


def capture_hunk(current_hunk, original_lines, offset, last_hunk, old_header, fuzzy=False):
    """
    Try to locate the hunk's true position in the original file.

    If multiple possible matches exist, pick the one closest to the expected
    (possibly corrupted) line number derived from the old hunk header.
    """
    if not current_hunk:
        raise EmptyHunk

    # extract needed info from old header match groups
    expected_old_start = int(old_header[0]) if old_header else 0
    try:
        hunk_context = old_header[4]
    except IndexError:
        hunk_context = ""

    # presence or absence of end line shouldn't affect line counts
    if regexes["END_LINE"].match(current_hunk[-1]):
        hunk_len = len(current_hunk) - 1
    else:
        hunk_len = len(current_hunk)

    # compute line counts
    context_count = sum(1 for l in current_hunk if l.startswith(' '))
    minus_count = sum(1 for l in current_hunk if l.startswith('-'))
    plus_count = sum(1 for l in current_hunk if l.startswith('+'))

    old_count = context_count + minus_count
    new_count = context_count + plus_count

    if minus_count == hunk_len:     # file deletion
        old_start = 1
        new_start = 0
    elif plus_count == hunk_len:    # file creation
        old_start = 0
        new_start = 1
    else:                           # file modification
        search_index = last_hunk
        search_lines = original_lines[search_index:]

        # gather *all* possible matches
        matches = find_all_hunk_starts(current_hunk, search_lines, fuzzy=fuzzy)
        if matches:
            # rebase to file line numbers (1-indexed later)
            candidate_positions = [m + search_index for m in matches]

            if expected_old_start:
                # choose the one closest to the expected position
                old_start = min(
                    candidate_positions,
                    key=lambda pos: abs(pos + 1 - expected_old_start),
                ) + 1  # convert to 1-indexed
            else:
                # pick first match if no expected line info
                old_start = candidate_positions[0] + 1
        else:
            # try from start of file, excluding lines already searched
            search_index += hunk_len
            search_lines = original_lines[:search_index]
            matches = find_all_hunk_starts(current_hunk, search_lines, fuzzy=fuzzy)
            if not matches:
                raise MissingHunkError(current_hunk)
            if expected_old_start:
                old_start = (
                    min(matches, key=lambda pos: abs(pos + 1 - expected_old_start)) + 1
                )
            else:
                old_start = matches[0] + 1

        if old_start < last_hunk + 1:
            raise OutOfOrderHunk(current_hunk, original_lines[last_hunk])

        if new_count == 0:
            # complete deletion of remaining content
            new_start = 0
        else:
            new_start = old_start + offset

    offset += (new_count - old_count)

    last_hunk += (old_start - last_hunk)

    # use condensed header if it's only one line
    old_part = f"{old_start},{old_count}" if old_count != 1 else f"{old_start}"
    new_part = f"{new_start},{new_count}" if new_count != 1 else f"{new_start}"

    fixed_header = f"@@ -{old_part} +{new_part} @@{hunk_context}\n"

    return fixed_header, offset, last_hunk



class Hunk:
    def __init__(self, content, diff, offset, last_hunk, fuzzy=False):
        self.diff = diff

        self.lines = [
            normalize_line(line) for line in content.splitlines(keepends=True)
        ]
        if not self.lines:
            raise EmptyHunk

        header_line = self.lines[0]
        old_header, line_type = match_line(header_line)

        if line_type != "HUNK_HEADER":
            # regex didn't work; construct fake old header as a placeholder
            context = header_line.split("@@")[-1].rstrip("\n")
            old_start = 0 if self.diff.new_file else 1
            old_header = (old_start, None, None, None, context)

        self.header, self.offset, self.last_hunk = capture_hunk(
            self.lines[1:],             # hunk content
            self.diff.original_lines,
            offset,
            last_hunk,
            old_header,
            fuzzy=fuzzy
        )
        self.lines[0] = self.header
