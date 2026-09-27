"""Static analysis of a whole repo, in any language codegraph.languages
supports: each file is handed to its language's extractor, then every
by-name reference (calls, base classes, imports) is resolved against the
whole repo here, with the same confidence rules for every language.
"""

from __future__ import annotations

import os
import re
import sys
from collections import deque
from pathlib import Path

from codegraph.languages import language_for
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex
from codegraph.model import Edge, Node, ParseResult

DEFAULT_EXCLUDE = (
    "test", "tests", "testdata", "__tests__", "__mocks__", "fixtures", "build", "docs",
    "node_modules", "vendor", "dist", "target", "__pycache__", "venv",
)  # fmt: skip
_SKIPPED_FILES = re.compile(
    r"(^test_.*\.py|_test\.(py|go)|\.(test|spec)\.[cm]?[jt]sx?|\.d\.[cm]?ts|\.min\.js|\.blade\.php)$"
)
_MAX_FILE_BYTES = 1_000_000  # bigger than this is almost always generated or bundled code


def discover_files(root: Path, exclude: tuple[str, ...] = DEFAULT_EXCLUDE) -> list[tuple[str, Language]]:
    """Every source file under root that some extractor handles, as
    (repo-relative path, language). Hidden and excluded directories are
    pruned during the walk, so a huge node_modules is never even listed."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude and not d.startswith(".")]
        for filename in filenames:
            if _SKIPPED_FILES.search(filename):
                continue
            full = Path(dirpath) / filename
            rel = full.relative_to(root).as_posix()
            language = language_for(rel)
            if language is not None and full.stat().st_size <= _MAX_FILE_BYTES:
                found.append((rel, language))
    return sorted(found)


def _extract_all(root: Path, files: list[tuple[str, Language]]) -> tuple[list[FileFacts], dict[str, Language]]:
    facts_list: list[FileFacts] = []
    language_of: dict[str, Language] = {}
    failed_languages: set[str] = set()
    for rel, language in files:
        if language.name in failed_languages:
            continue
        try:
            facts = language.extract((root / rel).read_bytes(), rel)
        except SyntaxError:
            continue
        except Exception as e:
            # Grammars download on first use, so a network failure lands here.
            # Skip that one language rather than losing the whole repo.
            failed_languages.add(language.name)
            print(f"codegraph: skipping {language.name} files, grammar unavailable: {e}", file=sys.stderr)
            continue
        facts_list.append(facts)
        language_of[rel] = language
    return facts_list, language_of


class _Resolver:
    def __init__(
        self, nodes: dict[str, Node], language_of: dict[str, Language], index: RepoIndex, facts: list[FileFacts]
    ):
        self.nodes = nodes
        self.language_of = language_of
        self.index = index
        self.package_of = {f.module_id: f.package for f in facts if f.package is not None}
        self._open_specs = {f.module_id: f.open_imports for f in facts if f.open_imports}
        self._open_modules: dict[str, set[str]] = {}
        self.parent: dict[str, str] = {}
        self.members: dict[str, dict[str, str]] = {}  # class id -> method name -> method id
        self.bases_of: dict[str, list[str]] = {}
        self.top_level: dict[tuple[str, str], list[str]] = {}  # (language, name) -> ids
        self.classes: dict[tuple[str, str], list[str]] = {}

    def add_defines(self, edge: Edge) -> None:
        self.parent[edge.dst] = edge.src
        child, parent = self.nodes[edge.dst], self.nodes[edge.src]
        key = (self.language_of[child.file].name, child.name)
        if child.kind == "class":
            self.classes.setdefault(key, []).append(child.id)
        if parent.kind == "module":
            self.top_level.setdefault(key, []).append(child.id)
        elif parent.kind == "class" and child.kind == "function":
            self.members.setdefault(parent.id, {})[child.name] = child.id

    def pick(self, ref: Ref, pool: dict[tuple[str, str], list[str]]) -> str | None:
        """Resolves ref.name within pool, most specific scope first: the
        module it was imported from, the same file, the same package, the
        namespaces the file opens with wildcard imports, then the repo. A
        name that's ambiguous at the first scope where it appears stays
        unresolved."""
        file = self.nodes[ref.src].file
        language = self.language_of[file]
        candidates = pool.get((language.name, ref.name), [])
        if ref.via_import:
            modules = language.resolve_import(ref.via_import, file, self.index)
            if not modules:
                return None  # imported from outside the repo
            # Looked up in each target module's own language: a .vue file imports .ts ones.
            for m in modules:
                for c in pool.get((self.language_of[m].name, ref.name), []):
                    if self.nodes[c].file == m:
                        return c
            # The module is ours but doesn't define the name itself, e.g. a re-export.
        scopes = [lambda c: self.nodes[c].file == file]
        package = self.package_of.get(file)
        if package is not None:
            scopes.append(lambda c: self.package_of.get(self.nodes[c].file) == package)
        opened = self.open_modules(file)
        if opened:
            scopes.append(lambda c: self.nodes[c].file in opened)
        scopes.append(lambda c: True)
        for in_scope in scopes:
            local = [c for c in candidates if in_scope(c)]
            if len(local) == 1:
                return local[0]
            if local:
                return None
        return None

    def open_modules(self, file: str) -> set[str]:
        """Every module brought into scope by the file's wildcard imports."""
        if file not in self._open_modules:
            language = self.language_of[file]
            specs = self._open_specs.get(file, [])
            self._open_modules[file] = {m for s in specs for m in language.resolve_import(s, file, self.index)}
        return self._open_modules[file]

    def lexical(self, ref: Ref) -> str | None:
        """A bare name defined in an enclosing function, like a closure
        calling a sibling helper. Class bodies aren't enclosing scopes for
        a bare name, so the walk stops at the first non-function."""
        scope: str | None = ref.src
        while scope is not None and self.nodes[scope].kind == "function":
            candidate = f"{scope}.{ref.name}"
            if candidate in self.nodes:
                return candidate
            scope = self.parent.get(scope)
        return None

    def method(self, class_id: str, name: str) -> str | None:
        """Looks for `name` on class_id itself, then breadth-first up its
        bases, which covers the inherited-but-not-overridden case."""
        seen: set[str] = set()
        queue = deque([class_id])
        while queue:
            cid = queue.popleft()
            if cid in seen:
                continue
            seen.add(cid)
            if name in self.members.get(cid, {}):
                return self.members[cid][name]
            queue.extend(self.bases_of.get(cid, []))
        return None

    def call(self, ref: Ref) -> str | None:
        if ref.receiver is not None:
            class_id: str | None = ref.receiver
            if class_id not in self.nodes:
                class_id = self.pick(Ref(ref.src, ref.receiver, via_import=ref.receiver_import), self.classes)
            found = self.method(class_id, ref.name) if class_id else None
            if found or not ref.bare_fallback:
                return found
        return self.lexical(ref) or self.pick(ref, self.top_level)


