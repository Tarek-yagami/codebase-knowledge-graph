# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Multi-language support. Full support (definitions, imports, calls, inheritance) for Python, TypeScript/JavaScript, Vue, Go, PHP, Java, Kotlin, C#, Rust, C and C++, and basic support (definitions, inheritance, calls) for any other language tree-sitter-language-pack has a tags query for, such as Ruby, Swift and Dart.
- Mixed-language repos parse into one graph, with name resolution kept within each language.
- Calls now resolve through import aliases (`from .a import f as g`, `import * as ns`, `pkg.F()` in Go) and to functions nested in the caller.
- Dependency, hidden and test directories and files (`node_modules`, `.venv`, `*_test.go`, `*.spec.ts`, ...) are skipped during the walk.
- Full PHP support, built around Laravel: namespaces and `use` imports resolved through composer.json PSR-4, inheritance and traits, `$this->`, `self::`, `parent::` and static calls, and route files linked to the controller methods they register. Blade templates are skipped.
- Laravel resource routes link to the controller actions they cover, and invokable controllers to their `__invoke`.
- Vue single-file components: `<script setup>` code is extracted under a component node, and the template links to child components and to the handlers it calls.
- React: rendering a component in JSX counts as a call to it, and `forwardRef`/`memo`-wrapped components are recognized.
- Next.js: imports through `tsconfig.json`/`jsconfig.json` `paths` and `baseUrl` aliases resolve, including inherited configs.
- Calls on a variable resolve through its declared type (field, parameter or local) in the statically typed languages.
- Package-level visibility (Go, Java, Kotlin, C#) and wildcard imports (`import a.b.*`, `using`, `use a::*`) are part of name resolution.
- Names resolve through re-exports: TypeScript `export * from` barrels and Python package `__init__.py` imports.
- TypeScript monorepos: imports of the repo's own workspace packages resolve through each package's `exports` to its source files.
- Vue Options API components: methods, computed properties and hooks become the component's functions, and `this.x()` resolves to them.
- The 3D viewer shows each node's language.

### Changed
- The README is now a short introduction for new visitors. The research write-up moved to `docs/RESEARCH.md` and the per-language details to `docs/LANGUAGES.md`.
- Node ids are now file-path based (`pkg/models.py::User.save`) instead of dotted Python paths, so they stay unique across languages.
- Requires Python 3.11+, for `tomllib` (Cargo.toml). Python 3.10 reaches end of life in October 2026.
- Base classes no longer fall back to the first same-named class anywhere in the repo, which linked std traits like `Error` to unrelated types. They follow the same scope rules as calls.

### Fixed
- `pip install` left out the 3D viewer's page template, so an installed `codegraph-viz` had nothing to render into.
- An arrow function whose body is a single call (`() => g()`) didn't record that call.
- A function calling the same target several times produced one edge per call site.
- Nested functions were attached to the enclosing class or module instead of the function that defines them.
- Bare calls to builtins like `set()` or `next()` could resolve to an unrelated method with the same name.
- A name imported from outside the repo could resolve to a same-named definition inside it.
- Absolute Python imports now resolve under a `src/` layout.

## [0.1.0] - 2026-09-02

First real release. Everything below was built and verified against real codebases (`requests`, Django's core package), not just written.

### Added
- AST-based static analysis (`codegraph.parser`): modules, functions, classes, and their real imports/calls/inheritance edges.
- A live, click-to-explore 3D visualization of the graph.
- An MCP server (`codegraph-mcp`) exposing the graph as tools Claude Code can query directly instead of grepping files.
- A local semantic embedding layer (no API key) and a `semantic_search` tool.
- A flat-chunk-only comparison MCP server, used to test whether structure actually helps.
- Two research experiments with honestly reported results, including a null one:
  - RQ4: the graph tool measurably reduces token usage, more so on larger codebases.
  - RQ1: the graph tool did not measurably improve answer quality over flat-chunk retrieval, likely because both are driven by the same iterative agent.
- Real, documented limits of static analysis (name-collision resolution, `@overload` handling, dynamically-computed base classes).
- A test suite, CI (tests, lint, typecheck, Docker build), and a proper installable package with console scripts.

### Fixed
- Call resolution used to match by bare name with no confidence check, so `self.x()` could silently resolve to an unrelated function sharing the name. Now only resolves when there's real evidence: `self.x()` walks the enclosing class and its bases, a bare `x()` only resolves if unambiguous codebase-wide.
- `@overload`-decorated stubs were parsed as separate real functions, producing duplicate graph edges.
- `search_nodes` matched against docstrings as well as names, so common-word queries returned noisy results. Split into a precise `find_by_name` lookup and a ranked fuzzy search.
- The embedding cache is now written atomically, avoiding a real race condition if two processes launch the MCP server against the same repo at once.
