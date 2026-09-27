"""Tests for the real correctness bugs found and fixed while building this
project: relative import resolution, confidence-based call resolution, and
@overload deduplication. See README "Where static analysis breaks down".
"""

import pytest

from codegraph.parser import parse_repo


def edges_of_kind(result, kind):
    return [e for e in result.edges if e.kind == kind]


def test_extracts_modules_functions_and_classes(make_repo):
    repo = make_repo(
        {
            "greet.py": '''
def hello(name):
    """Say hello."""
    return f"hi {name}"


class Greeter:
    def greet(self, name):
        return hello(name)
'''
        }
    )
    result = parse_repo(repo)

    assert result.nodes["greet.py"].kind == "module"
    assert result.nodes["greet.py::hello"].kind == "function"
    assert result.nodes["greet.py::Greeter"].kind == "class"
    assert result.nodes["greet.py::Greeter.greet"].kind == "function"


def test_relative_import_resolves_to_sibling_module(make_repo):
    repo = make_repo(
        {
            "models.py": "class User:\n    pass\n",
            "views.py": "from .models import User\n",
        }
    )
    result = parse_repo(repo)

    imports = edges_of_kind(result, "imports")
    assert any(e.src == "views.py" and e.dst == "models.py" for e in imports)


def test_self_call_resolves_within_enclosing_class(make_repo):
    """The real bug: self.request() inside one class must not resolve to an
    unrelated function elsewhere that happens to share the name.
    """
    repo = make_repo(
        {
            "a.py": "def request():\n    pass\n",
            "b.py": """
class Session:
    def get(self):
        return self.request()

    def request(self):
        return "real"
""",
        }
    )
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert any(e.src == "b.py::Session.get" and e.dst == "b.py::Session.request" for e in calls)
    assert not any(e.dst == "a.py::request" for e in calls)


def test_self_call_resolves_through_inheritance(make_repo):
    repo = make_repo(
        {
            "a.py": """
class Base:
    def close(self):
        pass


class Child(Base):
    def shutdown(self):
        return self.close()
"""
        }
    )
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert any(e.src == "a.py::Child.shutdown" and e.dst == "a.py::Base.close" for e in calls)


def test_bare_call_only_resolves_when_unambiguous(make_repo):
    repo = make_repo(
        {
            "a.py": "def helper():\n    pass\n",
            "b.py": "def helper():\n    pass\n",
            "c.py": """
def use_ambiguous():
    return helper()
""",
        }
    )
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert not any(e.src == "c.py::use_ambiguous" for e in calls)
    assert ("c.py::use_ambiguous", "helper") in result.unresolved_calls


def test_call_on_other_receiver_is_never_resolved(make_repo):
    """kwargs.get(...) is a dict method, not user code - it must never be
    matched against an unrelated function named `get` elsewhere.
    """
    repo = make_repo(
        {
            "api.py": "def get():\n    pass\n",
            "b.py": """
def use(kwargs):
    return kwargs.get("stream")
""",
        }
    )
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert not any(e.dst == "api.py::get" for e in calls)


def test_overload_stubs_are_skipped(make_repo):
    repo = make_repo(
        {
            "auth.py": """
from typing import overload


class HTTPBasicAuth:
    @overload
    def __init__(self, username: str, password: str) -> None: ...
    @overload
    def __init__(self, username: bytes, password: bytes) -> None: ...

    def __init__(self, username, password):
        self.username = username
        self.password = password
"""
        }
    )
    result = parse_repo(repo)

    defines = [e for e in edges_of_kind(result, "defines") if e.dst == "auth.py::HTTPBasicAuth.__init__"]
    assert len(defines) == 1


def test_multiple_inheritance_captures_both_bases(make_repo):
    repo = make_repo(
        {
            "exceptions.py": """
class RequestException(Exception):
    pass


class ConnectionError(RequestException):
    pass


class Timeout(RequestException):
    pass


class ConnectTimeout(ConnectionError, Timeout):
    pass
"""
        }
    )
    result = parse_repo(repo)

    bases = {e.dst for e in edges_of_kind(result, "inherits") if e.src == "exceptions.py::ConnectTimeout"}
    assert bases == {"exceptions.py::ConnectionError", "exceptions.py::Timeout"}


def test_parse_repo_raises_on_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_repo(tmp_path / "does_not_exist")


def test_parse_repo_raises_on_empty_directory(tmp_path):
    with pytest.raises(ValueError):
        parse_repo(tmp_path)


def test_call_through_aliased_import_resolves_to_that_module(make_repo):
    """`from .a import helper as h; h()` must reach a.helper even though
    another module also defines a `helper`."""
    repo = make_repo(
        {
            "a.py": "def helper():\n    pass\n",
            "b.py": "def helper():\n    pass\n",
            "c.py": "from .a import helper as h\n\n\ndef use():\n    return h()\n",
        }
    )
    calls = edges_of_kind(parse_repo(repo), "calls")
    assert any(e.src == "c.py::use" and e.dst == "a.py::helper" for e in calls)


