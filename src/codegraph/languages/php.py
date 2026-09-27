"""PHP extraction, with Laravel in mind. Every class reference is expanded to
its fully qualified name through the file's namespace and `use` statements,
then mapped to a file through composer.json's PSR-4 autoload rules, the
same way PHP itself finds the class at runtime.
"""

from __future__ import annotations

import json
import posixpath
from pathlib import Path

from tree_sitter import Node as SyntaxNode

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex

_CLASS_TYPES = {"class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"}
_FUNCTION_TYPES = {"function_definition", "method_declaration"}
_NAME_TYPES = {"name", "qualified_name"}
# Definitions get their own node, so their calls aren't credited to the enclosing scope.
_OWN_NODE_TYPES = frozenset(_CLASS_TYPES | _FUNCTION_TYPES)


class _Names:
    """Expands class names the way PHP does: `\\Foo` is absolute, a name
    starting with a `use` alias expands through it, and anything else is
    relative to the current namespace."""

    def __init__(self) -> None:
        self.namespace = ""
        self.aliases: dict[str, str] = {}  # alias -> fully qualified name

    def qualify(self, name: str) -> str:
        if name.startswith("\\"):
            return name[1:]
        head, sep, rest = name.partition("\\")
        if head in self.aliases:
            return self.aliases[head] + sep + rest
        return f"{self.namespace}\\{name}" if self.namespace else name

    def ref(self, src: str, name_node: SyntaxNode) -> Ref:
        fqcn = self.qualify(ts.text(name_node))
        return Ref(src, fqcn.rsplit("\\", 1)[-1], via_import=fqcn)

    def add_use(self, declaration: SyntaxNode, facts: FileFacts) -> None:
        if any(c.type in ("function", "const") for c in declaration.children):
            return  # `use function` / `use const` import functions, not classes
        group = declaration.child_by_field_name("body")
        prefix = next((ts.text(c) for c in declaration.named_children if c.type == "namespace_name"), "")
        clauses = group.named_children if group is not None else declaration.named_children
        for clause in clauses:
            if clause.type != "namespace_use_clause":
                continue
            name = next((c for c in clause.named_children if c.type in _NAME_TYPES), None)
            if name is None:
                continue
            fqcn = f"{prefix}\\{ts.text(name)}" if prefix else ts.text(name).lstrip("\\")
            alias = clause.child_by_field_name("alias")
            self.aliases[ts.text(alias) if alias is not None else fqcn.rsplit("\\", 1)[-1]] = fqcn
            facts.imports.append(fqcn)


