# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
