# How each language is handled

The details behind the languages table in the [README](../README.md).

Every file goes to an extractor for its language, and each extractor only reports what it can see in that one file: definitions, import specs, call sites, base classes. One shared resolver then links those names across the whole repo with the same confidence rules for every language. So a Python backend and a TypeScript frontend in one repo end up in one graph, and a Python `helper()` never resolves to a TypeScript `helper`.

| Support | Languages | What you get |
|---|---|---|
| Full | Python, TypeScript/JavaScript (incl. TSX/JSX), Vue, Go, PHP, Java, Kotlin, C#, Rust, C, C++ | Definitions, imports resolved to files, calls, inheritance |
| Basic | Ruby, Swift, Dart, Scala, Lua, Elixir, and anything else [tree-sitter-language-pack](https://github.com/xberg-io/tree-sitter-language-pack) ships a tags query for | Definitions with their nesting, inheritance, and calls within a file or to unambiguous names, but no imports |

Python uses the standard library's `ast` module. Everything else uses tree-sitter, whose grammars download the first time a language shows up.

A name resolves through the most specific scope that has it: the module it was imported from (following re-exports like an `index.ts` barrel or a package `__init__.py`), the same file, the same package (Go, Java, Kotlin and C# files in one package see each other without importing), namespaces opened by wildcard imports (`import a.b.*`, C#'s `using`, Rust's `use a::*`), and only then a unique name anywhere in the repo. In statically typed languages a call on a variable also resolves through its declared type, so `repo.findById()` reaches `OwnerRepository.findById` when `repo` is declared as an `OwnerRepository`, whether it's a field, a parameter or a local. That works in Java, C#, C++, Rust, Swift and the other tree-sitter languages without per-language code, because their grammars mark declarations the same way.

Some details differ by language:

- **Go:** methods attach to their receiver type even when it's declared in another file of the package, and embedded structs count as inheritance since their methods get promoted.
- **Rust:** `mod` and `use` paths (`crate::`, `self::`, `super::`, other crates in the Cargo workspace) map to files the way rustc lays modules out, including custom crate roots from `Cargo.toml`. `impl Trait for Type` makes Type inherit Trait, and a qualified std trait like `std::fmt::Debug` never lands on a same-named type in the repo.
- **C and C++:** `#include`s resolve next to the including file, else by a unique path suffix. Methods defined outside their class (`void Foo::bar()`) attach to Foo wherever it's declared, header prototypes don't count as definitions, and a `.h` file is read as C or C++ by what it contains.
- **Kotlin and Java** share import resolution, so an Android project's Kotlin can import its Java classes and the other way around.

The frameworks people actually build with are covered too:

- **React:** rendering `<Button />` counts as a call to the `Button` component, and components wrapped in `forwardRef` or `memo` are still recognized as components.
- **Next.js and TypeScript monorepos:** `@/components/...` style imports resolve through the `paths` and `baseUrl` in `tsconfig.json` or `jsconfig.json`, including configs that inherit them through `extends`. A monorepo importing its own packages by name (`import { z } from "zod/v4"`) resolves through each package's `exports` to its source files.
- **Laravel:** class names expand through each file's namespace and `use` statements, then map to files with composer.json's PSR-4 rules, the same way PHP finds them at runtime. `parent::`, `self::` and static calls like `User::find()` resolve, traits count as inheritance, and route files link straight to the controller methods they register, whether written as `[UserController::class, 'index']`, a resource route (`Route::apiResource('photos', PhotoController::class)` links to the actions the controller defines) or an invokable controller (linked to its `__invoke`). Framework classes from `vendor/` stay external.
- **Vue:** each single-file component becomes a node named after its file. It holds the functions from its `<script setup>`, or the methods, computed properties and hooks of an Options API component, where `this.save()` resolves to the component's own method. The template links to the child components it renders (`<SongItem>` and `<song-item>` alike) and to the handlers and functions it calls (`@play="onPlay"`).

Node ids are file paths, so they stay unique across languages: `src/requests/sessions.py` for a module and `src/requests/sessions.py::Session.send` for anything defined in it.

Tested on real repos, with parse times:

| Repo | What it is | Nodes | Parse |
|---|---|---|---|
| `requests` | Python library | 316 | 0.2s |
| `gin` | Go web framework | 661 | 0.1s |
| `zod` | TypeScript monorepo | 2,494 | 1.1s |
| `taxonomy` | Next.js app | 419 | 0.3s |
| `koel` | Laravel app with a Vue frontend | 7,176 | 2.8s |
| `spring-petclinic` | Java Spring app | 145 | 0.1s |
| `CleanArchitecture` | C# ASP.NET app | 403 | 0.3s |
| `ripgrep` | Rust Cargo workspace | 3,521 | 1.3s |
| `spdlog` | C++ library | 2,055 | 1.1s |
| `redis` | C server | 11,043 | 5.8s |
