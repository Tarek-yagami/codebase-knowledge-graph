"""Rust: the module tree (`mod`, `use crate::`/`self::`/`super::`), crates in
a Cargo workspace, custom crate roots, and trait impls as inheritance."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def workspace(make_repo):
    return parse_repo(
        make_repo(
            {
                "Cargo.toml": """[workspace]
members = ["crates/*"]

[package]
name = "app"

[[bin]]
name = "app"
path = "crates/app/main.rs"
""",
                "crates/app/main.rs": """mod cli;

use matcher::Matcher;

fn main() {
    cli::run();
}
""",
                "crates/app/cli.rs": """use crate::helpers::shout;

pub fn run() { shout(); }
""",
                "crates/app/helpers.rs": "pub fn shout() {}\n",
                "crates/matcher/Cargo.toml": '[package]\nname = "grep-matcher"\n',
                "crates/matcher/src/lib.rs": """pub trait Matcher {
    fn find(&self);
}

pub struct Plain;

impl Matcher for Plain {
    fn find(&self) {}
}

impl std::fmt::Debug for Plain {}

pub struct Debug;
""",
                "crates/regex/Cargo.toml": '[package]\nname = "grep-regex"\n',
                "crates/regex/src/lib.rs": """use grep_matcher::Matcher;

pub struct Regex;

impl Matcher for Regex {
    fn find(&self) { self.compile(); Regex::new(); }
}

impl Regex {
    fn compile(&self) {}
    fn new() -> Self { Regex }
}
""",
            }
        )
    )


def test_module_tree_and_custom_crate_root(make_repo):
    imports = edges(workspace(make_repo), "imports")
    assert ("crates/app/main.rs", "crates/app/cli.rs") in imports  # `mod cli;` under a [[bin]] path
    assert ("crates/app/cli.rs", "crates/app/helpers.rs") in imports  # `use crate::...`
    assert ("crates/regex/src/lib.rs", "crates/matcher/src/lib.rs") in imports  # another workspace crate


def test_trait_impls_are_inheritance_and_std_traits_stay_external(make_repo):
    inherits = edges(workspace(make_repo), "inherits")
    assert ("crates/regex/src/lib.rs::Regex", "crates/matcher/src/lib.rs::Matcher") in inherits
    assert ("crates/matcher/src/lib.rs::Plain", "crates/matcher/src/lib.rs::Matcher") in inherits
    # `impl std::fmt::Debug` is std's trait, not the crate's own `Debug` struct.
    assert ("crates/matcher/src/lib.rs::Plain", "crates/matcher/src/lib.rs::Debug") not in inherits


def test_calls_through_self_types_and_imports(make_repo):
    calls = edges(workspace(make_repo), "calls")
    assert ("crates/app/cli.rs::run", "crates/app/helpers.rs::shout") in calls
    find = {dst for src, dst in calls if src == "crates/regex/src/lib.rs::Regex.find"}
    assert find == {"crates/regex/src/lib.rs::Regex.compile", "crates/regex/src/lib.rs::Regex.new"}
