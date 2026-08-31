"""Same experiment as run_requests.py, run against Django's core package
instead, to test whether the graph's token advantage grows on a much
larger, real codebase (846 files vs. requests' 21).

Usage: python run_django.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import mcp_config, run_claude, run_two_conditions  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent / "data" / "repos" / "django" / "django"
OUT_PATH = Path(__file__).resolve().parent / "results_django.json"

BASE_TOOLS = "Read Grep Glob"
GRAPH_TOOLS = BASE_TOOLS + (
    " mcp__codegraph__list_modules mcp__codegraph__get_node mcp__codegraph__list_children"
    " mcp__codegraph__get_relationships mcp__codegraph__search_nodes"
    " mcp__codegraph__find_by_name mcp__codegraph__semantic_search"
)
GRAPH_CONFIG = mcp_config("codegraph", "server.py", REPO)

QUESTIONS = [
    "What's the full inheritance chain for HttpResponseNotFound up to its base class, and which sibling response classes share that same base? Watch out for classes that look like siblings but actually aren't.",
    "What does the Manager class in django.db.models.manager inherit from, and why might that be hard to determine automatically just from reading the code structure?",
    "How many different classes define a save() method across this codebase, and are they related to each other through inheritance?",
    "How many different places define a clean() method, and what do they have in common?",
    "What's the relationship between BaseManager, Manager, and QuerySet in django.db.models?",
    "What does EmptyManager inherit from, and how does that compare to how the regular Manager class is defined?",
]


def main() -> None:
    run_two_conditions(
        QUESTIONS,
        OUT_PATH,
        run_a=lambda q: run_claude(q, REPO, BASE_TOOLS, timeout=300),
        run_b=lambda q: run_claude(q, REPO, GRAPH_TOOLS, GRAPH_CONFIG, timeout=300),
        label_a="baseline",
        label_b="graph",
    )


if __name__ == "__main__":
    main()
