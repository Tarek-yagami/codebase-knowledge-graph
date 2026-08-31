"""Prints the flat_rag-vs-graph comparison for an RQ1 results file.

Usage: python summarize.py [results.json]   (defaults to results.json)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import summarize  # noqa: E402

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results.json"
    summarize(path, "flat_rag", "graph")
