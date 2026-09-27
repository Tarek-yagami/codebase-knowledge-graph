"""Python extraction via the stdlib `ast` module, which is more precise for
Python than a tree-sitter grammar and needs no extra dependency.
"""

from __future__ import annotations

import ast
import posixpath

from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex
from codegraph.model import Edge, Node, member_id


def _join(spec: str, name: str) -> str:
    return spec + name if spec.endswith(".") else f"{spec}.{name}"


def _dotted(expr: ast.expr) -> list[str] | None:
    """`a.b.C` -> ["a", "b", "C"]; `Generic[T]` -> its unsubscripted base."""
    if isinstance(expr, ast.Subscript):
        expr = expr.value
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return parts[::-1]


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        name = dec.attr if isinstance(dec, ast.Attribute) else getattr(dec, "id", None)
        if name == "overload":
            return True
    return False


def _module_level_names(tree: ast.Module) -> set[str]:
    """Functions and classes defined at module level, including inside
    module-level `try`/`if` blocks, but not inside other definitions."""
    names: set[str] = set()
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        stmt = pending.pop()
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, (ast.If, ast.Try)):
            pending.extend(stmt.body + stmt.orelse)
            pending.extend(s for h in getattr(stmt, "handlers", []) for s in h.body)
            pending.extend(getattr(stmt, "finalbody", []))
    return names


class _ImportMap:
    """What each local name in a file was imported as, so a call or base
    class written through that name can be traced back to its module."""

    def __init__(self, tree: ast.Module):
        self.defined_here = _module_level_names(tree)
        self.specs: list[str] = []
        self.symbols: dict[str, tuple[str, str]] = {}  # local name -> (from-spec, original name)
        self.modules: dict[str, str] = {}  # local name -> spec of the module it's bound to
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.specs.append(alias.name)
                    if alias.asname:
                        self.modules[alias.asname] = alias.name
                    else:
                        head = alias.name.split(".")[0]
                        self.modules[head] = head
            elif isinstance(node, ast.ImportFrom):
                spec = "." * (node.level or 0) + (node.module or "")
                if node.module:
                    self.specs.append(spec)
                for alias in node.names:
                    local = alias.asname or alias.name
                    if not node.module:
                        # `from . import X` - each name is itself a sibling module/package
                        self.specs.append(_join(spec, alias.name))
                    self.symbols[local] = (spec, alias.name)
                    self.modules[local] = _join(spec, alias.name)

    def ref(self, src: str, parts: list[str]) -> Ref:
        """Builds a Ref for a name written as `parts` (`["mod", "func"]`)."""
        *prefix, name = parts
        if not prefix:
            # A module-level definition wins over an import of the same name,
            # like the fallback in `try: from x import f / except ImportError: def f`.
            if name in self.symbols and name not in self.defined_here:
                spec, original = self.symbols[name]
                return Ref(src, original, via_import=spec)
            return Ref(src, name)
        if prefix[0] in self.modules:
            spec = self.modules[prefix[0]]
            for p in prefix[1:]:
                spec = _join(spec, p)
            return Ref(src, name, via_import=spec)
        return Ref(src, name)


