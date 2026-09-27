"""Shared tree-sitter plumbing for the extractors that use it: parsing,
node text, doc comments, and building graph nodes from syntax nodes.
Grammars come from tree-sitter-language-pack, which downloads each one
the first time it's used.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache

import tree_sitter_language_pack as tslp
from tree_sitter import Language, Parser, Query, QueryCursor, Tree
from tree_sitter import Node as SyntaxNode

from codegraph.languages.base import FileFacts
from codegraph.model import Edge, Node, member_id

# License headers and tool directives (`//go:build`, `/* eslint-disable */`) aren't docs.
_NOT_A_DOC = re.compile(r"copyright|license|spdx|^(go:|\+build|eslint|@ts-|prettier|jshint)", re.I)
_COMMENT_MARKERS = re.compile(r"^\s*(/\*\*?|\*/|\*|//+|#+)\s?")


@cache
def get_parser(grammar: str) -> Parser:
    return tslp.get_parser(grammar)


def parse(grammar: str, source: bytes) -> Tree:
    return get_parser(grammar).parse(source)


def descendants(node: SyntaxNode | None, prune: frozenset[str] = frozenset()) -> Iterator[SyntaxNode]:
    """node and every named node below it, not descending into (or
    yielding) nodes whose type is in prune. node itself is always included,
    since an arrow function's body can be a single call: `() => g()`."""
    if node is None:
        return
    yield node
    stack = list(node.named_children)
    while stack:
        n = stack.pop()
        if n.type in prune:
            continue
        yield n
        stack.extend(n.named_children)


@cache
def _type_query(language: Language, types: tuple[str, ...]) -> Query | None:
    known = [t for t in types if language.id_for_node_kind(t, True)]
    return Query(language, " ".join(f"({t}) @node" for t in known)) if known else None


def find(tree: Tree, types: tuple[str, ...], root: SyntaxNode | None = None) -> list[SyntaxNode]:
    """Every node of the given types in tree (or under root), in document
    order. Runs in tree-sitter's C query engine, far faster than walking the
    tree in Python. Types the grammar doesn't have are ignored."""
    query = _type_query(tree.language, types)
    if query is None:
        return []
    nodes = QueryCursor(query).captures(root if root is not None else tree.root_node).get("node", [])
    return sorted(nodes, key=lambda n: n.start_byte)


def text(node: SyntaxNode | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


def _clean(comments: list[SyntaxNode]) -> str:
    lines = [line for c in comments for line in text(c).splitlines()]
    cleaned = [_COMMENT_MARKERS.sub("", line).rstrip().rstrip("*/").rstrip() for line in lines]
    return "\n".join(cleaned).strip()


def leading_comment(node: SyntaxNode) -> str:
    """The comment block directly above a definition (JSDoc, Go doc
    comments, `///` in Rust), with comment markers stripped."""
    block: list[SyntaxNode] = []
    prev = node.prev_named_sibling
    row = node.start_point[0]
    while prev is not None and "comment" in prev.type and prev.end_point[0] >= row - 1:
        block.insert(0, prev)
        row = prev.start_point[0]
        prev = prev.prev_named_sibling
    return _clean(block)


def _file_doc(root: SyntaxNode) -> str:
    """The first comment block at the top of a file that's neither a
    license header nor the doc comment of the definition right below it
    (Go's package doc, which sits directly above `package`, counts)."""
    kids = root.named_children
    i = 0
    while i < len(kids) and "comment" in kids[i].type:
        block = [kids[i]]
        i += 1
        while i < len(kids) and "comment" in kids[i].type and kids[i].start_point[0] <= block[-1].end_point[0] + 1:
            block.append(kids[i])
            i += 1
        after = kids[i] if i < len(kids) else None
        doc = _clean(block)
        documents_file = (
            after is None
            or after.start_point[0] > block[-1].end_point[0] + 1  # a blank line separates them
            or after.type == "package_clause"
            or "comment" in after.type
        )
        if doc and documents_file and not _NOT_A_DOC.search(doc[:300]):
            return doc
    return ""


def module_node(rel_file: str, language: str, tree: Tree) -> Node:
    root = tree.root_node
    return Node(
        id=rel_file,
        kind="module",
        name=rel_file,
        file=rel_file,
        lineno=1,
        end_lineno=root.end_point[0] + 1,
        language=language,
        docstring=_file_doc(root),
    )


def definition_node(
    node_id: str,
    kind: str,
    name: str,
    rel_file: str,
    language: str,
    syntax: SyntaxNode,
    doc_anchor: SyntaxNode | None = None,
) -> Node:
    """doc_anchor is where the doc comment sits when it isn't directly above
    `syntax`, e.g. above the `export` wrapping a TS declaration."""
    return Node(
        id=node_id,
        kind=kind,
        name=name,
        file=rel_file,
        lineno=syntax.start_point[0] + 1,
        end_lineno=syntax.end_point[0] + 1,
        language=language,
        docstring=leading_comment(doc_anchor or syntax),
        source=text(syntax)[:1500],
    )


def add_definition(
    facts: FileFacts,
    parent_id: str | None,
    qualname: str,
    kind: str,
    language: str,
    syntax: SyntaxNode,
    doc_anchor: SyntaxNode | None = None,
) -> str:
    """Records a definition and, when parent_id is given, its "defines" edge."""
    node_id = member_id(facts.module_id, qualname)
    name = qualname.rsplit(".", 1)[-1]
    facts.nodes[node_id] = definition_node(node_id, kind, name, facts.module_id, language, syntax, doc_anchor)
    if parent_id is not None:
        facts.defines.append(Edge(parent_id, node_id, "defines"))
    return node_id
