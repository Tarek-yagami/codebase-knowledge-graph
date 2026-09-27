"""Rust: the generic tags-based extraction (structs, traits, functions,
`impl` methods, calls) plus the module tree. `mod x;` and `use` paths
(`crate::`, `self::`, `super::`, or another crate in the Cargo workspace)
map to files the way rustc lays modules out on disk, and `impl Trait for
Type` makes Type inherit Trait.
"""

from __future__ import annotations

import posixpath
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node as SyntaxNode

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Ref, RepoIndex
from codegraph.languages.generic import GenericLanguage
from codegraph.model import member_id


@dataclass
class _Crate:
    name: str  # as Rust code spells it: `-` becomes `_`
    roots: list[str]  # crate root files relative to the crate directory, like `src/lib.rs`


def _load_crate(cargo_toml: Path) -> _Crate | None:
    """The crate a Cargo.toml defines, with its root files (`[lib]` and
    `[[bin]]` paths, else the `src/lib.rs` and `src/main.rs` defaults).
    None for a workspace-only manifest, so the search keeps going up."""
    try:
        data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = (data.get("package") or {}).get("name")
    if not isinstance(name, str):
        return None
    roots = [(data.get("lib") or {}).get("path", "src/lib.rs"), "src/main.rs"]
    roots += [b["path"] for b in data.get("bin", []) if isinstance(b.get("path"), str)]
    return _Crate(name.replace("-", "_"), [posixpath.normpath(r) for r in roots])


def _use_paths(node: SyntaxNode, prefix: str = "") -> list[tuple[str, str | None]]:
    """(full path, local name) for everything a `use` tree brings in; the
    local name is None for a wildcard. `a::{b, c as d, e::*}` expands to
    three entries."""
    t = node.type
    if t in ("scoped_use_list", "use_list"):
        path = node.child_by_field_name("path")
        inner = f"{prefix}{ts.text(path)}::" if path is not None else prefix
        items = node.child_by_field_name("list") if t == "scoped_use_list" else node
        return [p for child in (items.named_children if items is not None else []) for p in _use_paths(child, inner)]
    if t == "use_as_clause":
        return [(prefix + ts.text(node.child_by_field_name("path")), ts.text(node.child_by_field_name("alias")))]
    if t == "use_wildcard":
        target = node.named_children[0] if node.named_children else None
        return [(prefix + ts.text(target) if target is not None else prefix.rstrip(":"), None)]
    full = prefix + ts.text(node)
    return [(full, full.rsplit("::", 1)[-1])]


class RustLanguage(GenericLanguage):
    extensions = (".rs",)

    def __init__(self) -> None:
        super().__init__("rust")

    def scan_module(self, root: SyntaxNode, facts: FileFacts, defined: dict[tuple[int, int], tuple[str, str]]) -> None:
        imports: dict[str, str] = {}  # local name -> use path
        impls = []
        for item in root.named_children:
            if item.type == "mod_item" and item.child_by_field_name("body") is None:
                facts.imports.append(f"self::{ts.text(item.child_by_field_name('name'))}")
            elif item.type == "use_declaration":
                argument = item.child_by_field_name("argument")
                for path, local in _use_paths(argument) if argument is not None else []:
                    facts.imports.append(path)
                    if local is None:
                        facts.open_imports.append(path)
                    else:
                        imports[local] = path
            elif item.type == "impl_item" and item.child_by_field_name("trait") is not None:
                impls.append(item)
        for item in impls:
            type_id = member_id(facts.module_id, ts.text(item.child_by_field_name("type")).split("<")[0])
            if type_id not in facts.nodes:
                continue
            trait = ts.text(item.child_by_field_name("trait")).split("<")[0]
            head, _, rest = trait.partition("::")
            # A qualified trait (`fmt::Debug`, `std::error::Error`) resolves as that path, so a
            # std trait never lands on an unrelated type of the same name in the repo.
            trait_path: str | None = None
            if rest:
                trait_path = f"{imports[head]}::{rest}" if head in imports else trait
            facts.bases.append(Ref(type_id, trait.rsplit("::", 1)[-1], via_import=trait_path))
        self.attach_imports(facts, imports)

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        found = index.nearest_config(posixpath.dirname(from_file), ("Cargo.toml",), _load_crate)
        if found is None:
            return []
        crate_dir, crate = found
        segments = spec.split("::")
        head = segments[0]
        if head == "crate":
            root_dir, base, rest = self._module_root(from_file, crate_dir, crate), [], segments[1:]
        elif head in ("self", "super"):
            root_dir = self._module_root(from_file, crate_dir, crate)
            base = self._module_path(from_file, root_dir)
            while segments and segments[0] == "super":
                base, segments = base[:-1], segments[1:]
            rest = segments[1:] if segments and segments[0] == "self" else segments
        else:
            other = self._workspace_crates(index).get(head)
            if other is None:  # std, or a crates.io dependency
                return []
            other_dir, other_crate = other
            root_dir = posixpath.join(other_dir, posixpath.dirname(other_crate.roots[0]))
            base, rest = [], segments[1:]
        # The longest prefix of the path that's a module file; the rest names items in it.
        for k in range(len(rest), -1, -1):
            module = self._module_file(root_dir, base + rest[:k], index)
            if module is not None:
                return [module]
        return []

    @staticmethod
    def _module_root(file: str, crate_dir: str, crate: _Crate) -> str:
        """The directory whose files form the module tree file belongs to:
        the directory of the crate root the file sits under."""
        dirs = [posixpath.normpath(posixpath.join(crate_dir, posixpath.dirname(r))) for r in crate.roots]
        under = [d for d in dirs if file.startswith(d.rstrip(".") + "/") or d == "."]
        return max(under, key=len) if under else dirs[0]

    @staticmethod
    def _module_path(file: str, root_dir: str) -> list[str]:
        """`src/a/b.rs` -> ["a", "b"]; `src/a/mod.rs` -> ["a"]; `src/lib.rs` -> []."""
        parts = posixpath.relpath(file, root_dir)[: -len(".rs")].split("/")
        if parts[-1] in ("mod", "lib", "main"):
            parts.pop()
        return parts

    @staticmethod
    def _module_file(root_dir: str, path: list[str], index: RepoIndex) -> str | None:
        root_dir = "" if root_dir == "." else root_dir
        if not path:
            candidates = [posixpath.join(root_dir, "lib.rs"), posixpath.join(root_dir, "main.rs")]
        else:
            joined = posixpath.join(root_dir, *path)
            candidates = [f"{joined}.rs", posixpath.join(joined, "mod.rs")]
        return next((c for c in candidates if c in index.modules), None)

    @staticmethod
    def _workspace_crates(index: RepoIndex) -> dict[str, tuple[str, _Crate]]:
        """Crate name -> (crate directory, crate), for every crate with source files in the repo."""
        crates: dict[str, tuple[str, _Crate]] | None = index.cache.get("rust_crates")
        if crates is None:
            crates = {}
            for module in (m for m in index.modules if m.endswith(".rs")):
                found = index.nearest_config(posixpath.dirname(module), ("Cargo.toml",), _load_crate)
                if found is not None:
                    crates.setdefault(found[1].name, found)
            index.cache["rust_crates"] = crates
        return crates
