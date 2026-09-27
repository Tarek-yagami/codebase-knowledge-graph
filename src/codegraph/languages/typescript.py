"""TypeScript and JavaScript extraction (including TSX/JSX). Both share one
extractor because the grammars share nearly every node type, and a TS
project routinely imports plain JS files.
"""

from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass
from pathlib import Path

import json5
from tree_sitter import Node as SyntaxNode
from tree_sitter import Tree

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex

_GRAMMAR_BY_EXTENSION = {
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}
_RESOLVE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

_CLASS_TYPES = {"class_declaration", "abstract_class_declaration", "interface_declaration", "class"}
_FUNCTION_DECLS = {"function_declaration", "generator_function_declaration"}
_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
# Named definitions get their own node, so their calls aren't credited to the enclosing function.
_OWN_NODE_TYPES = frozenset(_FUNCTION_DECLS | {"class_declaration", "abstract_class_declaration", "class"})


class _Imports:
    def __init__(self, root: SyntaxNode):
        self.specs: list[str] = []
        self.reexports: list[str] = []  # `export ... from "x"`
        self.symbols: dict[str, tuple[str, str]] = {}  # local name -> (spec, exported name)
        self.namespaces: dict[str, str] = {}  # `import * as ns` / `const ns = require(...)`
        for node in root.named_children:
            source = node.child_by_field_name("source")
            if node.type in ("import_statement", "export_statement") and source is not None:
                spec = ts.text(source).strip("'\"`")
                self.specs.append(spec)
                if node.type == "import_statement":
                    self._bind(node, spec)
                else:
                    self.reexports.append(spec)
            elif node.type in ("lexical_declaration", "variable_declaration"):
                for decl in node.named_children:
                    required = _require_spec(decl.child_by_field_name("value"))
                    if decl.type == "variable_declarator" and required is not None:
                        self.specs.append(required)
                        name = decl.child_by_field_name("name")
                        if name is not None and name.type == "identifier":
                            self.namespaces[ts.text(name)] = required

    def _bind(self, statement: SyntaxNode, spec: str) -> None:
        clause = next((c for c in statement.named_children if c.type == "import_clause"), None)
        if clause is None:
            return
        for part in clause.named_children:
            if part.type == "identifier":  # default import: the exported name isn't known
                self.symbols[ts.text(part)] = (spec, ts.text(part))
            elif part.type == "namespace_import":
                self.namespaces[ts.text(part.named_children[0])] = spec
            elif part.type == "named_imports":
                for spec_node in part.named_children:
                    name = ts.text(spec_node.child_by_field_name("name"))
                    alias = spec_node.child_by_field_name("alias")
                    self.symbols[ts.text(alias) if alias is not None else name] = (spec, name)

    def ref(self, src: str, parts: list[str]) -> Ref | None:
        if len(parts) == 1:
            name = parts[0]
            if name in self.symbols:
                spec, exported = self.symbols[name]
                return Ref(src, exported, via_import=spec)
            return Ref(src, name)
        if len(parts) == 2 and parts[0] in self.namespaces:
            return Ref(src, parts[1], via_import=self.namespaces[parts[0]])
        return None


def _require_spec(value: SyntaxNode | None) -> str | None:
    """The module spec in `require("x")`, or None if value isn't a require call."""
    if value is None or value.type != "call_expression" or ts.text(value.child_by_field_name("function")) != "require":
        return None
    args = value.child_by_field_name("arguments")
    return ts.text(args.named_children[0]).strip("'\"`") if args is not None and args.named_children else None


def _wrapped_function(value: SyntaxNode) -> SyntaxNode | None:
    """The function inside a wrapper call like React's `forwardRef(() => ...)`
    or `memo(function () {...})`, which is the real definition of the name."""
    if value.type != "call_expression":
        return None
    args = value.child_by_field_name("arguments")
    first = args.named_children[0] if args is not None and args.named_children else None
    return first if first is not None and first.type in _FUNCTION_VALUES else None