class _FileVisitor(ast.NodeVisitor):
    def __init__(self, facts: FileFacts, rel_file: str, source_lines: list[str], imports: _ImportMap):
        self.facts = facts
        self.file = rel_file
        self.source_lines = source_lines
        self.imports = imports
        self._scope_stack: list[tuple[str, str]] = [(facts.module_id, "")]  # (node id, qualname)
        # Tracks only the nearest enclosing class, independent of _scope_stack,
        # so a closure nested inside a method still resolves `self.x()` against
        # the method's class rather than needing its own class scope.
        self._class_stack: list[str] = []

    def _add(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> tuple[str, str]:
        parent_id, parent_qual = self._scope_stack[-1]
        qual = f"{parent_qual}.{node.name}" if parent_qual else node.name
        node_id = member_id(self.facts.module_id, qual)
        end = getattr(node, "end_lineno", node.lineno)
        self.facts.nodes[node_id] = Node(
            id=node_id,
            kind=kind,
            name=node.name,
            file=self.file,
            lineno=node.lineno,
            end_lineno=end,
            language="python",
            docstring=ast.get_docstring(node) or "",
            source="\n".join(self.source_lines[node.lineno - 1 : end])[:1500],
        )
        self.facts.defines.append(Edge(parent_id, node_id, "defines"))
        return node_id, qual

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        node_id, qual = self._add(node, "class")
        for base in node.bases:
            parts = _dotted(base)
            if parts:
                self.facts.bases.append(self.imports.ref(node_id, parts))
        self._scope_stack.append((node_id, qual))
        self._class_stack.append(node_id)
        self.generic_visit(node)
        self._class_stack.pop()
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if _is_overload(node):
            # Typing overload stubs share a name with the real implementation
            # and aren't real, separate functions - skip them entirely rather
            # than recording three "definitions" of the same method.
            return
        node_id, qual = self._add(node, "function")
        self._record_calls(node_id, node)
        self._scope_stack.append((node_id, qual))
        # Only nested defs get their own nodes; the rest of the body was
        # already covered by _record_calls.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self._scope_stack.pop()

    def _record_calls(self, node_id: str, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Records only calls that can be resolved with confidence: `self.x()`
        (against the enclosing class and its bases), `x()` and `mod.x()`
        (through imports, or by an unambiguous name). Calls on any other
        receiver, like a local variable or a dict, are deliberately left
        untracked rather than guessed at via a global same-name registry.
        """
        enclosing_class = self._class_stack[-1] if self._class_stack else None
        for n in ast.walk(func_node):
            if not isinstance(n, ast.Call):
                continue
            callee = n.func
            if isinstance(callee, ast.Name):
                self.facts.calls.append(self.imports.ref(node_id, [callee.id]))
            elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
                if callee.value.id == "self":
                    if enclosing_class:
                        self.facts.calls.append(Ref(node_id, callee.attr, receiver=enclosing_class))
                elif callee.value.id in self.imports.modules:
                    self.facts.calls.append(self.imports.ref(node_id, [callee.value.id, callee.attr]))


class PythonLanguage(Language):
    name = "python"
    extensions = (".py",)
    grammars = ("python",)

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        text = source.decode("utf-8", errors="replace")
        tree = ast.parse(text, filename=rel_file)  # SyntaxError: parser.py skips the file
        lines = text.splitlines()
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = Node(
            id=rel_file,
            kind="module",
            name=rel_file,
            file=rel_file,
            lineno=1,
            end_lineno=len(lines),
            language="python",
            docstring=ast.get_docstring(tree) or "",
        )
        imports = _ImportMap(tree)
        facts.imports = imports.specs
        _FileVisitor(facts, rel_file, lines, imports).visit(tree)
        return facts

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        level = len(spec) - len(spec.lstrip("."))
        parts = [p for p in spec[level:].split(".") if p]
        if level:
            base = posixpath.dirname(from_file)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            path = posixpath.join(base, *parts)
            candidates = [f"{path}.py"] if parts else []
            candidates.append(posixpath.join(path, "__init__.py"))
            return [c for c in candidates if c in index.modules][:1]
        return self._resolve_absolute(parts, from_file, index)

    def _resolve_absolute(self, parts: list[str], from_file: str, index: RepoIndex) -> list[str]:
        """An absolute import can point below any source root (`src/`, a
        service directory, the repo root), so it's matched by dotted-path
        suffix. Ties go to the candidate sharing the most directories with
        the importing file, and a tie that's still unbroken stays unresolved.
        """
        suffixes = index.cache.get("python_suffixes")
        if suffixes is None:
            suffixes = {}
            for m in index.modules:
                if not m.endswith(".py"):
                    continue
                dotted = m[: -len(".py")].split("/")
                if dotted[-1] == "__init__":
                    dotted.pop()
                for i in range(len(dotted)):
                    suffixes.setdefault(".".join(dotted[i:]), []).append(m)
            index.cache["python_suffixes"] = suffixes

        candidates = suffixes.get(".".join(parts), [])
        if len(candidates) <= 1:
            return candidates
        from_dir = posixpath.dirname(from_file)

        def shared(m: str) -> int:
            common = posixpath.commonpath([from_dir, posixpath.dirname(m)])
            return len(common.split("/")) if common else 0

        best = max(shared(m) for m in candidates)
        top = [m for m in candidates if shared(m) == best]
        return top if len(top) == 1 else []
