"""Vue single-file components. The `<script>` blocks are plain TypeScript/
JavaScript, extracted by the TypeScript extractor. The file itself becomes
a component node (named after the file, the way Vue names it) that owns
the script's definitions, since `<script setup>` compiles into the
component's setup function. The template adds edges for the child
components it renders and the handlers and functions it calls.
"""

from __future__ import annotations

import posixpath
import re

from tree_sitter import Node as SyntaxNode

from codegraph.languages import treesitter as ts
from codegraph.languages.base import FileFacts, Language, Ref, RepoIndex
from codegraph.languages.typescript import ScriptWalker, TypeScriptLanguage, grammar_for, walk_script

_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
_TAGS = ("start_tag", "self_closing_tag")


def _masked_script(source: bytes, scripts: list[SyntaxNode]) -> bytes:
    """The file with everything outside the script blocks blanked to spaces
    (newlines kept), so parsing it as TypeScript gives line numbers that
    match the .vue file."""
    masked = bytearray(b if b == 0x0A else 0x20 for b in source)
    for script in scripts:
        masked[script.start_byte : script.end_byte] = source[script.start_byte : script.end_byte]
    return bytes(masked)


def _script_lang(script_element: SyntaxNode) -> str:
    start = next((c for c in script_element.named_children if c.type == "start_tag"), None)
    for attr in start.named_children if start is not None else []:
        name = next((c for c in attr.named_children if c.type == "attribute_name"), None)
        if attr.type == "attribute" and ts.text(name) == "lang":
            value = next((c for c in ts.descendants(attr) if c.type == "attribute_value"), None)
            return ts.text(value)
    return "js"


def _component_name(tag: str) -> str:
    """`song-list` and `SongList` both refer to the SongList component."""
    return "".join(part[:1].upper() + part[1:] for part in tag.split("-")) if "-" in tag else tag


class VueLanguage(Language):
    name = "vue"
    extensions = (".vue",)
    grammars = ("vue",)

    def __init__(self, scripts: TypeScriptLanguage):
        self._scripts = scripts

    def extract(self, source: bytes, rel_file: str) -> FileFacts:
        document = ts.parse("vue", source).root_node
        facts = FileFacts(module_id=rel_file)
        facts.nodes[rel_file] = ts.module_node(rel_file, "vue", ts.parse("vue", source))
        component = posixpath.splitext(posixpath.basename(rel_file))[0]
        component_id = ts.add_definition(facts, rel_file, component, "function", "vue", document)

        script_elements = [c for c in document.named_children if c.type == "script_element"]
        raw = [c for s in script_elements for c in s.named_children if c.type == "raw_text"]
        grammar = grammar_for(_script_lang(script_elements[0])) if script_elements else "javascript"
        if raw:
            tree = ts.parse(grammar, _masked_script(source, raw))
            walker = walk_script(facts, tree, "vue", (component_id, component))
            # Top-level script code is the body of the component's setup function.
            walker.record_calls(component_id, tree.root_node, None)
        else:
            walker = walk_script(facts, ts.parse(grammar, b""), "vue", (component_id, component))

        for template in (c for c in document.named_children if c.type == "template_element"):
            self._template(template, component_id, grammar, walker)
        return facts

    def _template(self, template: SyntaxNode, component_id: str, grammar: str, walker: ScriptWalker) -> None:
        for tag in (n for n in ts.descendants(template) if n.type in _TAGS):
            name = _component_name(ts.text(next((c for c in tag.named_children if c.type == "tag_name"), None)))
            if name in walker.imports.symbols:
                ref = walker.imports.ref(component_id, [name])
                if ref is not None:
                    walker.facts.calls.append(ref)
            for attr in (c for c in tag.named_children if c.type == "directive_attribute"):
                value = ts.text(next((c for c in ts.descendants(attr) if c.type == "attribute_value"), None))
                if not value:
                    continue
                if ts.text(attr).startswith(("@", "v-on:")) and _IDENTIFIER.match(value):
                    walker.facts.calls.append(Ref(component_id, value))  # `@click="play"` names a handler
                else:
                    expression = ts.parse(grammar, value.encode())
                    walker.record_calls(component_id, expression.root_node, None)

    def resolve_import(self, spec: str, from_file: str, index: RepoIndex) -> list[str]:
        return self._scripts.resolve_import(spec, from_file, index)
