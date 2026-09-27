"""Fallback extraction for any language tree-sitter-language-pack ships a
tags query for (Ruby, Swift, Kotlin, C, C++, Dart, Scala, ...). The tags
query marks definitions, base types and call references, so this gets
classes, functions and methods with their nesting, inheritance and calls.
Call shapes a query doesn't mark are found from node shapes instead. It
doesn't get imports, which need a dedicated extractor per language.
"""

from __future__ import annotations

import re
from functools import cache

import tree_sitter_language_pack as tslp
from tree_sitter import Node as SyntaxNode
from tree_sitter import Query, QueryCursor

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref

_CLASS_TAGS = {"class", "interface", "struct", "enum", "trait", "module", "type", "union"}
_FUNCTION_TAGS = {"function", "method", "constructor", "macro"}
_SELF_WORDS = {"this", "self", "$this", "@"}
# Fields that hold the receiver of a method call across common grammars.
_RECEIVER_FIELDS = ("object", "receiver", "scope", "operand", "value", "argument")
_CALL_TAGS = ("reference.call", "reference.send")  # C#'s query calls them sends
# A function declared without a body (a C prototype) isn't a definition.
_PROTOTYPES = {"declaration", "field_declaration"}
_CALL_NODE_TYPES = {
    "call_expression",
    "call",
    "function_call",
    "function_call_expression",
    "method_invocation",
    "invocation_expression",
}


@cache
def tags_query(grammar: str) -> Query | None:
    source = tslp.get_tags_query(grammar)
    if not source:
        return None
    try:
        return Query(tslp.get_language(grammar), source)
    except Exception:
        # Some bundled queries use syntax this binding version can't compile.
        return None


def _impl_owner(syntax: SyntaxNode) -> str | None:
    """The type a method belongs to when it's declared in a block that
    isn't itself a definition: Rust `impl Point { ... }`, Swift/Kotlin
    `extension Point { ... }`."""
    node = syntax.parent
    while node is not None:
        if "impl" in node.type or "extension" in node.type:
            fields = (node.child_by_field_name(f) for f in ("type", "extended_type", "name"))
            target = next((f for f in fields if f is not None), None)
            if target is None:
                return None
            return re.split(r"::|\.", ts.text(target).split("<")[0].strip())[-1] or None
        node = node.parent
    return None


class _FileWalker:
    """Turns one file's tag captures into definitions and calls."""

    def __init__(self, facts: FileFacts, language: str):
        self.facts = facts
        self.language = language
        self.defined: dict[tuple[int, int], tuple[str, str]] = {}  # syntax span -> (node id, kind)
        self.syntax: dict[str, SyntaxNode] = {}  # node id -> its syntax node
        self.impl_owner: dict[str, str] = {}  # method id -> owning type name
        self._scope_types: dict[str, dict[str, str]] = {}

    def add_definitions(self, definitions: list[tuple[SyntaxNode, str, str]]) -> None:
        # Outer definitions first, so each one's parent already exists. The
        # same node can match two patterns (e.g. both method and function).
        definitions.sort(key=lambda d: (d[0].start_byte, -d[0].end_byte))
        stack: list[tuple[SyntaxNode, str, str]] = []  # (syntax node, node id, qualname)
        for syntax, kind, name in definitions:
            span = (syntax.start_byte, syntax.end_byte)
            if span in self.defined:
                continue
            while stack and stack[-1][0].end_byte < syntax.end_byte:
                stack.pop()
            owner = _impl_owner(syntax) if not stack and kind == "function" else None
            if owner is not None:
                # The type may be declared in another file, so parser.py attaches it.
                qual = f"{owner}.{name}"
                node_id = ts.add_definition(self.facts, None, qual, kind, self.language, syntax)
                self.facts.owners.append((node_id, owner))
                self.impl_owner[node_id] = owner
            else:
                parent_id, parent_qual = (stack[-1][1], stack[-1][2]) if stack else (self.facts.module_id, "")
                qual = f"{parent_qual}.{name}" if parent_qual else name
                node_id = ts.add_definition(self.facts, parent_id, qual, kind, self.language, syntax)
            self.defined[span] = (node_id, kind)
            self.syntax[node_id] = syntax
            stack.append((syntax, node_id, qual))

    def _enclosing(self, node: SyntaxNode) -> tuple[str | None, str | None]:
        """The innermost function around node, and the class (or impl
        type) it belongs to."""
        function = owner = None
        current = node.parent
        while current is not None and owner is None:
            found = self.defined.get((current.start_byte, current.end_byte))
            if found is not None:
                node_id, kind = found
                if kind == "function" and function is None:
                    function = node_id
                    owner = self.impl_owner.get(node_id)
                elif kind == "class":
                    owner = node_id
            current = current.parent
        return function, owner

    def add_bases(self, implementations: list[tuple[SyntaxNode, str]]) -> None:
        """`reference.implementation` captures (`class A : Base`) as base
        classes of the definition they sit in."""
        for node, base in implementations:
            current: SyntaxNode | None = node
            while current is not None:
                found = self.defined.get((current.start_byte, current.end_byte))
                if found is not None and found[1] == "class":
                    self.facts.bases.append(Ref(found[0], base))
                    break
                current = current.parent

    def add_calls(self, calls: list[tuple[SyntaxNode, str, str | None]]) -> None:
        """Only receiver-less calls (`f()`) and self calls (`this.f()`) are
        kept. `obj.f()` is also reported as a call to `f`, and resolving that
        by name alone would guess wrong whenever two types share a method name."""
        for call, name, receiver in calls:
            function, owner = self._enclosing(call)
            if function is None:
                continue
            head = re.split(r"\.|->|::", receiver)[0] if receiver is not None else ""
            if receiver is None:
                self.facts.calls.append(Ref(function, name, receiver=owner, bare_fallback=True))
            elif head in _SELF_WORDS:
                if owner is not None:
                    self.facts.calls.append(Ref(function, name, receiver=owner))
            elif head[:1].isupper() and head.isidentifier():
                # A capitalized receiver names a type: `Node::new()`, `Foo.create()`.
                self.facts.calls.append(Ref(function, name, receiver=head))
            else:
                receiver_type = self._declared_type(receiver, function, owner)
                if receiver_type is not None:
                    self.facts.calls.append(Ref(function, name, receiver=receiver_type))

    def _declared_type(self, receiver: str, function: str, owner: str | None) -> str | None:
        """The declared type of a call's receiver: a parameter or local of
        the enclosing function (`repo.get()`), or a field of its class
        (`_db.save()`, `this.db.save()`)."""
        parts = re.split(r"\.|->", receiver)
        if len(parts) == 2 and parts[0] in _SELF_WORDS and owner is not None:
            return self._types_of(owner).get(parts[1])
        if len(parts) != 1:
            return None
        found = self._types_of(function).get(parts[0])
        return found if found is not None or owner is None else self._types_of(owner).get(parts[0])

    def _types_of(self, node_id: str) -> dict[str, str]:
        if node_id not in self._scope_types:
            syntax = self.syntax.get(node_id)
            self._scope_types[node_id] = {} if syntax is None else _declared_types(syntax, self.defined)
        return self._scope_types[node_id]


