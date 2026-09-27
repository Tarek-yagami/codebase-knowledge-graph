"""Go extraction: package-level imports through go.mod, methods attached
to their receiver type across files, and embedding as inheritance."""

from codegraph.parser import parse_repo

GO_MOD = "module example.com/shop\n\ngo 1.22\n"


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_import_resolves_to_every_file_in_the_package(make_repo):
    repo = make_repo(
        {
            "go.mod": GO_MOD,
            "main.go": """package main

import (
\t"fmt"
\t"example.com/shop/cart"
)

func main() { cart.New(); fmt.Println() }
""",
            "cart/cart.go": "package cart\n\nfunc New() *Cart { return &Cart{} }\n",
            "cart/types.go": "package cart\n\ntype Cart struct{}\n",
        }
    )
    result = parse_repo(repo)
    assert edges(result, "imports") == {("main.go", "cart/cart.go"), ("main.go", "cart/types.go")}
    assert ("main.go::main", "cart/cart.go::New") in edges(result, "calls")


def test_method_attaches_to_type_declared_in_another_file(make_repo):
    repo = make_repo(
        {
            "go.mod": GO_MOD,
            "cart/types.go": "package cart\n\n// Cart holds items.\ntype Cart struct{ items []int }\n",
            "cart/methods.go": """package cart

// Add appends an item.
func (c *Cart) Add(i int) { c.recount(); helper() }

func (c *Cart) recount() {}
""",
            "cart/util.go": "package cart\n\nfunc helper() {}\n",
        }
    )
    result = parse_repo(repo)
    method = "cart/methods.go::Cart.Add"
    assert ("cart/types.go::Cart", method) in edges(result, "defines")
    assert result.nodes[method].docstring == "Add appends an item."
    assert result.nodes["cart/types.go::Cart"].docstring == "Cart holds items."
    calls = edges(result, "calls")
    assert (method, "cart/methods.go::Cart.recount") in calls
    assert (method, "cart/util.go::helper") in calls  # same package, different file


def test_embedded_struct_is_inheritance_and_promotes_methods(make_repo):
    repo = make_repo(
        {
            "go.mod": GO_MOD,
            "engine.go": """package shop

type Group struct{}

func (g *Group) Use() {}

type Engine struct {
\tGroup
\tname string
}

func (e *Engine) Start() { e.Use() }
""",
        }
    )
    result = parse_repo(repo)
    assert ("engine.go::Engine", "engine.go::Group") in edges(result, "inherits")
    assert ("engine.go::Engine.Start", "engine.go::Group.Use") in edges(result, "calls")


def test_test_files_are_skipped(make_repo):
    repo = make_repo({"go.mod": GO_MOD, "a.go": "package shop\n", "a_test.go": "package shop\n\nfunc TestA() {}\n"})
    assert {n.file for n in parse_repo(repo).nodes.values()} == {"a.go"}
