"""Console-script entry points, exposed as `codegraph-viz` once this package
is installed. scripts/visualize.py is a thin wrapper around this for running
straight from a source checkout without installing anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

from codegraph.graph import build_graph
from codegraph.parser import parse_repo
from codegraph.viz3d import render_3d_html


def visualize() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: codegraph-viz <path-to-repo> [title]")
    repo_path = Path(sys.argv[1]).resolve()
    title = sys.argv[2] if len(sys.argv) > 2 else repo_path.name

    result = parse_repo(repo_path)
    g = build_graph(result)

    out = Path("data") / "graph3d.html"
    render_3d_html(g, out, title=title)
    print(f"wrote {out}")