class _Walker:
    def __init__(self, facts: FileFacts):
        self.facts = facts
        self.names = _Names()

    def visit(self, root: SyntaxNode) -> None:
        for node in root.named_children:
            if node.type == "namespace_definition":
                self.names.namespace = ts.text(node.child_by_field_name("name"))
                body = node.child_by_field_name("body")
                if body is not None:  # block form: `namespace Foo { ... }`
                    self.visit(body)
            elif node.type == "namespace_use_declaration":
                self.names.add_use(node, self.facts)
            elif node.type in _CLASS_TYPES:
                self._class(node)
            elif node.type == "function_definition":
                self._function(node, self.facts.module_id, "", None, None)
        # Script-style code at file level, like Laravel's routes/web.php, is
        # where controllers get wired up, so its calls belong to the module.
        self._record_calls(self.facts.module_id, root, None, None)

    def _class(self, node: SyntaxNode) -> None:
        name = ts.text(node.child_by_field_name("name"))
        class_id = ts.add_definition(self.facts, self.facts.module_id, name, "class", "php", node)
        parent_ref = None
        for clause in node.named_children:
            if clause.type in ("base_clause", "class_interface_clause"):
                for base in clause.named_children:
                    if base.type in _NAME_TYPES:
                        ref = self.names.ref(class_id, base)
                        self.facts.bases.append(ref)
                        if clause.type == "base_clause" and parent_ref is None:
                            parent_ref = ref
        body = node.child_by_field_name("body")
        for member in body.named_children if body is not None else []:
            if member.type == "use_declaration":  # traits mix their methods in
                for trait in member.named_children:
                    if trait.type in _NAME_TYPES:
                        self.facts.bases.append(self.names.ref(class_id, trait))
            elif member.type == "method_declaration":
                self._function(member, class_id, name, class_id, parent_ref)

    def _function(
        self, node: SyntaxNode, parent_id: str, parent_qual: str, class_id: str | None, parent_ref: Ref | None
    ) -> None:
        body = node.child_by_field_name("body")
        if body is None:  # abstract or interface method
            return
        name = ts.text(node.child_by_field_name("name"))
        qual = f"{parent_qual}.{name}" if parent_qual else name
        fn_id = ts.add_definition(self.facts, parent_id, qual, "function", "php", node)
        self._record_calls(fn_id, body, class_id, parent_ref)

    def _record_calls(self, src: str, body: SyntaxNode, class_id: str | None, parent_ref: Ref | None) -> None:
        """`$this->m()`, `self::m()`, `parent::m()`, `Foo::m()`, `new Foo`,
        `f()` and `[Foo::class, 'm']` callables are recorded. Calls on any
        other object aren't, since its class isn't known statically."""
        calls = self.facts.calls
        for n in ts.descendants(body, prune=_OWN_NODE_TYPES):
            t = n.type
            if t in ("member_call_expression", "nullsafe_member_call_expression"):
                obj = n.child_by_field_name("object")
                if class_id is not None and ts.text(obj) == "$this":
                    calls.append(Ref(src, ts.text(n.child_by_field_name("name")), receiver=class_id))
            elif t == "scoped_call_expression":
                self._static_call(src, n, class_id, parent_ref)
            elif t == "object_creation_expression":
                cls = next((c for c in n.named_children if c.type in _NAME_TYPES), None)
                if cls is not None:
                    calls.append(self.names.ref(src, cls))
            elif t == "function_call_expression":
                fn = n.child_by_field_name("function")
                if fn is not None and fn.type == "name":
                    calls.append(Ref(src, ts.text(fn)))
            elif t == "array_creation_expression":
                self._callable_array(src, n)

    def _static_call(self, src: str, call: SyntaxNode, class_id: str | None, parent_ref: Ref | None) -> None:
        scope = call.child_by_field_name("scope")
        method = ts.text(call.child_by_field_name("name"))
        if scope is None:
            return
        if scope.type == "relative_scope":
            keyword = ts.text(scope).lower()
            if keyword in ("self", "static") and class_id is not None:
                self.facts.calls.append(Ref(src, method, receiver=class_id))
            elif keyword == "parent" and parent_ref is not None:
                self.facts.calls.append(
                    Ref(src, method, receiver=parent_ref.name, receiver_import=parent_ref.via_import)
                )
        elif scope.type in _NAME_TYPES:
            cls = self.names.ref(src, scope)
            self.facts.calls.append(Ref(src, method, receiver=cls.name, receiver_import=cls.via_import))

    def _callable_array(self, src: str, array: SyntaxNode) -> None:
        """`[UserController::class, 'index']`, the way Laravel routes, events
        and jobs point at a method."""
        elements = [e.named_children[0] for e in array.named_children if e.named_children]
        if len(elements) != 2 or elements[0].type != "class_constant_access_expression":
            return
        parts = elements[0].named_children
        if len(parts) != 2 or ts.text(parts[1]).lower() != "class" or elements[1].type != "string":
            return
        cls = self.names.ref(src, parts[0])
        method = ts.text(elements[1]).strip("'\"")
        self.facts.calls.append(Ref(src, method, receiver=cls.name, receiver_import=cls.via_import))


def _psr4(composer: Path) -> dict[str, list[str]] | None:
    """composer.json's PSR-4 namespace prefix -> directories, or None when
    it declares none (so a composer.json further up is tried instead)."""
    try:
        data = json.loads(composer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mapping: dict[str, list[str]] = {}
    for section in ("autoload", "autoload-dev"):
        for prefix, dirs in (data.get(section) or {}).get("psr-4", {}).items():
            mapping.setdefault(prefix, []).extend([dirs] if isinstance(dirs, str) else dirs)
    return mapping or None


class PhpLanguage(Language):
    name = "php"
    extensions = (".php",)
    grammars = ("php",)

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        tree = ts.parse("php", source)
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, "php", tree)
        _Walker(facts).visit(tree.root_node)
        return facts

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        """Maps a fully qualified class name to its file. With composer.json's
        PSR-4 rules when the project has them, and anything outside those
        prefixes is a vendor package. Without composer, falls back to the
        one-class-per-file convention and matches on the file name alone."""
        found = index.nearest_config(posixpath.dirname(from_file), ("composer.json",), _psr4)
        if found is None:
            basename = spec.rsplit("\\", 1)[-1] + ".php"
            matches = [m for m in index.modules if posixpath.basename(m) == basename]
            return matches if len(matches) == 1 else []
        composer_dir, mapping = found
        for prefix in sorted(mapping, key=len, reverse=True):
            if not spec.startswith(prefix):
                continue
            relative = spec[len(prefix) :].replace("\\", "/") + ".php"
            for directory in mapping[prefix]:
                candidate = posixpath.normpath(posixpath.join(composer_dir, directory, relative))
                if candidate in index.modules:
                    return [candidate]
        return []
