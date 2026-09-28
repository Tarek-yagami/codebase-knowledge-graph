"""The actual query logic behind the MCP tools in codegraph_mcp/, kept
separate from the MCP wiring so it can be unit tested directly against a
graph, without needing a running server or a real repo on disk.
"""

from __future__ import annotations

import networkx as nx

# Edge kinds that don't represent a real structural dependency: "defines" is
# containment (a module defining a function isn't affected by that function
# changing), "similar_to" is conceptual, not structural - see semantic_search.
_NON_STRUCTURAL_EDGE_KINDS = ("defines", "similar_to")


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
    outgoing = [
        {"kind": d["kind"], "target": v}
        for _, v, d in g.out_edges(node_id, data=True)
        if d["kind"] not in _NON_STRUCTURAL_EDGE_KINDS
    ]
    incoming = [
        {"kind": d["kind"], "source": u}
        for u, _, d in g.in_edges(node_id, data=True)
        if d["kind"] not in _NON_STRUCTURAL_EDGE_KINDS
    ]
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


def impact_of_changes(g: nx.MultiDiGraph, changed_files: list[str]) -> dict:
    """Given a list of changed file paths (as git diff --name-only would report,
    relative to the repo root), find every node that structurally depends on
    something in those files, directly or transitively, by walking incoming
    calls/imports/inherits edges outward from the changed nodes. This is the
    real blast radius of a change, not just its immediate callers.
    """
    changed_set = set(changed_files)
    changed_nodes = [n for n, d in g.nodes(data=True) if d["file"] in changed_set]

    impacted: dict[str, dict] = {}
    frontier = list(changed_nodes)
    seen = set(changed_nodes)
    while frontier:
        next_frontier = []
        for node in frontier:
            if node not in g:
                continue
            for u, _, d in g.in_edges(node, data=True):
                if d["kind"] in _NON_STRUCTURAL_EDGE_KINDS or u in seen:
                    continue
                seen.add(u)
                impacted[u] = {"via": d["kind"], "reaches": node}
                next_frontier.append(u)
        frontier = next_frontier

    return {
        "changed_nodes": [node_summary(g, n) for n in changed_nodes],
        "impacted_nodes": [{**node_summary(g, n), **info} for n, info in impacted.items()],
    }


def suggested_reading_order(g: nx.MultiDiGraph) -> list[dict]:
    """Orders modules so each one's real dependencies (via imports) come
    before it, a leaves-first walk through the actual import graph rather
    than an arbitrary file listing. Modules involved in an import cycle are
    grouped together (in a stable, alphabetical order within the group)
    since no single ordering of a cycle is more correct than another.
    """
    modules = [n for n, d in g.nodes(data=True) if d["kind"] == "module"]

    deps = nx.MultiDiGraph()
    deps.add_nodes_from(modules)
    for u, v, d in g.edges(data=True):
        if d["kind"] == "imports" and u in deps and v in deps:
            deps.add_edge(v, u)  # reversed: v (imported) must be read before u (importer)

    condensed = nx.condensation(deps)
    order = []
    for component in nx.topological_sort(condensed):
        order.extend(sorted(condensed.nodes[component]["members"]))
    return [node_summary(g, n) for n in order]


def rank_by_similarity(embeddings: dict, query_vec, top_k: int = 10) -> list[tuple[float, str]]:
    """Pure ranking step for semantic search - takes an already-computed query
    vector so it's testable with fake embeddings, no real model needed.
    """
    scored = [(float(query_vec @ vec), node_id) for node_id, vec in embeddings.items()]
    scored.sort(reverse=True)
    return scored[:top_k]
