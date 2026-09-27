"""Java extraction. Classes resolve through imports and the package (files in
one package see each other without importing), and because Java declares
every variable's type, a call like `repo.findById()` resolves to the method
on the declared type of `repo`, not just calls on `this`.
"""

from __future__ import annotations

from tree_sitter import Node as SyntaxNode

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex

_CLASS_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
}
_METHOD_TYPES = {"method_declaration", "constructor_declaration", "compact_constructor_declaration"}
_OWN_NODE_TYPES = frozenset(_CLASS_TYPES | _METHOD_TYPES)
# Declarations whose `type` field names the type of the variable they declare.
_TYPED_DECLARATIONS = {
    "local_variable_declaration",
    "field_declaration",
    "formal_parameter",
    "catch_formal_parameter",
    "resource",
    "enhanced_for_statement",
}


def _type_name(node: SyntaxNode | None) -> str | None:
    """`Owner`, `List<Owner>` -> `List`, `a.b.Owner` -> `Owner`; None for
    primitives, arrays and `var`, which name no class in the repo."""
    if node is None:
        return None
    if node.type == "type_identifier":
        name = ts.text(node)
        return None if name == "var" else name
    if node.type == "generic_type":
        return _type_name(node.named_children[0] if node.named_children else None)
    if node.type == "scoped_type_identifier":
        return ts.text(node).rsplit(".", 1)[-1]
    return None


def _declared_names(declaration: SyntaxNode) -> list[str]:
    name = declaration.child_by_field_name("name")
    if name is not None:
        return [ts.text(name)]
    return [
        ts.text(d.child_by_field_name("name"))
        for d in declaration.named_children
        if d.type == "variable_declarator" and d.child_by_field_name("name") is not None
    ]


def variable_types(scope: SyntaxNode | None) -> dict[str, str]:
    """name -> declared type name for every typed variable declared in
    scope. Block scoping is ignored, so a name reused with another type in
    a sibling block keeps the last one."""
    types: dict[str, str] = {}
    for n in ts.descendants(scope, prune=_OWN_NODE_TYPES):
        if n.type not in _TYPED_DECLARATIONS:
            continue
        type_name = _type_name(n.child_by_field_name("type"))
        if type_name is None and n.type == "local_variable_declaration":
            # `var owner = new Owner();` takes the type of what it's assigned.
            declarator = n.child_by_field_name("declarator")
            value = declarator.child_by_field_name("value") if declarator is not None else None
            if value is not None and value.type == "object_creation_expression":
                type_name = _type_name(value.child_by_field_name("type"))
        if type_name is not None:
            for name in _declared_names(n):
                types[name] = type_name
    return types


