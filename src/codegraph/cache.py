"""Where codegraph keeps generated files (embeddings, rendered graphs): outside
the analyzed repo and outside the installed package, overridable with
CODEGRAPH_CACHE.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def cache_dir(*parts: str) -> Path:
    root = Path(os.environ.get("CODEGRAPH_CACHE") or Path.home() / ".cache" / "codegraph")
    return root.joinpath(*parts)


def repo_key(repo_root: Path) -> str:
    """A stable folder name per repo: readable, and unique even when two
    repos share a name."""
    resolved = repo_root.resolve()
    return f"{resolved.name}-{hashlib.sha1(str(resolved).encode()).hexdigest()[:8]}"
