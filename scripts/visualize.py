"""Builds the graph for a repo and renders it as an interactive 3D,
click-to-expand knowledge graph.

Usage: python scripts/visualize.py <path-to-repo> [title]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from codegraph.graph import build_graph
from codegraph.parser import parse_repo
from codegraph.viz3d import render_3d_html


def main() -> None:
    repo_path = Path(sys.argv[1]).resolve()
    title = sys.argv[2] if len(sys.argv) > 2 else repo_path.name

    result = parse_repo(repo_path)
    g = build_graph(result)

    out = Path("data") / "graph3d.html"
    render_3d_html(g, out, title=title)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
