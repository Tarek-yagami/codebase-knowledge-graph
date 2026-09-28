"""The language-neutral graph model every language extractor produces and
everything downstream (graph building, queries, MCP, visualization) consumes.

Node ids are file-path based so they stay unique in mixed-language repos:
a module is its repo-relative path (`pkg/models.py`) and anything defined
in it is `<path>::<qualified name>` (`pkg/models.py::User.save`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    id: str
    kind: str  # "module" | "function" | "class" (class covers any type-like definition)
    name: str
    file: str
    lineno: int
    end_lineno: int
    language: str
    docstring: str = ""
    source: str = ""


@dataclass
class Edge:
    src: str
    dst: str
    kind: str  # "imports" | "defines" | "calls" | "inherits"


@dataclass
class ParseResult:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    unresolved_calls: list[tuple[str, str]] = field(default_factory=list)
    unresolved_imports: list[tuple[str, str]] = field(default_factory=list)


def member_id(module_id: str, qualname: str) -> str:
    return f"{module_id}::{qualname}"
