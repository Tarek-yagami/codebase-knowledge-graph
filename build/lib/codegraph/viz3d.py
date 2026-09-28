"""Renders a codegraph.graph.MultiDiGraph as an interactive 3D, click-to-expand
knowledge graph (WebGL via 3d-force-graph), starting collapsed at the module
level.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "graph3d.html"


def render_3d_html(g: nx.MultiDiGraph, out_path: Path, title: str = "Codebase Knowledge Graph") -> None:
    nodes = [{"id": n, **d} for n, d in g.nodes(data=True)]
    links = [{"source": u, "target": v, "kind": d["kind"]} for u, v, d in g.edges(data=True)]

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__GRAPH_DATA__", json.dumps({"nodes": nodes, "links": links}))
    html = html.replace("__TITLE__", title)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
