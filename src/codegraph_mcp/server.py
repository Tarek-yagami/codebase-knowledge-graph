"""MCP server exposing a codebase's structural knowledge graph as tools, so
an agent can ask about relationships directly instead of reading or
grepping files to reconstruct them by hand.

Usage: python server.py <path-to-repo>
(or set CODEGRAPH_REPO instead of passing an argument)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from codegraph.embeddings import add_semantic_edges, embed_nodes, get_model
from codegraph.graph import build_graph
from codegraph.parser import parse_repo

REPO_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CODEGRAPH_REPO", ".")).resolve()

mcp = MCPServer(
    "codegraph",
    instructions=(
        "Tools for querying the structure of a Python codebase (imports, function calls, "
        "class inheritance) that has already been statically analyzed. Prefer these tools "
        "over reading or grepping source files whenever the question is about how code "
        "relates to other code: who calls this, what does this depend on, what's defined "
        "in this module. They give an exact answer and are far cheaper than reconstructing "
        "that relationship from raw files."
    ),
)

_result = parse_repo(REPO_PATH)
_graph = build_graph(_result)
_embeddings = embed_nodes(_graph, REPO_PATH)
add_semantic_edges(_graph, _embeddings)


def _node_summary(node_id: str) -> dict:
    data = _graph.nodes[node_id]
    return {
        "id": node_id,
        "kind": data["kind"],
        "name": data["name"],
        "file": data["file"],
        "line": data["lineno"],
        "docstring": data.get("docstring", ""),
    }


@mcp.tool()
def list_modules() -> list[dict]:
    """List every module in the indexed repository, with its file path and docstring."""
    return [_node_summary(n) for n, d in _graph.nodes(data=True) if d["kind"] == "module"]


@mcp.tool()
def get_node(node_id: str) -> dict:
    """Get full details for a specific node (module, function, or class) by its id,
    including its docstring and source snippet. Use search_nodes first if you don't
    already know the exact id.
    """
    if node_id not in _graph.nodes:
        return {"error": f"no such node: {node_id}"}
    data = dict(_graph.nodes[node_id])
    data["id"] = node_id
    return data


@mcp.tool()
def list_children(node_id: str) -> list[dict]:
    """List the functions and classes defined directly inside a module or class."""
    if node_id not in _graph.nodes:
        return [{"error": f"no such node: {node_id}"}]
    children = [v for _, v, d in _graph.out_edges(node_id, data=True) if d["kind"] == "defines"]
    return [_node_summary(c) for c in children]


@mcp.tool()
def get_relationships(node_id: str) -> dict:
    """Get what a node depends on (imports, calls, or inherits from) and what depends
    on it in turn (who imports, calls, or inherits from it). This directly answers
    questions like "who calls this function" or "what does this module depend on"
    without needing to read or search any files.
    """
    if node_id not in _graph.nodes:
        return {"error": f"no such node: {node_id}"}
    skip = ("defines", "similar_to")  # similar_to is conceptual, not structural - see semantic_search
    outgoing = [
        {"kind": d["kind"], "target": v} for _, v, d in _graph.out_edges(node_id, data=True) if d["kind"] not in skip
    ]
    incoming = [
        {"kind": d["kind"], "source": u} for u, _, d in _graph.in_edges(node_id, data=True) if d["kind"] not in skip
    ]
    return {"node": node_id, "depends_on": outgoing, "depended_on_by": incoming}


@mcp.tool()
def search_nodes(query: str) -> list[dict]:
    """Search for nodes by name or docstring (case-insensitive), for when you
    don't know the exact name to look for and are exploring by concept or
    keyword instead. Results are ranked: an exact name match comes first,
    then a partial name match, then a docstring-only mention - each result
    says which one it was, so a node that just happens to mention the word
    in passing doesn't get confused with one actually named that. If you
    already know the exact name, use find_by_name instead, it's precise
    where this is deliberately fuzzy.
    """
    q = query.lower()
    tiers: list[list[dict]] = [[], [], []]
    for n, d in _graph.nodes(data=True):
        name = d["name"].lower()
        if name == q:
            tiers[0].append({**_node_summary(n), "matched_on": "exact name"})
        elif q in name:
            tiers[1].append({**_node_summary(n), "matched_on": "partial name"})
        elif q in d.get("docstring", "").lower():
            tiers[2].append({**_node_summary(n), "matched_on": "docstring"})
    return (tiers[0] + tiers[1] + tiers[2])[:25]


@mcp.tool()
def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """Find nodes whose *meaning* matches a natural-language description,
    even when no import or call connects them and the name doesn't contain
    your words at all - e.g. "code that handles retrying a failed request"
    might surface a retry-related method that never says "retry" in its
    name. Use this when search_nodes and find_by_name come up empty, or
    when the question is about what a piece of code does rather than what
    it's called or what calls it.
    """
    query_vec = get_model().encode([query], normalize_embeddings=True)[0]

    scored = [(float(query_vec @ vec), node_id) for node_id, vec in _embeddings.items()]
    scored.sort(reverse=True)
    return [{**_node_summary(node_id), "similarity": round(score, 3)} for score, node_id in scored[:top_k]]


@mcp.tool()
def find_by_name(name: str) -> list[dict]:
    """Find every node whose name is exactly this (case-insensitive) - e.g.
    every method called `save` across every class, no matter how many there
    are. Use this once you know the precise name you're looking for; use
    search_nodes instead when you're exploring by concept and don't.
    """
    q = name.lower()
    return [_node_summary(n) for n, d in _graph.nodes(data=True) if d["name"].lower() == q]


if __name__ == "__main__":
    mcp.run(transport="stdio")