def test_module_alias_call_resolves(make_repo):
    repo = make_repo(
        {
            "pkg/__init__.py": "",
            "pkg/sessions.py": "class Session:\n    pass\n",
            "pkg/api.py": "from . import sessions\n\n\ndef request():\n    return sessions.Session()\n",
        }
    )
    calls = edges_of_kind(parse_repo(repo), "calls")
    assert any(e.src == "pkg/api.py::request" and e.dst == "pkg/sessions.py::Session" for e in calls)


def test_nested_function_belongs_to_its_function_and_is_callable(make_repo):
    repo = make_repo(
        {
            "a.py": """
class Response:
    def iter_content(self):
        def generate():
            pass
        return generate()
"""
        }
    )
    result = parse_repo(repo)
    outer, nested = "a.py::Response.iter_content", "a.py::Response.iter_content.generate"
    assert any(e.src == outer and e.dst == nested for e in edges_of_kind(result, "defines"))
    assert any(e.src == outer and e.dst == nested for e in edges_of_kind(result, "calls"))


def test_builtin_call_never_resolves_to_a_same_named_method(make_repo):
    """The old bug: bare `set()` resolved to the only method called `set`."""
    repo = make_repo(
        {
            "jar.py": "class Jar:\n    def set(self, k):\n        pass\n",
            "cookie.py": "def create():\n    return set()\n",
        }
    )
    calls = edges_of_kind(parse_repo(repo), "calls")
    assert not any(e.src == "cookie.py::create" for e in calls)


def test_name_imported_from_outside_the_repo_never_resolves_elsewhere(make_repo):
    """`from typing import cast` means typing's cast, not the repo's only
    `cast`. A same-file fallback in `except ImportError:` still counts."""
    repo = make_repo(
        {
            "casts.py": "def cast():\n    pass\n",
            "use.py": """
from typing import cast

try:
    from socks import Manager
except ImportError:
    def Manager():
        pass


def run():
    cast()
    return Manager()
""",
        }
    )
    targets = {e.dst for e in edges_of_kind(parse_repo(repo), "calls") if e.src == "use.py::run"}
    assert targets == {"use.py::Manager"}


def test_absolute_import_resolves_under_src_layout(make_repo):
    repo = make_repo(
        {
            "src/mylib/__init__.py": "",
            "src/mylib/core.py": "def run():\n    pass\n",
            "scripts/main.py": "import mylib.core\n",
        }
    )
    imports = edges_of_kind(parse_repo(repo), "imports")
    assert any(e.src == "scripts/main.py" and e.dst == "src/mylib/core.py" for e in imports)


def test_mixed_language_repo_keeps_languages_apart(make_repo):
    """A Python `helper()` must not resolve to a TypeScript `helper`, and
    both languages' files land in one graph."""
    repo = make_repo(
        {
            "backend/app.py": "def main():\n    return helper()\n",
            "frontend/util.ts": "export function helper() {}\n",
        }
    )
    result = parse_repo(repo)
    assert {n.language for n in result.nodes.values()} == {"python", "typescript"}
    assert not edges_of_kind(result, "calls")


def test_dependency_and_hidden_directories_are_skipped(make_repo):
    repo = make_repo(
        {
            "app.py": "def f():\n    pass\n",
            "node_modules/lib/index.js": "function g() {}\n",
            ".venv/site.py": "def h():\n    pass\n",
            "web/app.test.ts": "function t() {}\n",
        }
    )
    assert {n.file for n in parse_repo(repo).nodes.values()} == {"app.py"}


def test_repeated_calls_produce_one_edge(make_repo):
    repo = make_repo({"a.py": "def f():\n    pass\n\n\ndef g():\n    f()\n    f()\n"})
    calls = [e for e in edges_of_kind(parse_repo(repo), "calls") if e.src == "a.py::g"]
    assert len(calls) == 1


def test_name_reexported_by_package_init_resolves_to_its_definition(make_repo):
    """`from .sessions import Session` in __init__ makes `from pkg import
    Session` reach the class, even with another Session elsewhere."""
    repo = make_repo(
        {
            "pkg/__init__.py": "from .sessions import Session\n",
            "pkg/sessions.py": "class Session:\n    pass\n",
            "other/sessions.py": "class Session:\n    pass\n",
            "app.py": "from pkg import Session\n\n\ndef main():\n    return Session()\n",
        }
    )
    calls = edges_of_kind(parse_repo(repo), "calls")
    assert any(e.src == "app.py::main" and e.dst == "pkg/sessions.py::Session" for e in calls)
