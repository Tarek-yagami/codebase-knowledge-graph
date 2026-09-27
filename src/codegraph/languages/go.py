"""Go extraction. Go has no classes, so struct, interface and other named
types become "class" nodes, embedded fields count as inheritance (their
methods are promoted), and methods are attached to their receiver type
even when it's declared in another file of the same package.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from tree_sitter import Node as SyntaxNode

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex

_VERSION_SUFFIX = re.compile(r"^v\d+$")


def _default_alias(path: str) -> str:
    """The package name an import is referred to by when it has no explicit
    alias. By convention it's the last path element, skipping a `/v2`-style
    major version suffix."""
    parts = path.split("/")
    if len(parts) > 1 and _VERSION_SUFFIX.match(parts[-1]):
        return parts[-2]
    return parts[-1]


def _type_name(node: SyntaxNode | None) -> str | None:
    """The bare type name behind `T`, `*T`, `T[K]` and `*T[K]`."""
    while node is not None and node.type in ("pointer_type", "generic_type"):
        node = node.child_by_field_name("type") or (node.named_children[0] if node.named_children else None)
    return ts.text(node) if node is not None and node.type == "type_identifier" else None


class _Walker:
    def __init__(self, facts: FileFacts, source_root: SyntaxNode):
        self.facts = facts
        self.module_id = facts.module_id
        self.aliases: dict[str, str] = {}  # package alias -> import path
        for decl in source_root.named_children:
            if decl.type == "import_declaration":
                for spec in _import_specs(decl):
                    path = ts.text(spec.child_by_field_name("path")).strip('"`')
                    facts.imports.append(path)
                    name = spec.child_by_field_name("name")
                    alias = ts.text(name) if name is not None else _default_alias(path)
                    if alias not in ("_", "."):
                        self.aliases[alias] = path

    def visit(self, root: SyntaxNode) -> None:
        for decl in root.named_children:
            if decl.type == "type_declaration":
                for spec in decl.named_children:
                    if spec.type == "type_spec":
                        self._type(spec, decl)
            elif decl.type == "function_declaration":
                name = ts.text(decl.child_by_field_name("name"))
                fn_id = ts.add_definition(self.facts, self.module_id, name, "function", "go", decl)
                self._record_calls(fn_id, decl.child_by_field_name("body"), None, None)
            elif decl.type == "method_declaration":
                self._method(decl)

    def _type(self, spec: SyntaxNode, decl: SyntaxNode) -> None:
        name = ts.text(spec.child_by_field_name("name"))
        # A lone type in its declaration keeps its doc comment above the `type` keyword.
        anchor = decl if len(decl.named_children) == 1 else spec
        type_id = ts.add_definition(self.facts, self.module_id, name, "class", "go", spec, anchor)
        body = spec.child_by_field_name("type")
        if body is None:
            return
        if body.type == "struct_type":
            fields = next((c for c in body.named_children if c.type == "field_declaration_list"), None)
            embedded = [
                f.child_by_field_name("type")
                for f in (fields.named_children if fields is not None else [])
                if f.type == "field_declaration" and f.child_by_field_name("name") is None
            ]
        elif body.type == "interface_type":
            embedded = [c.named_children[0] for c in body.named_children if c.type == "type_elem" and c.named_children]
        else:
            embedded = []
        for t in embedded:
            ref = self._type_ref(type_id, t)
            if ref is not None:
                self.facts.bases.append(ref)

    def _type_ref(self, src: str, node: SyntaxNode | None) -> Ref | None:
        while node is not None and node.type == "pointer_type":
            node = node.named_children[0] if node.named_children else None
        if node is None:
            return None
        if node.type == "qualified_type":
            pkg = ts.text(node.child_by_field_name("package"))
            if pkg in self.aliases:
                return Ref(src, ts.text(node.child_by_field_name("name")), via_import=self.aliases[pkg])
            return None
        name = _type_name(node)
        return Ref(src, name) if name else None

    def _method(self, decl: SyntaxNode) -> None:
        receiver = decl.child_by_field_name("receiver")
        params = receiver.named_children if receiver is not None else []
        param = next((p for p in params if p.type == "parameter_declaration"), None)
        type_name = _type_name(param.child_by_field_name("type")) if param is not None else None
        if param is None or type_name is None:
            return
        var = param.child_by_field_name("name")
        name = ts.text(decl.child_by_field_name("name"))
        # No "defines" edge yet: the receiver type may be in another file,
        # so parser.py attaches the method once every file is known.
        method_id = ts.add_definition(self.facts, None, f"{type_name}.{name}", "function", "go", decl)
        self.facts.owners.append((method_id, type_name))
        receiver_var = ts.text(var) if var is not None else None
        self._record_calls(method_id, decl.child_by_field_name("body"), receiver_var, type_name)

    def _record_calls(
        self, fn_id: str, body: SyntaxNode | None, receiver_var: str | None, receiver_type: str | None
    ) -> None:
        """`f()`, `pkg.F()` and `recv.M()` are recorded; calls on any other
        value are not, since their type isn't known without type checking."""
        for n in ts.descendants(body):
            if n.type != "call_expression":
                continue
            callee = n.child_by_field_name("function")
            if callee is None:
                continue
            if callee.type == "identifier":
                self.facts.calls.append(Ref(fn_id, ts.text(callee)))
            elif callee.type == "selector_expression":
                operand = callee.child_by_field_name("operand")
                field = ts.text(callee.child_by_field_name("field"))
                if operand is None or operand.type != "identifier":
                    continue
                target = ts.text(operand)
                if receiver_var is not None and target == receiver_var:
                    self.facts.calls.append(Ref(fn_id, field, receiver=receiver_type))
                elif target in self.aliases:
                    self.facts.calls.append(Ref(fn_id, field, via_import=self.aliases[target]))


def _import_specs(decl: SyntaxNode) -> list[SyntaxNode]:
    specs = []
    for child in decl.named_children:
        if child.type == "import_spec":
            specs.append(child)
        elif child.type == "import_spec_list":
            specs.extend(c for c in child.named_children if c.type == "import_spec")
    return specs


class GoLanguage(Language):
    name = "go"
    extensions = (".go",)
    grammars = ("go",)
    directory_is_scope = True

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        tree = ts.parse("go", source)
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, "go", tree)
        walker = _Walker(facts, tree.root_node)
        walker.visit(tree.root_node)
        return facts

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        """Go imports a whole package, meaning every file in one directory.
        The import path maps to a directory through the module path declared
        in the nearest go.mod above the importing file."""
        found = index.nearest_config(posixpath.dirname(from_file), ("go.mod",), _module_path)
        if found is None:
            return []
        mod_dir, mod_path = found
        if spec != mod_path and not spec.startswith(mod_path + "/"):
            return []
        target = posixpath.normpath(posixpath.join(mod_dir, spec[len(mod_path) :].lstrip("/")))
        target = "" if target == "." else target
        return [m for m in index.by_dir.get(target, []) if m.endswith(".go")]


def _module_path(go_mod: Path) -> str | None:
    match = re.search(r"^module\s+(\S+)", go_mod.read_text(encoding="utf-8", errors="replace"), re.M)
    return match.group(1) if match else None
