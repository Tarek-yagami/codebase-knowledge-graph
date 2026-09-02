"""The actual query logic behind the MCP tools in codegraph_mcp/, kept
separate from the MCP wiring so it can be unit tested directly against a
graph, without needing a running server or a real repo on disk.
"""

from __future__ import annotations

import networkx as nx


def node_summary(g: nx.MultiDiGraph, node_id: str) -> dict:
    data = g.nodes[node_id]
    return {
        "id": node_id,
        "kind": data["kind"],
        "name": data["name"],
        "file": data["file"],
        "line": data["lineno"],
        "docstring": data.get("docstring", ""),
    }


def list_modules(g: nx.MultiDiGraph) -> list[dict]:
    return [node_summary(g, n) for n, d in g.nodes(data=True) if d["kind"] == "module"]


def get_node(g: nx.MultiDiGraph, node_id: str) -> dict:
    if node_id not in g.nodes:
        return {"error": f"no such node: {node_id}"}
    data = dict(g.nodes[node_id])
    data["id"] = node_id
    return data


def list_children(g: nx.MultiDiGraph, node_id: str) -> list[dict]:
    if node_id not in g.nodes:
        return [{"error": f"no such node: {node_id}"}]
    children = [v for _, v, d in g.out_edges(node_id, data=True) if d["kind"] == "defines"]
    return [node_summary(g, c) for c in children]


def get_relationships(g: nx.MultiDiGraph, node_id: str) -> dict:
    if node_id not in g.nodes:
        return {"error": f"no such node: {node_id}"}
    skip = ("defines", "similar_to")  # similar_to is conceptual, not structural - see semantic_search
    outgoing = [
        {"kind": d["kind"], "target": v} for _, v, d in g.out_edges(node_id, data=True) if d["kind"] not in skip
    ]
    incoming = [{"kind": d["kind"], "source": u} for u, _, d in g.in_edges(node_id, data=True) if d["kind"] not in skip]
    return {"node": node_id, "depends_on": outgoing, "depended_on_by": incoming}


def search_nodes(g: nx.MultiDiGraph, query: str) -> list[dict]:
    q = query.lower()
    tiers: list[list[dict]] = [[], [], []]
    for n, d in g.nodes(data=True):
        name = d["name"].lower()
        if name == q:
            tiers[0].append({**node_summary(g, n), "matched_on": "exact name"})
        elif q in name:
            tiers[1].append({**node_summary(g, n), "matched_on": "partial name"})
        elif q in d.get("docstring", "").lower():
            tiers[2].append({**node_summary(g, n), "matched_on": "docstring"})
    return (tiers[0] + tiers[1] + tiers[2])[:25]


def find_by_name(g: nx.MultiDiGraph, name: str) -> list[dict]:
    q = name.lower()
    return [node_summary(g, n) for n, d in g.nodes(data=True) if d["name"].lower() == q]


def rank_by_similarity(embeddings: dict, query_vec, top_k: int = 10) -> list[tuple[float, str]]:
    """Pure ranking step for semantic search - takes an already-computed query
    vector so it's testable with fake embeddings, no real model needed.
    """
    scored = [(float(query_vec @ vec), node_id) for node_id, vec in embeddings.items()]
    scored.sort(reverse=True)
    return scored[:top_k]
