"""Tests for the real correctness bugs found and fixed while building this
project: relative import resolution, confidence-based call resolution, and
@overload deduplication. See README "Where static analysis breaks down".
"""

from pathlib import Path

import pytest

from codegraph.parser import parse_repo


def edges_of_kind(result, kind):
    return [e for e in result.edges if e.kind == kind]


def test_extracts_modules_functions_and_classes(make_repo):
    repo = make_repo({
        "greet.py": '''
def hello(name):
    """Say hello."""
    return f"hi {name}"


class Greeter:
    def greet(self, name):
        return hello(name)
'''
    })
    result = parse_repo(repo)

    assert result.nodes["greet"].kind == "module"
    assert result.nodes["greet.hello"].kind == "function"
    assert result.nodes["greet.Greeter"].kind == "class"
    assert result.nodes["greet.Greeter.greet"].kind == "function"


def test_relative_import_resolves_to_sibling_module(make_repo):
    repo = make_repo({
        "models.py": "class User:\n    pass\n",
        "views.py": "from .models import User\n",
    })
    result = parse_repo(repo)

    imports = edges_of_kind(result, "imports")
    assert any(e.src == "views" and e.dst == "models" for e in imports)


def test_self_call_resolves_within_enclosing_class(make_repo):
    """The real bug: self.request() inside one class must not resolve to an
    unrelated function elsewhere that happens to share the name.
    """
    repo = make_repo({
        "a.py": "def request():\n    pass\n",
        "b.py": '''
class Session:
    def get(self):
        return self.request()

    def request(self):
        return "real"
'''
    })
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert any(e.src == "b.Session.get" and e.dst == "b.Session.request" for e in calls)
    assert not any(e.dst == "a.request" for e in calls)


def test_self_call_resolves_through_inheritance(make_repo):
    repo = make_repo({
        "a.py": '''
class Base:
    def close(self):
        pass


class Child(Base):
    def shutdown(self):
        return self.close()
'''
    })
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert any(e.src == "a.Child.shutdown" and e.dst == "a.Base.close" for e in calls)


def test_bare_call_only_resolves_when_unambiguous(make_repo):
    repo = make_repo({
        "a.py": "def helper():\n    pass\n",
        "b.py": "def helper():\n    pass\n",
        "c.py": '''
def use_ambiguous():
    return helper()
'''
    })
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert not any(e.src == "c.use_ambiguous" for e in calls)
    assert ("c.use_ambiguous", "helper") in result.unresolved_calls


def test_call_on_other_receiver_is_never_resolved(make_repo):
    """kwargs.get(...) is a dict method, not user code - it must never be
    matched against an unrelated function named `get` elsewhere.
    """
    repo = make_repo({
        "api.py": "def get():\n    pass\n",
        "b.py": '''
def use(kwargs):
    return kwargs.get("stream")
'''
    })
    result = parse_repo(repo)

    calls = edges_of_kind(result, "calls")
    assert not any(e.dst == "api.get" for e in calls)


def test_overload_stubs_are_skipped(make_repo):
    repo = make_repo({
        "auth.py": '''
from typing import overload


class HTTPBasicAuth:
    @overload
    def __init__(self, username: str, password: str) -> None: ...
    @overload
    def __init__(self, username: bytes, password: bytes) -> None: ...

    def __init__(self, username, password):
        self.username = username
        self.password = password
'''
    })
    result = parse_repo(repo)

    defines = [e for e in edges_of_kind(result, "defines") if e.dst == "auth.HTTPBasicAuth.__init__"]
    assert len(defines) == 1


def test_multiple_inheritance_captures_both_bases(make_repo):
    repo = make_repo({
        "exceptions.py": '''
class RequestException(Exception):
    pass


class ConnectionError(RequestException):
    pass


class Timeout(RequestException):
    pass


class ConnectTimeout(ConnectionError, Timeout):
    pass
'''
    })
    result = parse_repo(repo)

    bases = {e.dst for e in edges_of_kind(result, "inherits") if e.src == "exceptions.ConnectTimeout"}
    assert bases == {"exceptions.ConnectionError", "exceptions.Timeout"}


def test_parse_repo_raises_on_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_repo(tmp_path / "does_not_exist")


def test_parse_repo_raises_on_empty_directory(tmp_path):
    with pytest.raises(ValueError):
        parse_repo(tmp_path)
