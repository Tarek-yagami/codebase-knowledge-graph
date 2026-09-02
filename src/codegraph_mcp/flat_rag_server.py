"""A plain flat-chunk RAG MCP server, for comparison against server.py's
graph-backed one. Exposes exactly one tool: semantic search over isolated
code chunks, no relationships, no structure, nothing about what calls or
inherits from what. Reuses the same embeddings as the graph server so any
difference in answer quality comes from structure, not embedding quality.

Usage: python flat_rag_server.py <path-to-repo>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from codegraph import queries
from codegraph.embeddings import embed_nodes, get_model
from codegraph.graph import build_graph
from codegraph.parser import parse_repo

REPO_PATH = Path(sys.argv[1]).resolve()

mcp = MCPServer(
    "flat_rag",
    instructions=(
        "Semantic search over isolated code chunks from this repository. Each "
        "result is a standalone snippet - there is no information here about "
        "what calls what, what inherits from what, or how anything relates to "
        "anything else. Retrieve whatever chunks seem relevant and reason from "
        "their content alone."
    ),
)

_result = parse_repo(REPO_PATH)
_graph = build_graph(_result)
_embeddings = embed_nodes(_graph, REPO_PATH)


@mcp.tool()
def search_chunks(query: str, top_k: int = 8) -> list[dict]:
    """Semantic search over code chunks (functions and classes) by meaning.
    Returns each chunk's source code in isolation - no relationships to
    other chunks are included.
    """
    query_vec = get_model().encode([query], normalize_embeddings=True)[0]
    ranked = queries.rank_by_similarity(_embeddings, query_vec, top_k)

    chunks = []
    for score, node_id in ranked:
        data = _graph.nodes[node_id]
        chunks.append(
            {
                "file": data["file"],
                "line": data["lineno"],
                "similarity": round(score, 3),
                "source": data.get("source") or data.get("docstring", ""),
            }
        )
    return chunks


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
