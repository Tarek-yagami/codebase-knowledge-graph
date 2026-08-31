"""Same RQ1 comparison as run_requests.py, but against Django's core
package. Both questions are "complete enumeration" style, where flat-chunk
retrieval has a real recall risk (the target set is much bigger than
top_k) and the graph doesn't, since it walks real edges instead of
similarity-ranking. Ground truth (verified against the parsed graph
directly) is 21 save() definitions and 28 clean() definitions.

Usage: python run_django.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import mcp_config, run_claude, run_two_conditions  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent / "data" / "repos" / "django" / "django"
OUT_PATH = Path(__file__).resolve().parent / "results_django.json"

GRAPH_TOOLS = (
    "mcp__codegraph__list_modules mcp__codegraph__get_node mcp__codegraph__list_children"
    " mcp__codegraph__get_relationships mcp__codegraph__search_nodes"
    " mcp__codegraph__find_by_name mcp__codegraph__semantic_search"
)
FLAT_RAG_TOOLS = "mcp__flat_rag__search_chunks"

GRAPH_CONFIG = mcp_config("codegraph", "server.py", REPO)
FLAT_RAG_CONFIG = mcp_config("flat_rag", "flat_rag_server.py", REPO)

QUESTIONS = [
    "List every different class that defines a save() method across this codebase. I need the complete list, not just examples.",
    "List every different place that defines a clean() method across this codebase. I need the complete list, not just examples.",
]


def main() -> None:
    run_two_conditions(
        QUESTIONS,
        OUT_PATH,
        run_a=lambda q: run_claude(q, REPO, FLAT_RAG_TOOLS, FLAT_RAG_CONFIG, timeout=300),
        run_b=lambda q: run_claude(q, REPO, GRAPH_TOOLS, GRAPH_CONFIG, timeout=300),
        label_a="flat_rag",
        label_b="graph",
    )


if __name__ == "__main__":
    main()
