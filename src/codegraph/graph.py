"""Builds a networkx graph from parser.ParseResult and exports it for
visualization / downstream retrieval.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from codegraph.parser import ParseResult


def build_graph(result: ParseResult) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for node_id, node in result.nodes.items():
        g.add_node(
            node_id,
            kind=node.kind,
            name=node.name,
            file=node.file,
            lineno=node.lineno,
            end_lineno=node.end_lineno,
            docstring=node.docstring,
            source=node.source,
        )
    for edge in result.edges:
        if edge.src in g and edge.dst in g:
            g.add_edge(edge.src, edge.dst, kind=edge.kind)
    return g


def graph_stats(g: nx.MultiDiGraph) -> dict:
    kind_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        kind_counts[data["kind"]] = kind_counts.get(data["kind"], 0) + 1
    edge_kind_counts: dict[str, int] = {}
    for _, _, data in g.edges(data=True):
        edge_kind_counts[data["kind"]] = edge_kind_counts.get(data["kind"], 0) + 1
    return {
        "num_nodes": g.number_of_nodes(),
        "num_edges": g.number_of_edges(),
        "nodes_by_kind": kind_counts,
        "edges_by_kind": edge_kind_counts,
    }


def export_json(g: nx.MultiDiGraph, path: Path) -> None:
    data = {
        "nodes": [{"id": n, **d} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v, "kind": d["kind"]} for u, v, d in g.edges(data=True)],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