class _Walker:
    def __init__(self, facts: FileFacts, root: SyntaxNode):
        self.facts = facts
        self.imports: dict[str, str] = {}  # simple name -> fully qualified import
        for decl in root.named_children:
            if decl.type != "import_declaration":
                continue
            path = next((c for c in decl.named_children if c.type in ("scoped_identifier", "identifier")), None)
            spec = ts.text(path)
            if any(c.type == "asterisk" for c in decl.named_children):
                facts.open_imports.append(spec)
            else:
                self.imports[spec.rsplit(".", 1)[-1]] = spec
            facts.imports.append(spec)

    def class_ref(self, src: str, name: str) -> Ref:
        return Ref(src, name, via_import=self.imports.get(name))

    def visit(self, body: SyntaxNode | None, parent_id: str, parent_qual: str, fields: dict[str, str]) -> None:
        for node in body.named_children if body is not None else []:
            if node.type in _CLASS_TYPES:
                self._class(node, parent_id, parent_qual, fields)

    def _class(self, node: SyntaxNode, parent_id: str, parent_qual: str, outer_fields: dict[str, str]) -> None:
        name = ts.text(node.child_by_field_name("name"))
        qual = f"{parent_qual}.{name}" if parent_qual else name
        class_id = ts.add_definition(self.facts, parent_id, qual, "class", "java", node)
        superclass = None
        for clause in node.named_children:
            if clause.type in ("superclass", "super_interfaces", "extends_interfaces"):
                for t in ts.descendants(clause):
                    if t.type == "type_identifier" and t.parent is not None and t.parent.type != "type_arguments":
                        ref = self.class_ref(class_id, ts.text(t))
                        self.facts.bases.append(ref)
                        if clause.type == "superclass":
                            superclass = ref
        body = node.child_by_field_name("body")
        fields = {**outer_fields, **variable_types_of_fields(body)}
        for member in body.named_children if body is not None else []:
            if member.type in _METHOD_TYPES:
                self._method(member, class_id, qual, fields, superclass)
        self.visit(body, class_id, qual, fields)

    def _method(
        self, node: SyntaxNode, class_id: str, class_qual: str, fields: dict[str, str], superclass: Ref | None
    ) -> None:
        name = node.child_by_field_name("name")
        method_id = ts.add_definition(self.facts, class_id, f"{class_qual}.{ts.text(name)}", "function", "java", node)
        body = node.child_by_field_name("body")
        if body is None:  # abstract and interface methods are still what callers call
            return
        types = {**fields, **variable_types(node.child_by_field_name("parameters")), **variable_types(body)}
        self._record_calls(method_id, body, class_id, types, superclass)

    def _record_calls(
        self, src: str, body: SyntaxNode, class_id: str, types: dict[str, str], superclass: Ref | None
    ) -> None:
        """`m()` and `this.m()` on the enclosing class, `super.m()` on its
        superclass, `x.m()` on the declared type of `x`, `Type.m()` static
        calls, and `new Type()`. A receiver whose type isn't declared, like
        a chained call's result, is skipped."""
        calls = self.facts.calls
        for n in ts.descendants(body, prune=_OWN_NODE_TYPES):
            if n.type == "object_creation_expression":
                type_name = _type_name(n.child_by_field_name("type"))
                if type_name is not None:
                    calls.append(self.class_ref(src, type_name))
                continue
            if n.type != "method_invocation":
                continue
            method = ts.text(n.child_by_field_name("name"))
            obj = n.child_by_field_name("object")
            if obj is None:
                if method in self.imports:  # a static import: `import static a.Util.trim;`
                    owner = self.imports[method].rsplit(".", 2)
                    calls.append(Ref(src, method, receiver=owner[-2], receiver_import=".".join(owner[:-1])))
                else:
                    calls.append(Ref(src, method, receiver=class_id, bare_fallback=True))
            elif obj.type == "this":
                calls.append(Ref(src, method, receiver=class_id))
            elif obj.type == "super" and superclass is not None:
                calls.append(Ref(src, method, receiver=superclass.name, receiver_import=superclass.via_import))
            else:
                receiver = self._receiver_type(obj, types)
                if receiver is not None:
                    calls.append(Ref(src, method, receiver=receiver, receiver_import=self.imports.get(receiver)))

    def _receiver_type(self, obj: SyntaxNode, types: dict[str, str]) -> str | None:
        if obj.type == "identifier":
            name = ts.text(obj)
            # Not a known variable and capitalized: a static call on a class.
            return types.get(name) or (name if name[:1].isupper() else None)
        if obj.type == "field_access" and ts.text(obj.child_by_field_name("object")) == "this":
            return types.get(ts.text(obj.child_by_field_name("field")))
        return None


def variable_types_of_fields(body: SyntaxNode | None) -> dict[str, str]:
    """Field name -> declared type for a class body's own fields."""
    types: dict[str, str] = {}
    for member in body.named_children if body is not None else []:
        if member.type == "field_declaration":
            type_name = _type_name(member.child_by_field_name("type"))
            if type_name is not None:
                types.update(dict.fromkeys(_declared_names(member), type_name))
    return types


class JavaLanguage(Language):
    name = "java"
    extensions = (".java",)
    grammars = ("java",)

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        tree = ts.parse("java", source)
        root = tree.root_node
        package = next((c for c in root.named_children if c.type == "package_declaration"), None)
        package_name = ts.text(next((c for c in package.named_children), None)) if package is not None else ""
        facts = FileFacts(module_id=rel_file, package=package_name)
        facts.nodes[rel_file] = ts.module_node(rel_file, "java", tree)
        _Walker(facts, root).visit(root, rel_file, "", {})
        return facts

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        return resolve_jvm_import(spec, index)


def resolve_jvm_import(spec: str, index: RepoIndex) -> list[str]:
    """Java and Kotlin imports. A package (`a.b`, from `import a.b.*`) maps
    to all its files. A class (`a.b.Owner`) or static member
    (`a.b.Util.trim`) maps to the file named after the class, as Java
    requires, or else the whole package, since Kotlin files can hold many
    classes. Either language can import the other's classes."""
    if spec in index.packages:
        return index.packages[spec]
    parts = spec.split(".")
    for split in (len(parts) - 1, len(parts) - 2):
        files = index.packages.get(".".join(parts[:split]), [])
        if files:
            class_name = parts[split]
            named = [f for f in files if f.rsplit("/", 1)[-1].rsplit(".", 1)[0] == class_name]
            return named or files
    return []
