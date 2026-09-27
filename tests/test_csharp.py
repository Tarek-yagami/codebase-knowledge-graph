"""C#: namespaces and `using` directives, inheritance, and calls resolved
through declared field and parameter types."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_namespaces_usings_and_typed_calls(make_repo):
    repo = make_repo(
        {
            "src/Domain/Entity.cs": """namespace Shop.Domain;

public abstract class Entity { public int Id() { return 1; } }
""",
            "src/Domain/Order.cs": """namespace Shop.Domain;

/// <summary>An order.</summary>
public class Order : Entity { }
""",
            "src/Data/Db.cs": "namespace Shop.Data;\n\npublic class Db { public void Save() {} }\n",
            "src/Web/OrderService.cs": """using Shop.Data;
using Shop.Domain;

namespace Shop.Web;

public class OrderService
{
    private readonly Db _db;

    public void Place(Order order)
    {
        _db.Save();
        order.Id();
        Audit();
        Log.Write();
    }

    private void Audit() {}
}

public static class Log { public static void Write() {} }
""",
        }
    )
    result = parse_repo(repo)
    assert {dst for src, dst in edges(result, "imports") if src == "src/Web/OrderService.cs"} == {
        "src/Data/Db.cs",
        "src/Domain/Entity.cs",
        "src/Domain/Order.cs",
    }
    # Order finds Entity through its own namespace, no using needed.
    assert ("src/Domain/Order.cs::Order", "src/Domain/Entity.cs::Entity") in edges(result, "inherits")
    place = {dst for src, dst in edges(result, "calls") if src == "src/Web/OrderService.cs::OrderService.Place"}
    assert place == {
        "src/Data/Db.cs::Db.Save",  # field type
        "src/Domain/Entity.cs::Entity.Id",  # parameter type, through inheritance
        "src/Web/OrderService.cs::OrderService.Audit",  # implicit this
        "src/Web/OrderService.cs::Log.Write",  # static call
    }
