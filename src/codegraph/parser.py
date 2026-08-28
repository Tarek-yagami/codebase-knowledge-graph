"""AST-based static analysis: extracts modules, functions, classes, and the
relationships between them (imports, calls, inheritance) from a Python
codebase. Pure static analysis, no LLM involved.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    id: str
    kind: str  # "module" | "function" | "class"
    name: str
    file: str
    lineno: int
    end_lineno: int
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


@dataclass
class _RawImport:
    importing_module: str
    level: int
    module_part: str | None  # the "X" in "from X import ..."; None for "from . import Y"


def _resolve_import(raw: "_RawImport") -> str | None:
    """Resolves a relative or absolute import to a dotted module-id candidate,
    using the same flat dotted-path scheme as _module_id. Returns None only
    when there's nothing to resolve (e.g. a bare `import os` handled by caller).
    """
    if raw.level == 0:
        return raw.module_part

    current_parts = raw.importing_module.split(".")
    package_parts = current_parts[:-1]  # package containing the importing module
    up = raw.level - 1
    if up:
        package_parts = package_parts[:-up] if up <= len(package_parts) else []
    if raw.module_part:
        parts = package_parts + raw.module_part.split(".")
    else:
        parts = package_parts
    return ".".join(parts) if parts else None


def _module_id(file: Path, root: Path) -> str:
    rel = file.relative_to(root).with_suffix("")
    return str(rel).replace("\\", "/").replace("/", ".")


class _FileVisitor(ast.NodeVisitor):
    """Walks a single file's AST and records defs/calls relative to that file."""

    def __init__(self, module_id: str, file: str, source_lines: list[str]):
        self.module_id = module_id
        self.file = file
        self.source_lines = source_lines
        self.raw_imports: list[_RawImport] = []
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._scope_stack: list[str] = [module_id]

    def _snippet(self, node: ast.AST) -> str:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        return "\n".join(self.source_lines[start:end])[:1500]

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.raw_imports.append(_RawImport(self.module_id, 0, alias.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        level = node.level or 0
        if node.module:
            self.raw_imports.append(_RawImport(self.module_id, level, node.module))
        else:
            # `from . import X, Y` - each name is itself a sibling module/package
            for alias in node.names:
                self.raw_imports.append(_RawImport(self.module_id, level, alias.name))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self._scope_stack[-1]
        node_id = f"{self.module_id}.{node.name}"
        self.nodes[node_id] = Node(
            id=node_id,
            kind="class",
            name=node.name,
            file=self.file,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node) or "",
            source=self._snippet(node),
        )
        self.edges.append(Edge(parent, node_id, "defines"))
        for base in node.bases:
            base_name = ast.unparse(base) if hasattr(ast, "unparse") else None
            if base_name:
                self.edges.append(Edge(node_id, base_name, "inherits"))
        self._scope_stack.append(node_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        parent = self._scope_stack[-1]
        node_id = f"{parent}.{node.name}"
        self.nodes[node_id] = Node(
            id=node_id,
            kind="function",
            name=node.name,
            file=self.file,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node) or "",
            source=self._snippet(node),
        )
        self.edges.append(Edge(parent, node_id, "defines"))
        self._scope_stack.append(node_id)
        for call_name in self._calls_in(node):
            self.edges.append(Edge(node_id, call_name, "calls"))
        self._scope_stack.pop()
        # Don't generic_visit into the function body for nested defs handling
        # separately would double-count; instead visit only nested def/class.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)

    def _calls_in(self, func_node) -> set[str]:
        names: set[str] = set()
        for n in ast.walk(func_node):
            if isinstance(n, ast.Call):
                callee = n.func
                if isinstance(callee, ast.Name):
                    names.add(callee.id)
                elif isinstance(callee, ast.Attribute):
                    names.add(callee.attr)
        return names


def parse_file(file: Path, root: Path) -> _FileVisitor:
    source = file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(file))
    module_id = _module_id(file, root)
    visitor = _FileVisitor(module_id, str(file.relative_to(root)), source.splitlines())
    visitor.nodes[module_id] = Node(
        id=module_id,
        kind="module",
        name=module_id,
        file=str(file.relative_to(root)),
        lineno=1,
        end_lineno=len(visitor.source_lines),
        docstring=ast.get_docstring(tree) or "",
    )
    visitor.visit(tree)
    return visitor


def parse_repo(root: Path, exclude: tuple[str, ...] = ("test", "tests", "build", "docs")) -> ParseResult:
    result = ParseResult()
    py_files = [
        f
        for f in root.rglob("*.py")
        if not any(part in exclude for part in f.relative_to(root).parts)
    ]
    all_defined_names: dict[str, str] = {}  # short name -> node id, for call resolution

    visitors = []
    for f in py_files:
        try:
            v = parse_file(f, root)
        except SyntaxError:
            continue
        visitors.append(v)
        for node_id, node in v.nodes.items():
            result.nodes[node_id] = node
            all_defined_names.setdefault(node.name, node_id)

    module_ids = {n.id for n in result.nodes.values() if n.kind == "module"}

    for v in visitors:
        for edge in v.edges:
            if edge.kind in ("calls", "inherits") and edge.dst not in result.nodes:
                resolved = all_defined_names.get(edge.dst)
                if resolved:
                    result.edges.append(Edge(edge.src, resolved, edge.kind))
                else:
                    result.unresolved_calls.append((edge.src, edge.dst))
                continue
            result.edges.append(edge)

        seen: set[str] = set()
        for raw in v.raw_imports:
            candidate = _resolve_import(raw)
            if candidate in module_ids and candidate not in seen:
                result.edges.append(Edge(raw.importing_module, candidate, "imports"))
                seen.add(candidate)
            elif candidate not in module_ids:
                result.unresolved_imports.append((raw.importing_module, candidate or "?"))

    return result