def _declared_types(scope: SyntaxNode, defined: dict[tuple[int, int], tuple[str, str]]) -> dict[str, str]:
    """name -> type name for the variables declared directly in scope (not in
    nested definitions). Grammars broadly mark a declaration's type with a
    `type` field and its variable with `name`, `pattern` or `declarator`,
    which is what makes this work without per-language code."""
    types: dict[str, str] = {}
    stack = list(scope.named_children)
    while stack:
        n = stack.pop()
        if (n.start_byte, n.end_byte) in defined:
            continue  # a nested function or class has its own scope
        stack.extend(n.named_children)
        type_node = n.child_by_field_name("type")
        type_name = _type_name(type_node) if type_node is not None else None
        if type_name is None:
            type_name = _constructed_type(n.child_by_field_name("value"))
        if type_name is None:
            continue
        for name in _declared_names(n):
            types[name] = type_name
    return types


def _type_name(node: SyntaxNode) -> str | None:
    """`Foo`, `&mut Foo`, `Foo<T>`, `a::b::Foo`, `Foo*` -> `Foo`."""
    text = re.sub(r"(const|mut|dyn|impl)|[&*?\[\]\s]", "", ts.text(node).split("<")[0])
    last = re.split(r"\.|::", text)[-1]
    return last if last.isidentifier() and last not in ("var", "let", "auto") else None


def _constructed_type(value: SyntaxNode | None) -> str | None:
    """The type a declaration without one gets from its initializer:
    `new Foo()`, `Foo::new()`, `Foo()`."""
    if value is None:
        return None
    callee = value.child_by_field_name("type") or value.child_by_field_name("function")
    if callee is None:
        return None
    head = re.split(r"\.|::", ts.text(callee))[0]
    return head if head[:1].isupper() and head.isidentifier() else None


def _declared_names(declaration: SyntaxNode) -> list[str]:
    names = []
    targets = [declaration.child_by_field_name(f) for f in ("name", "pattern", "declarator")]
    targets += [c for c in declaration.named_children if c.type == "variable_declarator"]
    for target in targets:
        # Declarators nest (`*p = x` is init -> pointer -> identifier); the name is at the bottom.
        while target is not None and target.child_by_field_name("declarator") is not None:
            target = target.child_by_field_name("declarator")
        if target is not None and target.type == "variable_declarator":
            target = target.child_by_field_name("name") or next(iter(target.named_children), None)
        if target is not None and "identifier" in target.type and target.type != "type_identifier":
            names.append(ts.text(target))
    return names