def _name_parts(node: SyntaxNode | None) -> list[str] | None:
    """`Foo`, `ns.Foo`, `Foo<T>` -> the dotted name parts, or None for
    anything that isn't a plain (possibly namespaced) name, like a mixin call."""
    if node is None:
        return None
    if node.type in ("identifier", "type_identifier", "property_identifier"):
        return [ts.text(node)]
    if node.type == "generic_type":
        return _name_parts(node.child_by_field_name("name"))
    if node.type == "nested_type_identifier":
        return ts.text(node).split(".")
    if node.type == "member_expression":
        obj = _name_parts(node.child_by_field_name("object"))
        prop = node.child_by_field_name("property")
        return obj + [ts.text(prop)] if obj and prop is not None else None
    return None


class ScriptWalker:
    """Walks one parsed script, recording its definitions and calls into facts."""

    def __init__(self, facts: FileFacts, language: str, imports: _Imports):
        self.facts = facts
        self.language = language
        self.imports = imports

    def visit(self, node: SyntaxNode, scope: tuple[str, str], class_id: str | None) -> None:
        for child in node.named_children:
            self._visit_statement(child, child, scope, class_id)

    def _visit_statement(
        self, node: SyntaxNode, anchor: SyntaxNode, scope: tuple[str, str], class_id: str | None
    ) -> None:
        t = node.type
        if t == "export_statement":
            decl = node.child_by_field_name("declaration")
            if decl is not None:
                self._visit_statement(decl, node, scope, class_id)
        elif t in _FUNCTION_DECLS:
            self._function(node, node.child_by_field_name("name"), node, anchor, scope, class_id)
        elif t in _CLASS_TYPES:
            self._class(node, node.child_by_field_name("name"), anchor, scope)
        elif t in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                value = decl.child_by_field_name("value")
                name = decl.child_by_field_name("name")
                if value is None or name is None or name.type != "identifier":
                    continue
                wrapped = _wrapped_function(value)
                if value.type in _FUNCTION_VALUES:
                    self._function(value, name, decl, anchor, scope, class_id)
                elif wrapped is not None:
                    self._function(wrapped, name, decl, anchor, scope, class_id)
                elif value.type == "class":
                    self._class(value, name, anchor, scope)
        elif t == "method_definition":
            self._function(node, node.child_by_field_name("name"), node, anchor, scope, class_id)
        elif t == "pair":  # `save: function () {...}` or `save: () => ...` in an object literal
            value = node.child_by_field_name("value")
            key = node.child_by_field_name("key")
            if value is not None and value.type in _FUNCTION_VALUES and key is not None:
                self._function(value, key, node, anchor, scope, class_id)
        elif t in ("public_field_definition", "field_definition"):
            value = node.child_by_field_name("value")
            if value is not None and value.type in _FUNCTION_VALUES:
                name = node.child_by_field_name("name") or node.child_by_field_name("property")
                self._function(value, name, node, anchor, scope, class_id)

    def _qual(self, scope: tuple[str, str], name: str) -> str:
        return f"{scope[1]}.{name}" if scope[1] else name

    def _class(self, node: SyntaxNode, name: SyntaxNode | None, anchor: SyntaxNode, scope: tuple[str, str]) -> None:
        if name is None:
            return
        qual = self._qual(scope, ts.text(name))
        class_id = ts.add_definition(self.facts, scope[0], qual, "class", self.language, node, anchor)
        for base in self._base_names(node):
            ref = self.imports.ref(class_id, base)
            if ref is not None:
                self.facts.bases.append(ref)
        body = node.child_by_field_name("body")
        if body is not None:
            self.visit(body, (class_id, qual), class_id)

    def _base_names(self, node: SyntaxNode) -> list[list[str]]:
        names: list[list[str]] = []
        for child in node.named_children:
            if child.type == "class_heritage":
                clauses = child.named_children
                if clauses and clauses[0].type not in ("extends_clause", "implements_clause"):
                    clauses = [child]  # JavaScript: the heritage node holds the base expression directly
                for clause in clauses:
                    value = clause.child_by_field_name("value") if clause.type == "extends_clause" else None
                    targets = [value] if value is not None else clause.named_children
                    names.extend(p for p in (_name_parts(t) for t in targets) if p)
            elif child.type == "extends_type_clause":
                names.extend(p for p in (_name_parts(t) for t in child.named_children) if p)
        return names

    def _function(
        self,
        node: SyntaxNode,
        name: SyntaxNode | None,
        span: SyntaxNode,
        anchor: SyntaxNode,
        scope: tuple[str, str],
        class_id: str | None,
    ) -> None:
        body = node.child_by_field_name("body")
        if name is None or body is None:  # anonymous, or an overload/abstract signature
            return
        qual = self._qual(scope, ts.text(name))
        fn_id = ts.add_definition(self.facts, scope[0], qual, "function", self.language, span, anchor)
        self.record_calls(fn_id, body, class_id)
        if body.type == "statement_block":
            self.visit(body, (fn_id, qual), class_id)

    def record_calls(self, fn_id: str, body: SyntaxNode, class_id: str | None) -> None:
        """Same confidence rules as Python: `this.x()`, `x()` and `ns.x()`
        are recorded, calls on any other receiver are not."""
        for n in ts.descendants(body, prune=_OWN_NODE_TYPES):
            if n.type == "call_expression":
                callee = n.child_by_field_name("function")
            elif n.type == "new_expression":
                callee = n.child_by_field_name("constructor")
            elif n.type in ("jsx_opening_element", "jsx_self_closing_element"):
                # Rendering <Button /> invokes the Button component. Lowercase
                # names (<div>) are built-in elements, not code in this repo.
                callee = n.child_by_field_name("name")
                if callee is None or not ts.text(callee)[:1].isupper():
                    continue
            else:
                continue
            if callee is None or ts.text(callee) == "require":
                continue
            receiver = callee.child_by_field_name("object") if callee.type == "member_expression" else None
            if receiver is not None and receiver.type == "this":
                if class_id is not None:
                    prop = ts.text(callee.child_by_field_name("property"))
                    self.facts.calls.append(Ref(fn_id, prop, receiver=class_id))
                continue
            parts = _name_parts(callee)
            ref = self.imports.ref(fn_id, parts) if parts else None
            if ref is not None:
                self.facts.calls.append(ref)


