"""MCP talks JSON-RPC over stdout - a stray print() anywhere in the startup
path (parsing, graph building, embedding) would silently corrupt the
protocol stream. This asserts the real startup sequence never writes to
stdout, using a fake embedding model so it stays fast, no real model load.
"""

import contextlib
import io

import numpy as np

from codegraph.embeddings import add_semantic_edges
from codegraph.graph import build_graph
from codegraph.parser import parse_repo


class _FakeModel:
    def encode(self, texts, **kwargs):
        rng = np.random.default_rng(0)
        vectors = rng.normal(size=(len(texts), 8))
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def test_startup_sequence_never_writes_to_stdout(make_repo, monkeypatch):
    import codegraph.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "get_model", lambda: _FakeModel())

    repo = make_repo(
        {
            "a.py": "class Foo:\n    def bar(self):\n        pass\n",
            "b.py": "from .a import Foo\n\n\ndef use():\n    return Foo()\n",
        }
    )

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = parse_repo(repo)
        g = build_graph(result)
        embeddings = embeddings_module.embed_nodes(g, repo, use_cache=False)
        add_semantic_edges(g, embeddings)

    assert captured.getvalue() == ""
