---
description: Open this codebase as an explorable 3D knowledge graph in the browser
argument-hint: "[path, defaults to the current project]"
allowed-tools: Bash(uvx:*)
---

Render the codebase at `$ARGUMENTS` (or the current project directory if no path was given) as a 3D knowledge graph by running:

```
uvx --from git+https://github.com/Tarek-yagami/codebase-knowledge-graph codegraph-viz <path>
```

It parses the repo, writes the page to codegraph's cache folder and opens it in the browser. The first run takes a minute while `uvx` fetches the package. When it finishes, tell the user where the page was written and how to use it in one or two sentences: click a module to step inside it, click the empty space around it to step back out, and the lines are imports, calls and inheritance. Don't read or summarize the generated HTML.
