import re

path_regex = r'[^ \n\t]+(?: [^ \n\t]+)*'
regexes = {
    "DIFF_LINE": re.compile(rf'^diff --git (a/{path_regex}) (b/{path_regex})$'),
    "MODE_LINE": re.compile(r'^(?:new|deleted) file mode ([0-7]{6})$'),
    "INDEX_LINE": re.compile(r'^index ([0-9a-f]{7,64})\.\.([0-9a-f]{7,64})( [0-7]{6})?$|^similarity index ([0-9]+)%$'),
    "BINARY_LINE": re.compile(rf'^Binary files (a/{path_regex}|/dev/null) and (b/{path_regex}|/dev/null) differ$'),
    "RENAME_FROM": re.compile(rf'^rename from ({path_regex})$'),
    "RENAME_TO": re.compile(rf'^rename to ({path_regex})$'),
    "FILE_HEADER_START": re.compile(rf'^--- (a/{path_regex}|/dev/null)$'),
    "FILE_HEADER_END": re.compile(rf'^\+\+\+ (b/{path_regex}|/dev/null)$'),
    "HUNK_HEADER": re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$'),
    "END_LINE": re.compile(r'^\\ No newline at end of file$'),
}


def match_line(line):
    for line_type, regex in regexes.items():
        match = regex.match(line)
        if match:
            return match.groups(), line_type
    return None, None
