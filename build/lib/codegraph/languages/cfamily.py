"""C and C++. Calls, declared-type receivers and base classes come from the
generic extraction, but definitions come from walking the tree, since the
tags queries miss methods and out-of-class definitions (`void A::f() {}`,
attached to class A wherever it's declared) and count prototypes.
`#include`s resolve relative to the including file, else by a unique path
suffix, since the real include paths live in the build system.
"""

from __future__ import annotations

import posixpath
import re

from tree_sitter import Node as SyntaxNode
from tree_sitter import Tree

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Ref, RepoIndex
from codegraph.languages.generic import GenericLanguage

_CPP_ONLY = re.compile(rb"^\s*(class|namespace|template)\b|::|\bpublic:", re.M)
_TEMPLATE_ARGS = re.compile(r"<[^<>]*>")
_CLASS_TYPES = ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier")
_C_EXTENSIONS = (".c",)
_CPP_EXTENSIONS = (".h", ".cc", ".cpp", ".cxx", ".c++", ".hh", ".hpp", ".hxx", ".h++", ".ipp")


def _function_name(definition: SyntaxNode) -> str | None:
    """The name a function_definition defines, `ns::A::f` kept qualified."""
    declarator = definition.child_by_field_name("declarator")
    while declarator is not None and declarator.type != "function_declarator":
        declarator = declarator.child_by_field_name("declarator")
    name = declarator.child_by_field_name("declarator") if declarator is not None else None
    if name is None:
        return None
    # Drop template arguments, innermost first: `file_sink<std::vector<T>>::flush` -> `file_sink::flush`.
    text = ts.text(name)
    while _TEMPLATE_ARGS.search(text):
        text = _TEMPLATE_ARGS.sub("", text)
    return text


class CFamilyLanguage(GenericLanguage):
    extensions = _C_EXTENSIONS + _CPP_EXTENSIONS

    def __init__(self) -> None:
        super().__init__("cpp")
        self.name = "c/c++"  # one namespace for both, since .c files include .h headers
        self.grammars = ("c", "cpp")

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        ext = posixpath.splitext(rel_file)[1].lower()
        # A .h header can be either; it's C++ if it uses anything C lacks.
        is_c = ext in _C_EXTENSIONS or (ext == ".h" and not _CPP_ONLY.search(source))
        grammar = "c" if is_c else "cpp"
        return self.extract_with(grammar, grammar, source, rel_file)

    def definitions(self, tree: Tree, tagged: list[tuple[SyntaxNode, str, str]]) -> list[tuple[SyntaxNode, str, str]]:
        found = []
        for n in ts.find(tree, ("function_definition", *_CLASS_TYPES)):
            if n.type == "function_definition":
                name = _function_name(n)
                if name is not None:
                    found.append((n, "function", name))
            elif n.child_by_field_name("body") is not None:
                name_node = n.child_by_field_name("name")
                if name_node is not None:  # a template specialization `Box<int>` is still Box
                    found.append((n, "class", ts.text(name_node).split("<")[0].strip()))
        return found

    def scan_module(self, tree: Tree, facts: FileFacts, defined: dict[tuple[int, int], tuple[str, str]]) -> None:
        # Base classes, including templates (`: public base_sink<Mutex>`) that the tags query misses.
        facts.bases.clear()
        for clause in ts.find(tree, ("base_class_clause",)):
            owner = defined.get((clause.parent.start_byte, clause.parent.end_byte)) if clause.parent else None
            if owner is None:
                continue
            for base in clause.named_children:
                name = ts.text(base).split("<")[0].rsplit("::", 1)[-1].strip()
                if base.type != "access_specifier" and name.isidentifier():
                    facts.bases.append(Ref(owner[0], name))
        for include in ts.find(tree, ("preproc_include",)):
            path = include.child_by_field_name("path")
            if path is not None:
                facts.imports.append(ts.text(path).strip('"'))

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        """`"util/x.h"` is looked up next to the including file first;
        either form then matches a repo file whose path ends with it, when
        exactly one does. `<vector>` and other system headers match none."""
        system = spec.startswith("<")
        header = spec.strip("<>")
        if not system:
            beside = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), header))
            if beside in index.modules:
                return [beside]
        by_name: dict[str, list[str]] | None = index.cache.get("c_by_basename")
        if by_name is None:
            by_name = {}
            for m in index.modules:
                by_name.setdefault(posixpath.basename(m), []).append(m)
            index.cache["c_by_basename"] = by_name
        matches = [m for m in by_name.get(posixpath.basename(header), []) if m == header or m.endswith("/" + header)]
        return matches if len(matches) == 1 else []
