"""C#: the generic tags-based extraction (classes, methods, inheritance,
calls) plus namespaces. A `using A.B;` directive opens a namespace rather
than naming a file, so it resolves to every file declaring that namespace,
and files in the same namespace see each other without any `using`.
"""

from __future__ import annotations

from tree_sitter import Tree

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, RepoIndex
from codegraph.languages.generic import GenericLanguage

_NAMESPACES = ("file_scoped_namespace_declaration", "namespace_declaration")


class CSharpLanguage(GenericLanguage):
    extensions = (".cs",)

    def __init__(self) -> None:
        super().__init__("csharp")

    def scan_module(self, tree: Tree, facts: FileFacts, defined: dict[tuple[int, int], tuple[str, str]]) -> None:
        namespace = next(iter(ts.find(tree, _NAMESPACES)), None)
        facts.package = ts.text(namespace.child_by_field_name("name")) if namespace is not None else ""
        for using in ts.find(tree, ("using_directive",)):
            if using.child_by_field_name("name") is not None:
                continue  # `using M = A.B.C;` aliases one type, rarely enough to skip
            target = next((c for c in using.named_children if c.type in ("qualified_name", "identifier")), None)
            if target is not None:
                facts.imports.append(ts.text(target))
                facts.open_imports.append(ts.text(target))

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        return index.packages.get(spec, [])
