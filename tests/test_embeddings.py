"""Tests for the non-model parts of embeddings.py - the atomic cache write,
specifically. Doesn't load the real sentence-transformers model, so this
stays fast and has no network/download dependency.
"""

from codegraph.embeddings import _write_atomic


def test_write_atomic_writes_correct_content(tmp_path):
    target = tmp_path / "cache.pkl"
    _write_atomic(target, b"hello")
    assert target.read_bytes() == b"hello"


def test_write_atomic_overwrites_existing_file(tmp_path):
    target = tmp_path / "cache.pkl"
    _write_atomic(target, b"first")
    _write_atomic(target, b"second")
    assert target.read_bytes() == b"second"


def test_write_atomic_leaves_no_temp_files_behind(tmp_path):
    target = tmp_path / "cache.pkl"
    _write_atomic(target, b"data")
    assert list(tmp_path.iterdir()) == [target]
