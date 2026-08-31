"""Semantic layer: embeds each function/class node's name + docstring with a
local model (no API key, no per-call cost) and adds "similar_to" edges
between nodes whose meaning is close, even when nothing imports or calls
between them. Embeddings are cached to disk per repo, since the MCP server
re-parses fresh on every launch and recomputing embeddings for a large repo
every time would be slow.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

import networkx as nx
import numpy as np

_MODEL_NAME = "all-MiniLM-L6-v2"
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "embedding_cache"

_model = None  # lazy-loaded, the import itself is slow-ish and not always needed


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        try:
            # already downloaded once - skip the network round-trip checking for updates
            _model = SentenceTransformer(_MODEL_NAME, local_files_only=True)
        except Exception:
            _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _cache_path(repo_root: Path) -> Path:
    key = hashlib.sha1(str(repo_root.resolve()).encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{key}.pkl"


def _node_text(data: dict) -> str:
    parts = [data["name"].replace(".", " ").replace("_", " ")]
    if data.get("docstring"):
        parts.append(data["docstring"][:400])
    elif data.get("source"):
        parts.append(data["source"][:200])
    return "\n".join(parts)


def embed_nodes(g: nx.MultiDiGraph, repo_root: Path, use_cache: bool = True) -> dict[str, np.ndarray]:
    """Embeds every function/class node. Returns {node_id: vector}."""
    cache_file = _cache_path(repo_root)
    targets = [(n, d) for n, d in g.nodes(data=True) if d["kind"] in ("function", "class")]
    node_ids = [n for n, _ in targets]

    if use_cache and cache_file.exists():
        cached: dict[str, np.ndarray] = pickle.loads(cache_file.read_bytes())
        if set(cached.keys()) == set(node_ids):
            return cached

    texts = [_node_text(d) for _, d in targets]
    vectors = get_model().encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    result = dict(zip(node_ids, vectors))

    if use_cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pickle.dumps(result))

    return result


def add_semantic_edges(g: nx.MultiDiGraph, embeddings: dict[str, np.ndarray], top_k: int = 5, threshold: float = 0.55) -> int:
    """Adds a 'similar_to' edge from each node to its top_k nearest neighbors
    by cosine similarity (vectors are pre-normalized, so this is a dot
    product), skipping anything below `threshold`. Returns edges added.
    """
    ids = list(embeddings.keys())
    matrix = np.stack([embeddings[i] for i in ids])
    sims = matrix @ matrix.T

    added = 0
    for row, node_id in enumerate(ids):
        sims[row, row] = -1.0  # never match itself
        top = np.argsort(sims[row])[::-1][:top_k]
        for col in top:
            score = sims[row, col]
            if score < threshold:
                continue
            g.add_edge(node_id, ids[col], kind="similar_to", weight=float(score))
            added += 1
    return added
