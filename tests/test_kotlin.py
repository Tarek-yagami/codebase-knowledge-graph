"""Kotlin: packages and imports (shared with Java, including Java classes
imported from Kotlin), and supertypes written as constructor calls."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_packages_imports_and_constructor_supertypes(make_repo):
    repo = make_repo(
        {
            "app/src/main/java/shop/model/Base.kt": "package shop.model\n\nopen class Base {\n    fun hello() {}\n}\n",
            "app/src/main/java/shop/util/Strings.java": """package shop.util;

public class Strings {
    public static String trim(String s) { return s; }
}
""",
            "app/src/main/java/shop/ui/Kid.kt": """package shop.ui

import shop.model.Base
import shop.util.Strings

class Kid : Base() {
    fun play() {
        hello()
        Strings.trim("x")
    }
}
""",
        }
    )
    result = parse_repo(repo)
    root = "app/src/main/java/shop"
    assert (f"{root}/ui/Kid.kt::Kid", f"{root}/model/Base.kt::Base") in edges(result, "inherits")
    play = {dst for src, dst in edges(result, "calls") if src == f"{root}/ui/Kid.kt::Kid.play"}
    assert play == {f"{root}/model/Base.kt::Base.hello", f"{root}/util/Strings.java::Strings.trim"}
