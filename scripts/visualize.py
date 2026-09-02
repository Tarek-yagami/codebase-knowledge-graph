"""Runs the visualizer straight from a source checkout, no install needed.
Once this package is installed (`pip install .`), use `codegraph-viz`
instead, this just calls the same code.

Usage: python scripts/visualize.py <path-to-repo> [title]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from codegraph.cli import visualize

if __name__ == "__main__":
    visualize()
