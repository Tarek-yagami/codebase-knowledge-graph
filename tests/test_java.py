"""Java extraction: package visibility and imports (single, wildcard,
static), inheritance, and calls resolved through declared variable types."""

from codegraph.parser import parse_repo

MODEL = "src/main/java/shop/model"
WEB = "src/main/java/shop/web"


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def shop(make_repo):
    return parse_repo(
        make_repo(
            {
                f"{MODEL}/BaseEntity.java": """package shop.model;

public class BaseEntity {
    public Integer getId() { return 1; }
}
""",
                f"{MODEL}/Owner.java": """package shop.model;

/** A pet owner. */
public class Owner extends BaseEntity {
    public void addPet(Pet pet) { pet.setOwner(this); }
}
""",
                f"{MODEL}/Pet.java": """package shop.model;

public class Pet {
    public void setOwner(Owner o) {}
}
""",
                f"{MODEL}/OwnerRepository.java": """package shop.model;

public interface OwnerRepository {
    Owner findById(Integer id);
}
""",
                f"{WEB}/Strings.java": """package shop.web;

public class Strings {
    public static String trim(String s) { return s; }
}
""",
                f"{WEB}/OwnerController.java": """package shop.web;

import shop.model.*;
import shop.model.OwnerRepository;
import static shop.web.Strings.trim;

public class OwnerController {
    private final OwnerRepository owners;

    public String show(Integer id) {
        Owner owner = this.owners.findById(id);
        var pet = new Pet();
        owner.addPet(pet);
        owner.getId();
        trim("x");
        render();
        unknown().chained();
        return "ok";
    }

    private void render() {}
}
""",
            }
        )
    )


def test_imports_resolve_by_package_including_wildcards(make_repo):
    imports = {dst for src, dst in edges(shop(make_repo), "imports") if src == f"{WEB}/OwnerController.java"}
    assert f"{MODEL}/OwnerRepository.java" in imports
    assert f"{MODEL}/Owner.java" in imports  # through `import shop.model.*`
    assert f"{WEB}/Strings.java" in imports  # the static import's class


def test_same_package_classes_need_no_import(make_repo):
    result = shop(make_repo)
    assert (f"{MODEL}/Owner.java::Owner", f"{MODEL}/BaseEntity.java::BaseEntity") in edges(result, "inherits")
    assert result.nodes[f"{MODEL}/Owner.java::Owner"].docstring == "A pet owner."


def test_calls_resolve_through_declared_types(make_repo):
    result = shop(make_repo)
    show = {dst for src, dst in edges(result, "calls") if src == f"{WEB}/OwnerController.java::OwnerController.show"}
    assert show == {
        f"{MODEL}/OwnerRepository.java::OwnerRepository.findById",  # field type, interface method
        f"{MODEL}/Pet.java::Pet",  # new Pet(), with `var` typed from it
        f"{MODEL}/Owner.java::Owner.addPet",  # local variable type
        f"{MODEL}/BaseEntity.java::BaseEntity.getId",  # inherited through the declared type
        f"{WEB}/Strings.java::Strings.trim",  # static import
        f"{WEB}/OwnerController.java::OwnerController.render",  # implicit this
    }
    # A parameter's declared type works the same way.
    assert (f"{MODEL}/Owner.java::Owner.addPet", f"{MODEL}/Pet.java::Pet.setOwner") in edges(result, "calls")
