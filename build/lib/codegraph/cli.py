"""Console-script entry points, exposed as `codegraph-viz` once this package
is installed. scripts/visualize.py is a thin wrapper around this for running
straight from a source checkout without installing anything.

Usage: codegraph-viz <path-to-repo> [title] [--out PATH] [--no-open]
"""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from codegraph.cache import cache_dir, repo_key
from codegraph.graph import build_graph
from codegraph.parser import parse_repo
from codegraph.viz3d import render_3d_html


def visualize() -> None:
    parser = argparse.ArgumentParser(prog="codegraph-viz", description="Render a repo as an explorable 3D graph.")
    parser.add_argument("repo", type=Path, help="path to the repository to analyze")
    parser.add_argument("title", nargs="?", help="page title (defaults to the repo's folder name)")
    parser.add_argument("--out", type=Path, help="where to write the page (defaults to codegraph's cache folder)")
    parser.add_argument("--no-open", action="store_true", help="don't open the page in a browser")
    args = parser.parse_args()

    repo_path = args.repo.resolve()
    out = args.out or cache_dir("graphs", repo_key(repo_path), "graph3d.html")
    render_3d_html(build_graph(parse_repo(repo_path)), out, title=args.title or repo_path.name)
    print(f"wrote {out}")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())
