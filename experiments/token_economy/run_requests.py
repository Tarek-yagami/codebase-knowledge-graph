"""Research question 4 on requests: Claude Code with only default file tools
vs. with the codegraph MCP server also available.

Usage: python run_requests.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import mcp_config, run_claude, run_two_conditions  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent / "data" / "repos" / "requests" / "src" / "requests"
OUT_PATH = Path(__file__).resolve().parent / "results.json"

BASE_TOOLS = "Read Grep Glob"
GRAPH_TOOLS = BASE_TOOLS + (
    " mcp__codegraph__list_modules mcp__codegraph__get_node mcp__codegraph__list_children"
    " mcp__codegraph__get_relationships mcp__codegraph__search_nodes"
    " mcp__codegraph__find_by_name mcp__codegraph__semantic_search"
)
GRAPH_CONFIG = mcp_config("codegraph", "server.py", REPO)

QUESTIONS = [
    "Compare BaseAdapter.send and Session.send: what does each one call, and how are they related?",
    "What does ConnectTimeout inherit from, and if I catch ConnectionError, would that also catch a ConnectTimeout?",
    "Does HTTPProxyAuth define its own __init__ method, or does it inherit one? Where does it actually come from?",
    "What's the difference between the top-level requests.get and Session.get, and what does each one call internally?",
    "What would break if I changed the signature of Session.prepare_request?",
    "Which classes implement a close() method, and how are they related to each other?",
]


def main() -> None:
    run_two_conditions(
        QUESTIONS,
        OUT_PATH,
        run_a=lambda q: run_claude(q, REPO, BASE_TOOLS),
        run_b=lambda q: run_claude(q, REPO, GRAPH_TOOLS, GRAPH_CONFIG),
        label_a="baseline",
        label_b="graph",
    )


if __name__ == "__main__":
    main()