def parse_repo(root: Path, exclude: tuple[str, ...] = DEFAULT_EXCLUDE) -> ParseResult:
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")
    files = discover_files(root, exclude)
    if not files:
        raise ValueError(f"no supported source files found under {root} (excluding {exclude})")

    facts_list, language_of = _extract_all(root, files)
    result = ParseResult()
    for facts in facts_list:
        result.nodes.update(facts.nodes)
    index = RepoIndex.build(root, facts_list)
    resolver = _Resolver(result.nodes, language_of, index, facts_list)

    defines = [e for f in facts_list for e in f.defines]
    for edge in defines:
        resolver.add_defines(edge)

    # Methods declared apart from their type (Go) join it once all types are known.
    for facts in facts_list:
        for method_id, type_name in facts.owners:
            owner = resolver.pick(Ref(method_id, type_name), resolver.classes) or facts.module_id
            edge = Edge(owner, method_id, "defines")
            resolver.add_defines(edge)
            defines.append(edge)
    result.edges.extend(defines)

    # Base classes follow the same scope rules as calls: guessing among
    # same-named classes linked std traits like `Error` to unrelated types.
    for facts in facts_list:
        for ref in facts.bases:
            base = resolver.pick(ref, resolver.classes)
            if base and base != ref.src:
                result.edges.append(Edge(ref.src, base, "inherits"))
                resolver.bases_of.setdefault(ref.src, []).append(base)
            else:
                result.unresolved_calls.append((ref.src, ref.name))

    calls: set[tuple[str, str]] = set()  # one edge per caller/callee pair, however many call sites
    for facts in facts_list:
        for ref in facts.calls:
            target = resolver.call(ref)
            if target is None:
                result.unresolved_calls.append((ref.src, ref.name))
            elif (ref.src, target) not in calls:
                calls.add((ref.src, target))
                result.edges.append(Edge(ref.src, target, "calls"))

    for facts in facts_list:
        language = language_of[facts.module_id]
        seen: set[str] = set()
        for spec in facts.imports:
            targets = language.resolve_import(spec, facts.module_id, index)
            if not targets:
                result.unresolved_imports.append((facts.module_id, spec))
            for target in targets:
                if target not in seen and target != facts.module_id:
                    result.edges.append(Edge(facts.module_id, target, "imports"))
                    seen.add(target)

    return result
