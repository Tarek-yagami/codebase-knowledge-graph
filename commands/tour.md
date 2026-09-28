---
description: A guided tour of this codebase, in the order its parts build on each other
argument-hint: "[area to focus on, optional]"
---

Give the user a guided tour of this codebase, using the codegraph tools rather than reading files wherever they can answer.

1. Call `suggested_reading_order` to get the modules ordered so each comes after what it depends on. If `$ARGUMENTS` names an area (a folder, feature or concept), keep only the modules that belong to it, using `search_nodes` or `semantic_search` to find them.
2. Pick the handful of modules that matter most, the foundations early in the order and the ones many others depend on (check with `get_relationships`), and skip trivial ones like empty `__init__` files.
3. For each, use `get_node` and `list_children` to explain in a few sentences what it's for, its key classes and functions, and how it connects to the stops before it.
4. End with where to look next for the most common kinds of change.

Keep the tour readable in a couple of minutes, with file paths so the user can jump to the code.