def grammar_for(extension_or_lang: str) -> str:
    """The grammar for a file extension (`.tsx`) or a `<script lang="ts">` value."""
    key = extension_or_lang if extension_or_lang.startswith(".") else f".{extension_or_lang or 'js'}"
    return _GRAMMAR_BY_EXTENSION.get(key, "javascript")


def walk_script(facts: FileFacts, tree: Tree, language: str, scope: tuple[str, str]) -> ScriptWalker:
    """Extracts a parsed script into facts, with top-level definitions placed
    under scope (a node id and its qualname). Shared with the Vue extractor,
    whose `<script>` blocks are plain TypeScript/JavaScript."""
    imports = _Imports(tree.root_node)
    facts.imports.extend(imports.specs)
    facts.reexports.extend(imports.reexports)
    walker = ScriptWalker(facts, language, imports)
    walker.visit(tree.root_node, scope, None)
    return walker


class TypeScriptLanguage(Language):
    name = "typescript"
    extensions = tuple(_GRAMMAR_BY_EXTENSION)
    grammars = tuple(set(_GRAMMAR_BY_EXTENSION.values()))

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        grammar = grammar_for(posixpath.splitext(rel_file)[1])
        language = "javascript" if grammar == "javascript" else "typescript"
        tree = ts.parse(grammar, source)
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, language, tree)
        walk_script(facts, tree, language, (rel_file, ""))
        return facts

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        """Relative specs, plus `paths`/`baseUrl` aliases from the nearest
        tsconfig.json or jsconfig.json (Next.js's `@/components/...`), plus
        packages of the repo's own workspace (a monorepo importing
        `zod/v4`). Any other bare spec is an npm package."""
        if spec.startswith("."):
            return _module_at(posixpath.join(posixpath.dirname(from_file), spec), index)
        found = index.nearest_config(
            posixpath.dirname(from_file), ("tsconfig.json", "jsconfig.json"), lambda p: _load_aliases(p, index.root)
        )
        aliased = self._through_aliases(spec, found[1], index) if found is not None else []
        return aliased or _workspace_module(spec, index)

    @staticmethod
    def _through_aliases(spec: str, aliases: _Aliases, index: RepoIndex) -> list[str]:
        for pattern, targets in aliases.paths.items():
            prefix, star, suffix = pattern.partition("*")
            if star and spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix + suffix):
                matched = spec[len(prefix) : len(spec) - len(suffix)]
            elif not star and spec == pattern:
                matched = ""
            else:
                continue
            for target in targets:
                hit = _module_at(posixpath.join(aliases.base, target.replace("*", matched)), index)
                if hit:
                    return hit
        return _module_at(posixpath.join(aliases.base, spec), index) if aliases.has_base_url else []


