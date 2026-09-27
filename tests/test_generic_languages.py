"""The tags-query fallback used for languages without a dedicated
extractor, checked on Swift, Ruby, C and Rust."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


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


def test_config_formats_with_tags_queries_are_not_code(make_repo):
    repo = make_repo({"main.rs": "fn main() {}\n", "gradle.properties": "org.gradle.jvmargs=-Xmx2g\n"})
    assert {n.file for n in parse_repo(repo).nodes.values()} == {"main.rs"}


def test_swift_calls_found_by_node_shape(make_repo):
    """Swift's tags query marks no calls, so they come from the call nodes,
    and `item.price()` resolves through the parameter's declared type."""
    repo = make_repo(
        {
            "Cart.swift": """
class Cart {
    func add(item: Item) {
        recalc()
        self.log()
        item.price()
    }
    func recalc() {}
    func log() {}
}
class Item { func price() -> Int { return 1 } }
"""
        }
    )
    add_calls = {dst for src, dst in edges(parse_repo(repo), "calls") if src == "Cart.swift::Cart.add"}
    assert add_calls == {"Cart.swift::Cart.recalc", "Cart.swift::Cart.log", "Cart.swift::Item.price"}


def test_ruby_inheritance_and_self_calls(make_repo):
    repo = make_repo(
        {
            "dog.rb": """
class Animal
  def speak; end
end

class Dog < Animal
  def bark
    self.wag
    other.run
  end
  def wag; end
end
"""
        }
    )
    result = parse_repo(repo)
    assert ("dog.rb::Dog", "dog.rb::Animal") in edges(result, "inherits")
    assert {dst for src, dst in edges(result, "calls") if src == "dog.rb::Dog.bark"} == {"dog.rb::Dog.wag"}


def test_c_function_bodies_belong_to_their_function(make_repo):
    """C's query tags the declarator (`run(int x)`), not the whole function."""
    repo = make_repo(
        {
            "run.c": """static int helper(int x) { return x; }

int run(struct s *p) {
  p->go();
  return helper(1);
}
"""
        }
    )
    result = parse_repo(repo)
    assert (result.nodes["run.c::run"].lineno, result.nodes["run.c::run"].end_lineno) == (3, 6)
    assert edges(result, "calls") == {("run.c::run", "run.c::helper")}
