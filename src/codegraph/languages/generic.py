"""Fallback extraction for any language tree-sitter-language-pack ships a
tags query for (Java, Rust, Ruby, C, C++, PHP, ...). The tags query marks
definitions and call references, so this gets classes, functions and
methods with their nesting, plus calls. It doesn't get imports or
inheritance, which need a dedicated extractor per language.
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
        self.impl_owner: dict[str, str] = {}  # method id -> owning type name

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

    def add_calls(self, calls: list[tuple[SyntaxNode, SyntaxNode]]) -> None:
        """Only receiver-less calls (`f()`) and self calls (`this.f()`) are
        kept. A tags query also reports `obj.f()` as a call to `f`, and
        resolving that by name alone would guess wrong whenever two types
        share a method name."""
        for call, name in calls:
            function, owner = self._enclosing(call)
            if function is None:
                continue
            fields = (call.child_by_field_name(f) for f in _RECEIVER_FIELDS)
            receiver = next((f for f in fields if f is not None), None)
            if receiver is None and name.parent is not None and name.parent.id != call.id:
                receiver = name.parent  # the name sits inside a member-access node, e.g. `obj.f`
            if receiver is None:
                self.facts.calls.append(Ref(function, ts.text(name), receiver=owner, bare_fallback=True))
            elif owner is not None and ts.text(receiver).split(".")[0].split("->")[0] in _SELF_WORDS:
                self.facts.calls.append(Ref(function, ts.text(name), receiver=owner))


class GenericLanguage(Language):
    def __init__(self, grammar: str):
        self.name = grammar
        self.grammars = (grammar,)

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        tree = ts.parse(self.name, source)
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, self.name, tree)

        definitions: list[tuple[SyntaxNode, str, str]] = []  # (syntax node, kind, name)
        calls: list[tuple[SyntaxNode, SyntaxNode]] = []  # (call node, name node)
        query = tags_query(self.name)
        assert query is not None  # languages.language_for only hands out languages that have one
        for _, captures in QueryCursor(query).matches(tree.root_node):
            names = captures.get("name")
            if not names:
                continue
            for tag, nodes in captures.items():
                category, _, sub = tag.partition(".")
                if category == "definition" and sub in _CLASS_TAGS | _FUNCTION_TAGS:
                    kind = "class" if sub in _CLASS_TAGS else "function"
                    definitions.append((nodes[0], kind, ts.text(names[0])))
                elif tag == "reference.call":
                    calls.append((nodes[0], names[0]))

        walker = _FileWalker(facts, self.name)
        walker.add_definitions(definitions)
        walker.add_calls(calls)
        return facts
