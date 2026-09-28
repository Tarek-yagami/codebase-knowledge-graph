"""MCP server exposing a codebase's structural knowledge graph as tools, so
an agent can ask about relationships directly instead of reading or
grepping files to reconstruct them by hand.

Usage: codegraph-mcp <path-to-repo>
(or set CODEGRAPH_REPO instead of passing an argument)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from codegraph import queries
from codegraph.graph import build_graph
from codegraph.parser import parse_repo

REPO_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CODEGRAPH_REPO", ".")).resolve()

mcp = MCPServer(
    "codegraph",
    instructions=(
        "Tools for querying the structure of a codebase (imports, function calls, "
        "class inheritance) that has already been statically analyzed (Python, TypeScript/JavaScript, "
        "Vue, Go, PHP, Java, Kotlin, C#, Rust, C/C++, plus basic support for other tree-sitter languages). "
        "Node ids are file paths, with definitions as `<path>::<Class.method>`. Prefer these tools "
        "over reading or grepping source files whenever the question is about how code "
        "relates to other code: who calls this, what does this depend on, what's defined "
        "in this module. They give an exact answer and are far cheaper than reconstructing "
        "that relationship from raw files."
    ),
)

_graph = build_graph(parse_repo(REPO_PATH))
# Built on the first semantic_search rather than at startup: embedding a big
# repo takes minutes, and the structural tools shouldn't wait for it.
_embeddings: dict | None = None
_SEMANTIC_MISSING = (
    "Semantic search needs the optional extra, which pulls in PyTorch: pip install 'codebase-knowledge-graph[semantic]'"
)


@mcp.tool()
def list_modules() -> list[dict]:
    """List every module in the indexed repository, with its file path and docstring."""
    return queries.list_modules(_graph)


@mcp.tool()
def get_node(node_id: str) -> dict:
    """Get full details for a specific node (module, function, or class) by its id,
    including its docstring and source snippet. Use search_nodes first if you don't
    already know the exact id.
    """
    return queries.get_node(_graph, node_id)


@mcp.tool()
def list_children(node_id: str) -> list[dict]:
    """List the functions and classes defined directly inside a module or class."""
    return queries.list_children(_graph, node_id)


@mcp.tool()
def get_relationships(node_id: str) -> dict:
    """Get what a node depends on (imports, calls, or inherits from) and what depends
    on it in turn (who imports, calls, or inherits from it). This directly answers
    questions like "who calls this function" or "what does this module depend on"
    without needing to read or search any files.
    """
    return queries.get_relationships(_graph, node_id)


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
    return queries.search_nodes(_graph, query)


@mcp.tool()
def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """Find nodes whose *meaning* matches a natural-language description,
    even when no import or call connects them and the name doesn't contain
    your words at all - e.g. "code that handles retrying a failed request"
    might surface a retry-related method that never says "retry" in its
    name. Use this when search_nodes and find_by_name come up empty, or
    when the question is about what a piece of code does rather than what
    it's called or what calls it. The first call builds the index, which
    can take a minute or two on a large repo.
    """
    global _embeddings
    try:
        from codegraph.embeddings import embed_nodes, get_model

        if _embeddings is None:
            _embeddings = embed_nodes(_graph, REPO_PATH)
        query_vec = get_model().encode([query], normalize_embeddings=True)[0]
    except ImportError:
        return [{"error": _SEMANTIC_MISSING}]
    ranked = queries.rank_by_similarity(_embeddings, query_vec, top_k)
    return [{**queries.node_summary(_graph, node_id), "similarity": round(score, 3)} for score, node_id in ranked]


@mcp.tool()
def find_by_name(name: str) -> list[dict]:
    """Find every node whose name is exactly this (case-insensitive) - e.g.
    every method called `save` across every class, no matter how many there
    are. Use this once you know the precise name you're looking for; use
    search_nodes instead when you're exploring by concept and don't.
    """
    return queries.find_by_name(_graph, name)


@mcp.tool()
def impact_of_changes(changed_files: list[str]) -> dict:
    """Given file paths that changed (e.g. from `git diff --name-only`,
    relative to the repo root), find every node that structurally depends on
    them, directly or transitively, by walking calls/imports/inherits edges
    outward. Use this before a commit or review to see the real blast radius
    of a change, not just its immediate callers.
    """
    return queries.impact_of_changes(_graph, changed_files)


@mcp.tool()
def suggested_reading_order() -> list[dict]:
    """List every module in a sensible order to read them in: each module's
    real import dependencies come before it, so foundational modules appear
    first and the modules that build on them follow. Useful for onboarding
    onto an unfamiliar codebase without guessing where to start.
    """
    return queries.suggested_reading_order(_graph)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