def _manifest(package_json: Path) -> dict | None:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("name"), str) else None


def _export_targets(entry: object) -> list[str]:
    """Every path an `exports` entry can point to, across conditions
    (`import`, `types`, a custom source condition...), in order."""
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, dict):
        return [t for value in entry.values() for t in _export_targets(value)]
    if isinstance(entry, list):
        return [t for value in entry for t in _export_targets(value)]
    return []


def _workspace_module(spec: str, index: RepoIndex) -> list[str]:
    """A monorepo importing one of its own packages by name. The package's
    `exports` (or `source`/`main`/...) usually point at build output that
    isn't in the repo, so every target is tried and the first that's a real
    source file wins, with `src/` as the conventional fallback."""
    packages: dict[str, tuple[str, dict]] | None = index.cache.get("npm_workspace")
    if packages is None:
        packages = {}
        for module in index.modules:
            found = index.nearest_config(posixpath.dirname(module), ("package.json",), _manifest)
            if found is not None:
                packages.setdefault(found[1]["name"], found)
        index.cache["npm_workspace"] = packages
    parts = spec.split("/")
    name_length = 2 if spec.startswith("@") else 1
    name, subpath = "/".join(parts[:name_length]), "/".join(parts[name_length:])
    if name not in packages:
        return []
    package_dir, manifest = packages[name]
    exports = manifest.get("exports")
    entry = exports.get(f"./{subpath}" if subpath else ".") if isinstance(exports, dict) else None
    targets = _export_targets(entry) if subpath or entry is not None else []
    if not subpath:
        targets += [manifest[f] for f in ("source", "module", "main", "types") if isinstance(manifest.get(f), str)]
        targets += ["src/index", "index"]
    else:
        targets += [f"src/{subpath}", subpath]
    for target in targets:
        hit = _module_at(posixpath.join(package_dir, target), index)
        if hit:
            return hit
    return []


@dataclass
class _Aliases:
    base: str  # repo-relative directory that `paths` targets resolve against
    paths: dict[str, list[str]]
    has_base_url: bool


def _load_aliases(config: Path, root: Path, depth: int = 0) -> _Aliases | None:
    """Path aliases from a tsconfig/jsconfig, following relative `extends`.
    A config that sets neither `paths` nor `baseUrl` inherits its parent's."""
    try:
        data = json5.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    options = data.get("compilerOptions") or {}
    base_url, paths = options.get("baseUrl"), options.get("paths")
    if base_url is None and paths is None:
        extends = data.get("extends")
        for parent in [extends] if isinstance(extends, str) else extends or []:
            parent_path = config.parent / parent
            if not parent_path.suffix:
                parent_path = parent_path.with_suffix(".json")
            if parent.startswith(".") and depth < 10 and parent_path.is_file():
                return _load_aliases(parent_path, root, depth + 1)
        return None
    # `paths` resolve against baseUrl when it's set, else against the config's own directory.
    base = Path(os.path.relpath(config.parent / (base_url or "."), root)).as_posix()
    return _Aliases("" if base == "." else base, paths or {}, base_url is not None)


def _module_at(path: str, index: RepoIndex) -> list[str]:
    """The file an import of `path` loads: the path itself, with a source
    extension added, or its index file."""
    base = posixpath.normpath(path)
    stem, ext = posixpath.splitext(base)
    candidates = [base] + [base + e for e in _RESOLVE_EXTENSIONS]
    candidates += [posixpath.join(base, "index" + e) for e in _RESOLVE_EXTENSIONS]
    if ext in (".js", ".jsx", ".mjs", ".cjs"):
        # ESM TypeScript imports name the compiled .js file, not the .ts source.
        candidates += [stem + e for e in (".ts", ".tsx", ".mts", ".cts")]
    return next(([c] for c in candidates if c in index.modules), [])