def _whole_definition(node: SyntaxNode) -> SyntaxNode:
    """C-family queries tag a function's declarator (`run(int x)`), not the
    definition around it, which would leave the body outside its span."""
    while node.type.endswith("declarator") and node.parent is not None:
        node = node.parent
    return node


def _tagged_call(call: SyntaxNode, name: SyntaxNode) -> tuple[SyntaxNode, str, str | None]:
    fields = (call.child_by_field_name(f) for f in _RECEIVER_FIELDS)
    receiver = next((f for f in fields if f is not None), None)
    # The name sits inside a member access (`obj.f`, `obj::f`, Kotlin's
    # `obj` + `.f` suffix): the receiver is the first part that isn't the name.
    node = name
    while receiver is None and node.parent is not None and node.parent.id != call.id:
        first = node.parent.named_children[0]
        if first.id != node.id:
            receiver = first
        node = node.parent
    return call, ts.text(name), ts.text(receiver) if receiver is not None else None


def _structural_calls(root: SyntaxNode) -> list[tuple[SyntaxNode, str, str | None]]:
    """Calls found by node shape: the callee is a bare identifier, or a member
    access whose first child is the receiver and whose last identifier is
    the method."""
    calls: list[tuple[SyntaxNode, str, str | None]] = []
    for n in ts.descendants(root):
        if n.type not in _CALL_NODE_TYPES:
            continue
        callee = n.child_by_field_name("function") or (n.named_children[0] if n.named_children else None)
        if callee is None:
            continue
        if "identifier" in callee.type and not callee.named_children:
            calls.append((n, ts.text(callee), None))
            continue
        leaves = [d for d in ts.descendants(callee) if "identifier" in d.type and not d.named_children]
        receiver = callee.named_children[0] if callee.named_children else None
        if leaves and receiver is not None:
            method = max(leaves, key=lambda leaf: leaf.start_byte)  # descendants() isn't in source order
            calls.append((n, ts.text(method), ts.text(receiver)))
    return calls


class GenericLanguage(Language):
    def __init__(self, grammar: str):
        self.grammar = grammar
        self.name = grammar
        self.grammars = (grammar,)

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        tree = ts.parse(self.grammar, source)
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, self.name, tree)

        definitions: list[tuple[SyntaxNode, str, str]] = []  # (syntax node, kind, name)
        calls: list[tuple[SyntaxNode, str, str | None]] = []  # (call node, name, receiver text)
        implementations: list[tuple[SyntaxNode, str]] = []  # (node, base name)
        query = tags_query(self.grammar)
        assert query is not None  # languages.language_for only hands out languages that have one
        for _, captures in QueryCursor(query).matches(tree.root_node):
            names = captures.get("name")
            if not names:
                continue
            for tag, nodes in captures.items():
                category, _, sub = tag.partition(".")
                if category == "definition" and sub in _CLASS_TAGS | _FUNCTION_TAGS:
                    kind = "class" if sub in _CLASS_TAGS else "function"
                    whole = _whole_definition(nodes[0])
                    if whole.type not in _PROTOTYPES:
                        definitions.append((whole, kind, ts.text(names[0])))
                elif tag in _CALL_TAGS:
                    calls.append(_tagged_call(nodes[0], names[0]))
                elif tag == "reference.implementation":
                    implementations.append((nodes[0], ts.text(names[0]).split("<")[0]))
        # Tags queries often mark only some call shapes (C# only member
        # calls, Rust no `Type::new()`, Swift none), so calls found by node
        # shape fill in the rest.
        tagged = {call.id for call, _, _ in calls}
        calls += [c for c in _structural_calls(tree.root_node) if c[0].id not in tagged]

        walker = _FileWalker(facts, self.name)
        walker.add_definitions(definitions)
        walker.add_bases(implementations)
        walker.add_calls(calls)
        self.scan_module(tree.root_node, facts, walker.defined)
        return facts

    @staticmethod
    def attach_imports(facts: FileFacts, imports: dict[str, str]) -> None:
        """Points every call and base naming an imported type or function at
        that import, so it resolves to the imported module first."""
        for ref in facts.calls + facts.bases:
            if ref.receiver in imports and ref.receiver_import is None:
                ref.receiver_import = imports[ref.receiver]
            elif ref.receiver is None and ref.via_import is None and ref.name in imports:
                ref.via_import = imports[ref.name]

    def scan_module(self, root: SyntaxNode, facts: FileFacts, defined: dict[tuple[int, int], tuple[str, str]]) -> None:
        """Hook for a language that builds on this one to add what tags
        queries don't mark, like imports and packages. defined maps each
        definition's byte span to its (node id, kind)."""
