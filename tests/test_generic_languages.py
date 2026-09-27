"""The tags-query fallback used for languages without a dedicated
extractor, checked on Java (implicit `this`) and Rust (impl blocks)."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_java_methods_nest_under_class_and_self_calls_resolve(make_repo):
    repo = make_repo(
        {
            "Cart.java": """
/** A shopping cart. */
public class Cart {
    public void add(Item item) {
        recalc();
        this.log();
        item.price();
    }
    private void recalc() {}
    private void log() {}
}
class Item { int price() { return 1; } }
"""
        }
    )
    result = parse_repo(repo)
    assert result.nodes["Cart.java::Cart"].docstring == "A shopping cart."
    assert ("Cart.java::Cart", "Cart.java::Cart.add") in edges(result, "defines")
    # item.price() has an unknown receiver type, so it's deliberately not guessed.
    assert {dst for src, dst in edges(result, "calls") if src == "Cart.java::Cart.add"} == {
        "Cart.java::Cart.recalc",
        "Cart.java::Cart.log",
    }


def test_rust_impl_methods_attach_to_their_type(make_repo):
    repo = make_repo(
        {
            "lib.rs": """
pub struct Point { x: i32 }

impl Point {
    pub fn len(&self) -> i32 { self.norm() + helper() }
    fn norm(&self) -> i32 { 0 }
}

fn helper() -> i32 { 1 }
"""
        }
    )
    result = parse_repo(repo)
    assert ("lib.rs::Point", "lib.rs::Point.len") in edges(result, "defines")
    calls = edges(result, "calls")
    assert ("lib.rs::Point.len", "lib.rs::Point.norm") in calls
    assert ("lib.rs::Point.len", "lib.rs::helper") in calls


def test_non_code_files_are_ignored(make_repo):
    repo = make_repo({"main.rs": "fn main() {}\n", "README.md": "# hi\n", "data.json": "{}"})
    assert {n.file for n in parse_repo(repo).nodes.values()} == {"main.rs"}
