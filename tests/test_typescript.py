"""TypeScript/JavaScript extraction: ESM and CommonJS imports, classes and
interfaces, arrow-function definitions, and the same confidence rules for
calls as Python (`this.x()`, `x()`, `ns.x()` only)."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_definitions_including_arrow_functions_and_doc_comments(make_repo):
    repo = make_repo(
        {
            "shapes.ts": """
/** A drawable shape. */
export class Shape {
  /** Area in square units. */
  area(): number { return 0; }
}
export const double = (x: number) => x * 2;
function plain() {}
"""
        }
    )
    result = parse_repo(repo)
    assert result.nodes["shapes.ts::Shape"].kind == "class"
    assert result.nodes["shapes.ts::Shape"].docstring == "A drawable shape."
    assert result.nodes["shapes.ts::Shape.area"].docstring == "Area in square units."
    assert result.nodes["shapes.ts::double"].kind == "function"
    assert result.nodes["shapes.ts::plain"].language == "typescript"


def test_relative_imports_resolve_including_esm_js_suffix_and_index(make_repo):
    repo = make_repo(
        {
            "src/a.ts": "export function a() {}\n",
            "src/lib/index.ts": "export function b() {}\n",
            "src/main.ts": 'import { a } from "./a.js";\nimport * as lib from "./lib";\nimport fs from "node:fs";\n',
        }
    )
    assert edges(parse_repo(repo), "imports") == {("src/main.ts", "src/a.ts"), ("src/main.ts", "src/lib/index.ts")}


def test_calls_resolve_through_named_namespace_and_this(make_repo):
    repo = make_repo(
        {
            "util.ts": "export function fmt() {}\nexport function other() {}\n",
            "dup.ts": "export function fmt() {}\n",
            "app.ts": """
import { fmt as f } from "./util";
import * as u from "./util";
class Base { save() {} }
class App extends Base {
  run() { f(); u.other(); this.save(); something.unknown(); }
}
""",
        }
    )
    calls = edges(parse_repo(repo), "calls")
    run_calls = {dst for src, dst in calls if src == "app.ts::App.run"}
    # this.save() resolves through inheritance; something.unknown() isn't guessed at.
    assert run_calls == {"util.ts::fmt", "util.ts::other", "app.ts::Base.save"}


def test_extends_and_implements_become_inherits(make_repo):
    repo = make_repo(
        {
            "types.ts": """
interface Named { name: string }
interface Aged extends Named { age: number }
class Base {}
class Person extends Base implements Aged { name = ""; age = 0; }
"""
        }
    )
    inherits = edges(parse_repo(repo), "inherits")
    assert ("types.ts::Aged", "types.ts::Named") in inherits
    assert ("types.ts::Person", "types.ts::Base") in inherits
    assert ("types.ts::Person", "types.ts::Aged") in inherits


def test_commonjs_require_in_javascript(make_repo):
    repo = make_repo(
        {
            "lib/math.js": "function add(a, b) { return a + b; }\nmodule.exports = { add };\n",
            "index.js": 'const math = require("./lib/math");\nfunction main() { return math.add(1, 2); }\n',
        }
    )
    result = parse_repo(repo)
    assert result.nodes["index.js"].language == "javascript"
    assert ("index.js", "lib/math.js") in edges(result, "imports")
    assert ("index.js::main", "lib/math.js::add") in edges(result, "calls")


def test_jsx_components_and_wrapped_components(make_repo):
    """Rendering <Button /> is a call to the Button component; forwardRef and
    memo wrappers still define a component; <div> is a built-in element."""
    repo = make_repo(
        {
            "components/button.tsx": "export const Button = React.forwardRef((props, ref) => <button ref={ref} />)\n",
            "components/card.tsx": "export const Card = memo(function Card() { return <div /> })\n",
            "app/page.tsx": """import { Button } from "../components/button"
import { Card } from "../components/card"

export default function Page() {
  return <Card><Button /><div /></Card>
}
""",
        }
    )
    result = parse_repo(repo)
    assert result.nodes["components/button.tsx::Button"].kind == "function"
    page_calls = {dst for src, dst in edges(result, "calls") if src == "app/page.tsx::Page"}
    assert page_calls == {"components/button.tsx::Button", "components/card.tsx::Card"}


def test_tsconfig_path_aliases_with_comments_and_extends(make_repo):
    """Next.js's `@/` alias. tsconfig allows comments and trailing commas,
    and an app config often inherits its paths from a base config."""
    repo = make_repo(
        {
            "tsconfig.base.json": """{
  // shared by every app in the repo
  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"],}},
}
""",
            "tsconfig.json": '{"extends": "./tsconfig.base.json", "compilerOptions": {"strict": true}}',
            "src/lib/utils.ts": "export function cn() {}\n",
            "src/app/page.tsx": """import { cn } from "@/lib/utils"
import React from "react"
export default function Page() { cn() }
""",
        }
    )
    result = parse_repo(repo)
    assert edges(result, "imports") == {("src/app/page.tsx", "src/lib/utils.ts")}
    assert ("src/app/page.tsx::Page", "src/lib/utils.ts::cn") in edges(result, "calls")
