"""Picks the extractor for a file: a dedicated one for Python, TypeScript/
JavaScript, Go and PHP, else the generic tags-based one for any other language
tree-sitter-language-pack knows, else None (not source code).
"""

from __future__ import annotations

import posixpath
from functools import cache

import tree_sitter_language_pack as tslp

from codegraph.languages.base import Language
from codegraph.languages.generic import GenericLanguage, tags_query
from codegraph.languages.go import GoLanguage
from codegraph.languages.php import PhpLanguage
from codegraph.languages.python import PythonLanguage
from codegraph.languages.typescript import TypeScriptLanguage

_DEDICATED_LANGUAGES: tuple[Language, ...] = (
    PythonLanguage(),
    TypeScriptLanguage(),
    GoLanguage(),
    PhpLanguage(),
)
_DEDICATED = {ext: lang for lang in _DEDICATED_LANGUAGES for ext in lang.extensions}
_DEDICATED_GRAMMARS = {g for lang in _DEDICATED_LANGUAGES for g in lang.grammars}


@cache
def _generic(grammar: str) -> Language | None:
    if grammar in _DEDICATED_GRAMMARS or tags_query(grammar) is None:
        return None
    return GenericLanguage(grammar)


def language_for(rel_path: str) -> Language | None:
    ext = posixpath.splitext(rel_path)[1].lower()
    if ext in _DEDICATED:
        return _DEDICATED[ext]
    grammar = tslp.detect_language_from_path(rel_path)
    return _generic(grammar) if grammar else None
