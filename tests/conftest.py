"""Shared test fixtures: a helper to write a small synthetic repo to disk,
so parser tests don't depend on the real cloned demo repos under data/repos/
(which are gitignored and won't exist in a fresh checkout or CI).
"""

from pathlib import Path

import pytest


@pytest.fixture
def make_repo(tmp_path):
    """Writes {relative_path: source} as files under a temp directory and
    returns the directory. Usage: make_repo({"a.py": "def f(): pass"})
    """

    def _make(files: dict[str, str]) -> Path:
        for rel_path, content in files.items():
            full = tmp_path / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        return tmp_path

    return _make
