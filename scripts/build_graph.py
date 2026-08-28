"""CLI entry point: parse a repo, build the structural graph, print stats,
and export it as JSON.

Usage: python scripts/build_graph.py <path-to-repo> [output.json]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from codegraph.graph import build_graph, export_json, graph_stats
from codegraph.parser import parse_repo


def main() -> None:
    repo_path = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data") / "graph.json"

    result = parse_repo(repo_path)
    g = build_graph(result)

    print(json.dumps(graph_stats(g), indent=2))
    print(f"unresolved calls/inherits (not matched to a known definition): {len(result.unresolved_calls)}")
    print(f"unresolved imports (external packages/stdlib, not part of this repo): {len(result.unresolved_imports)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_json(g, out_path)
    print(f"graph written to {out_path}")


if __name__ == "__main__":
    main()
