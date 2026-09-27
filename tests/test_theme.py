"""The CSS reaches the browser as written.

theme.CSS is an ordinary Python string, so a CSS escape like \\25be must be
written with its backslash doubled. Written once, Python reads \\25 as an octal
escape, the browser gets an invisible control character followed by the text
"be", and every dropdown in the product printed "be" and "b4" beside it.
"""
import re

from app import theme


def test_css_has_no_control_characters():
    bad = [(i, hex(ord(c))) for i, c in enumerate(theme.CSS)
           if ord(c) < 32 and c not in "\n\t"]
    assert bad == []


def test_dropdown_arrows_survive_python():
    assert 'summary::after{content:" \\25be"' in theme.CSS
    assert 'summary::after{content:" \\25b4"}' in theme.CSS


def test_every_css_content_escape_is_intact():
    for value in re.findall(r'content:"([^"]*)"', theme.CSS):
        assert not re.search(r"[\x00-\x1f]", value), value


def test_every_css_token_used_is_defined():
    """An undefined var() is silently empty: --card left the zone box
    see-through and --line left borders undrawn, with no error anywhere."""
    import glob
    import re
    src = "".join(open(f, encoding="utf-8").read() for f in glob.glob("app/*.py"))
    used = set(re.findall(r"var\(--([\w-]+)", src))
    defined = set(re.findall(r"--([\w-]+)\s*:", src))
    assert not used - defined, sorted(used - defined)
