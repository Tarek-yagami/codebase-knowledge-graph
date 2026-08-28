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
    outgoing = [
        {"kind": d["kind"], "target": v} for _, v, d in _graph.out_edges(node_id, data=True) if d["kind"] != "defines"
    ]
    incoming = [
        {"kind": d["kind"], "source": u} for u, _, d in _graph.in_edges(node_id, data=True) if d["kind"] != "defines"
    ]
    return {"node": node_id, "depends_on": outgoing, "depended_on_by": incoming}


@mcp.tool()
def search_nodes(query: str) -> list[dict]:
    """Search for nodes by a substring of their name or docstring (case-insensitive).
    Use this when you don't know the exact node id to start from.
    """
    q = query.lower()
    matches = [
        _node_summary(n)
        for n, d in _graph.nodes(data=True)
        if q in d["name"].lower() or q in d.get("docstring", "").lower()
    ]
    return matches[:25]


if __name__ == "__main__":
    mcp.run(transport="stdio")
