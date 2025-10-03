import pytest
from hypothesis import given, strategies as st

from patch_fixer.patch_fixer import normalize_line, BadCarriageReturn

# --- Good cases --------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("", "\n"),                # empty string -> newline
    ("foo", "foo\n"),          # no terminator
    ("foo\r", "foo\n"),        # CR terminator normalized
    ("foo\n", "foo\n"),        # LF terminator unchanged
    ("foo\r\n", "foo\n"),      # CRLF normalized
])
def test_normalize_good(line, expected):
    assert normalize_line(line) == expected


# --- Type errors -------------------------------------------------

@pytest.mark.parametrize("bad", [
    123,
    4.56,
    None,
    True,
    ["list"],
    {"set"},
    {"dict": "val"},
    ("tuple",),
])
def test_normalize_type_error(bad):
    with pytest.raises(TypeError):
        normalize_line(bad)


# --- Bad endings -------------------------------------------------

@pytest.mark.parametrize("line", [
    "foo\n\r",   # LF then CR
    "foo\rx",    # CR not followed by LF at end
])
def test_normalize_bad_endings(line):
    with pytest.raises(BadCarriageReturn):
        normalize_line(line)


# --- Interior CR/LF ----------------------------------------------

def test_interior_lf_raises():
    line = "bad\nline\n"
    with pytest.raises(ValueError):
        normalize_line(line)

def test_interior_cr_raises():
    line = "bad\rcarriage\n"
    with pytest.raises(BadCarriageReturn):
        normalize_line(line)

# --- Hypothesis testing ------------------------------------------

# generate arbitrary strings including \r and \n
line_strategy = st.text(alphabet=st.characters(), min_size=0, max_size=100)

@given(line=line_strategy)
def test_normalize_line_hypothesis(line):
    # we want to see that normalize_line either:
    # 1. returns a string ending with exactly one "\n", or
    # 2. raises ValueError for interior LF, or
    # 3. raises BadCarriageReturn for interior CR or malformed endings
    try:
        result = normalize_line(line)
    except BadCarriageReturn:
        # must have an interior CR somewhere, or malformed ending
        cr_condition = (("\r" in line[:-2])
                        or (line.endswith("\r") and not line.endswith("\r\n"))
                        or line.endswith("\n\r"))
        assert cr_condition, f"BadCarriageReturn raised unexpectedly for line: {line!r}"
    except ValueError:
        # must have an interior LF somewhere
        assert "\n" in line[:-1], f"ValueError raised unexpectedly for line: {line!r}"
    else:
        # function returned normally
        assert result.endswith("\n"), f"Returned line does not end with \\n: {result!r}"

        core = result[:-1]
        assert "\n" not in core
        assert "\r" not in core