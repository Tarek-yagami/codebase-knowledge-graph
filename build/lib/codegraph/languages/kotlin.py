"""Kotlin: the generic tags-based extraction plus packages and imports,
resolved the same way as Java's (and across the two, as in an Android
project). Also reads supertypes written as constructor calls
(`class Kid : Base()`), which Kotlin's tags query doesn't mark.
"""

from __future__ import annotations

from tree_sitter import Tree

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Ref, RepoIndex
from codegraph.languages.generic import GenericLanguage
from codegraph.languages.java import resolve_jvm_import


class KotlinLanguage(GenericLanguage):
    extensions = (".kt", ".kts")

    def __init__(self) -> None:
        super().__init__("kotlin")

    def scan_module(self, tree: Tree, facts: FileFacts, defined: dict[tuple[int, int], tuple[str, str]]) -> None:
        root = tree.root_node
        header = next((c for c in root.named_children if c.type == "package_header"), None)
        package = next((c for c in header.named_children if c.type == "identifier"), None) if header else None
        facts.package = ".".join(p.strip() for p in ts.text(package).split(".")) if package is not None else ""
        imports: dict[str, str] = {}  # simple (or alias) name -> fully qualified import
        for header in ts.find(tree, ("import_header",)):
            path = next((c for c in header.named_children if c.type == "identifier"), None)
            spec = "".join(ts.text(path).split())
            facts.imports.append(spec)
            if any(c.type == "wildcard_import" for c in header.named_children):
                facts.open_imports.append(spec)
                continue
            alias = next((c for c in header.named_children if c.type == "import_alias"), None)
            imports[ts.text(alias.named_children[0]) if alias else spec.rsplit(".", 1)[-1]] = spec

        for spec_node in ts.find(tree, ("constructor_invocation",)):
            specifier = spec_node.parent
            owner = specifier.parent if specifier is not None and specifier.type == "delegation_specifier" else None
            found = defined.get((owner.start_byte, owner.end_byte)) if owner is not None else None
            if found is not None and found[1] == "class":
                base = ts.text(next((c for c in ts.descendants(spec_node) if c.type == "type_identifier"), None))
                facts.bases.append(Ref(found[0], base))
        self.attach_imports(facts, imports)

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        return resolve_jvm_import(spec, index)
