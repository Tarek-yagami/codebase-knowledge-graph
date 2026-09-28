"""MCP talks JSON-RPC over stdout - a stray print() anywhere in the startup
path would silently corrupt the protocol stream. This starts the real server
module against a small repo and asserts nothing reaches stdout, then checks
that semantic search builds its index lazily, using a fake embedding model
so no real model loads.
"""

import contextlib
import importlib
import io
import sys

import numpy as np


class _FakeModel:
    def encode(self, texts, **kwargs):
        rng = np.random.default_rng(0)
        vectors = rng.normal(size=(len(texts), 8))
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _start_server(repo, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["codegraph-mcp", str(repo)])
    sys.modules.pop("codegraph_mcp.server", None)
    return importlib.import_module("codegraph_mcp.server")


def test_startup_never_writes_to_stdout_and_skips_embeddings(make_repo, monkeypatch):
    repo = make_repo(
        {
            "a.py": "class Foo:\n    def bar(self):\n        pass\n",
            "b.py": "from .a import Foo\n\n\ndef use():\n    return Foo()\n",
        }
    )
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        server = _start_server(repo, monkeypatch)

    assert captured.getvalue() == ""
    assert server._embeddings is None  # nothing embedded until semantic search is used
    assert server.get_relationships("b.py::use")["depends_on"] == [{"kind": "calls", "target": "a.py::Foo"}]


def test_semantic_search_builds_its_index_on_first_use(make_repo, monkeypatch, tmp_path):
    import codegraph.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "get_model", lambda: _FakeModel())
    monkeypatch.setattr(embeddings_module, "_CACHE_DIR", tmp_path / "cache")
    server = _start_server(make_repo({"a.py": "def retry_request():\n    pass\n"}), monkeypatch)

    results = server.semantic_search("retry", top_k=1)

    assert results[0]["id"] == "a.py::retry_request"
    assert server._embeddings is not None
