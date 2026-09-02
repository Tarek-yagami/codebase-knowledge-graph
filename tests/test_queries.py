"""Tests for the actual logic behind the MCP tools (src/codegraph/queries.py),
independent of the MCP server wiring itself.
"""

import numpy as np

from codegraph import queries
from codegraph.graph import build_graph
from codegraph.parser import parse_repo

REPO = {
    "auth.py": '''
class AuthBase:
    def __call__(self, request):
        pass


class HTTPBasicAuth(AuthBase):
    """Attaches HTTP Basic Authentication."""

    def __init__(self, username, password):
        self.username = username
        self.password = password

    def __call__(self, request):
        return request


class HTTPProxyAuth(HTTPBasicAuth):
    def __call__(self, request):
        return request
''',
    "sessions.py": '''
from .auth import HTTPBasicAuth


class Session:
    def get(self):
        return self.request()

    def request(self):
        """Send a request."""
        pass
''',
}


def build(make_repo):
    repo = make_repo(REPO)
    return build_graph(parse_repo(repo))


def test_list_modules(make_repo):
    g = build(make_repo)
    names = {m["id"] for m in queries.list_modules(g)}
    assert names == {"auth", "sessions"}


def test_get_node_returns_error_for_unknown_id(make_repo):
    g = build(make_repo)
    assert "error" in queries.get_node(g, "does.not.exist")


def test_get_node_returns_real_data(make_repo):
    g = build(make_repo)
    node = queries.get_node(g, "auth.HTTPBasicAuth")
    assert node["kind"] == "class"
    assert "Attaches HTTP Basic" in node["docstring"]


def test_list_children_returns_methods(make_repo):
    g = build(make_repo)
    children = {c["name"] for c in queries.list_children(g, "auth.HTTPBasicAuth")}
    assert children == {"__init__", "__call__"}


def test_get_relationships_excludes_defines_and_similar_to(make_repo):
    g = build(make_repo)
    g.add_edge("sessions.Session.get", "sessions.Session.request", kind="similar_to")
    rel = queries.get_relationships(g, "sessions.Session.get")
    kinds = {d["kind"] for d in rel["depends_on"]}
    assert "similar_to" not in kinds
    assert "calls" in kinds


def test_get_relationships_unknown_node(make_repo):
    g = build(make_repo)
    assert "error" in queries.get_relationships(g, "nope")


def test_search_nodes_ranks_exact_name_above_docstring_match(make_repo):
    g = build(make_repo)
    results = queries.search_nodes(g, "request")
    assert results[0]["matched_on"] == "exact name"
    assert results[0]["id"] == "sessions.Session.request"


def test_search_nodes_caps_at_25(make_repo):
    files = {f"m{i}.py": f"def target_{i}():\n    pass\n" for i in range(30)}
    g = build_graph(parse_repo(make_repo(files)))
    results = queries.search_nodes(g, "target")
    assert len(results) == 25


def test_find_by_name_exact_match_only(make_repo):
    g = build(make_repo)
    results = queries.find_by_name(g, "__call__")
    names = {r["id"] for r in results}
    assert names == {"auth.AuthBase.__call__", "auth.HTTPBasicAuth.__call__", "auth.HTTPProxyAuth.__call__"}


def test_find_by_name_no_match(make_repo):
    g = build(make_repo)
    assert queries.find_by_name(g, "nonexistent") == []


def test_rank_by_similarity_orders_by_score():
    embeddings = {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0]), "c": np.array([0.9, 0.1])}
    ranked = queries.rank_by_similarity(embeddings, np.array([1.0, 0.0]), top_k=2)
    assert [node_id for _, node_id in ranked] == ["a", "c"]
