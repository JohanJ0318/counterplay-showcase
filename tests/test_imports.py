"""Every module imports.

Not a deep test, and it catches a specific mistake that broke this app twice in
one week: a name used inside a page before the line that defines it. Python
does not notice until the code runs, and a server-rendered page only runs when
somebody loads it — which, in production, means a coach.

Importing is not rendering. But a syntax error, a circular import, or a
top-level name that no longer exists dies here instead of in front of a
stranger.
"""
from __future__ import annotations

import importlib
import pathlib

import pytest

MODULES = sorted(
    f"{f.parent.name}.{f.stem}"
    for f in list(pathlib.Path("app").glob("*.py"))
       + list(pathlib.Path("counterplay").glob("*.py"))
    if f.stem != "__init__"
)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)


def test_there_are_modules_to_check():
    """Guards against the glob silently matching nothing and passing."""
    assert len(MODULES) > 10, f"only found {len(MODULES)} modules"
