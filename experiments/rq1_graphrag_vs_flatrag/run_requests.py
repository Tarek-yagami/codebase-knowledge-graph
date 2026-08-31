"""Research question 1: does structural graph traversal + semantic retrieval
answer real "how does X relate to Y" questions better than plain flat-chunk
RAG over the same code?

Both conditions get ONLY their own retrieval tool - no Read/Grep/Glob in
either one - so the comparison isolates retrieval strategy (graph vs. flat
chunks) rather than being diluted by falling back to reading files. Note:
since both conditions are still driven by the same agentic Claude Code loop
(able to call its tool multiple times), this tests "does an agentic
assistant benefit from a graph tool vs. a flat-chunk tool", not a classic
single-shot retrieve-then-generate RAG comparison - see the writeup for why
that distinction mattered for the results.

Usage: python run_requests.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import mcp_config, run_claude, run_two_conditions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
REPO = ROOT / "data" / "repos" / "requests" / "src" / "requests"
OUT_PATH = Path(__file__).resolve().parent / "results.json"

GRAPH_TOOLS = (
    "mcp__codegraph__list_modules mcp__codegraph__get_node mcp__codegraph__list_children"
    " mcp__codegraph__get_relationships mcp__codegraph__search_nodes"
    " mcp__codegraph__find_by_name mcp__codegraph__semantic_search"
)
FLAT_RAG_TOOLS = "mcp__flat_rag__search_chunks"

GRAPH_CONFIG = mcp_config("codegraph", "server.py", REPO)
FLAT_RAG_CONFIG = mcp_config("flat_rag", "flat_rag_server.py", REPO)

QUESTIONS = [
    "Compare BaseAdapter.send and Session.send: what does each one call, and how are they related?",
    "What does ConnectTimeout inherit from, and if I catch ConnectionError, would that also catch a ConnectTimeout?",
    "Does HTTPProxyAuth define its own __init__ method, or does it inherit one? Where does it actually come from?",
    "What's the difference between the top-level requests.get and Session.get, and what does each one call internally?",
    "List every exception class in this codebase that inherits from RequestException, directly or indirectly. I need the complete list, not just examples.",
    "List every class in this codebase that implements a close() method. I need the complete list, not just examples.",
]


def main() -> None:
    run_two_conditions(
        QUESTIONS,
        OUT_PATH,
        run_a=lambda q: run_claude(q, REPO, FLAT_RAG_TOOLS, FLAT_RAG_CONFIG),
        run_b=lambda q: run_claude(q, REPO, GRAPH_TOOLS, GRAPH_CONFIG),
        label_a="flat_rag",
        label_b="graph",
    )


if __name__ == "__main__":
    main()
