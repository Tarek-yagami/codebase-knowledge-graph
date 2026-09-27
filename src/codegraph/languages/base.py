"""The contract between a language extractor and the shared resolver in
parser.py. An extractor only sees one file and reports what it can see
there (definitions, import specs, call sites, base classes) as unresolved
names. parser.py then resolves those names against the whole repo.
"""

from __future__ import annotations

import posixpath
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from codegraph.model import Edge, Node

T = TypeVar("T")


@dataclass
class Ref:
    """A by-name reference from one node to something it calls or inherits."""

    src: str
    name: str
    # Class of the receiver for `self.x()` / `this.x()` / Go receiver calls:
    # an exact node id when the extractor knows it, else a type name.
    receiver: str | None = None
    # Import spec of the receiver type name, for static calls like PHP's `User::find()`.
    receiver_import: str | None = None
    # Import spec the name was brought in through (`from .x import name`,
    # `pkg.Name()` in Go), so it resolves to that exact module first.
    via_import: str | None = None
    # Languages with implicit `this` (Java, C#, C++): a bare `f()` inside a
    # class may be one of its methods, and otherwise resolves as a bare name.
    bare_fallback: bool = False


@dataclass
class FileFacts:
    module_id: str
    nodes: dict[str, Node] = field(default_factory=dict)
    defines: list[Edge] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    calls: list[Ref] = field(default_factory=list)
    bases: list[Ref] = field(default_factory=list)
    # (method id, owning type name) for methods declared apart from their
    # type, like Go methods, whose type may live in another file.
    owners: list[tuple[str, str]] = field(default_factory=list)
    # The package the file belongs to (Java/Kotlin package, C# namespace, Go
    # directory). Files in one package see each other's names without importing.
    package: str | None = None
    # Imports that bring a whole namespace into scope rather than one name:
    # `import a.b.*`, C#'s `using A.B;`, Rust's `use a::*`.
    open_imports: list[str] = field(default_factory=list)
    # Imports whose names this module passes on to its own importers: TS's
    # `export * from "./x"`, Python's `from .x import A` in a package's __init__.
    reexports: list[str] = field(default_factory=list)


@dataclass
class RepoIndex:
    root: Path
    modules: set[str]
    by_dir: dict[str, list[str]]
    packages: dict[str, list[str]]  # package name -> module ids declaring it
    # Per-language lookup tables built lazily on first resolve_import call.
    cache: dict = field(default_factory=dict)

    @classmethod
    def build(cls, root: Path, facts: list[FileFacts]) -> RepoIndex:
        by_dir: dict[str, list[str]] = {}
        packages: dict[str, list[str]] = {}
        for f in facts:
            by_dir.setdefault(posixpath.dirname(f.module_id), []).append(f.module_id)
            if f.package is not None:
                packages.setdefault(f.package, []).append(f.module_id)
        return cls(root, {f.module_id for f in facts}, by_dir, packages)

    def nearest_config(
        self, directory: str, filenames: tuple[str, ...], parse: Callable[[Path], T | None]
    ) -> tuple[str, T] | None:
        """The closest config file (go.mod, tsconfig.json, composer.json)
        at or above directory that parse accepts, as (its directory, parsed
        value). Cached per directory, since every file in a folder asks."""
        cache: dict[str, tuple[str, T] | None] = self.cache.setdefault(("config",) + filenames, {})
        if directory in cache:
            return cache[directory]
        result = None
        for filename in filenames:
            path = self.root / directory / filename
            parsed = parse(path) if path.is_file() else None
            if parsed is not None:
                result = (directory, parsed)
                break
        if result is None and directory:
            result = self.nearest_config(posixpath.dirname(directory), filenames, parse)
        cache[directory] = result
        return result


class Language(ABC):
    name: str
    extensions: tuple[str, ...] = ()  # file extensions a dedicated extractor claims
    grammars: tuple[str, ...] = ()  # tree-sitter grammar names it covers, so the fallback skips them

    @abstractmethod
    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        """Everything visible in one file, with references left unresolved."""

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        """Maps an import spec to the module ids it refers to. Empty means
        external (stdlib, third-party) or not resolvable statically."""
        return []
