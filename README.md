<h1 align="center">Codebase Knowledge Graph</h1>

<p align="center">
  <strong>Your codebase as a world you can fly into.</strong>
  <br />
  Any repo becomes an explorable 3D knowledge graph, and Claude Code gets the same map through MCP to answer questions without reading every file.
</p>

<p align="center">
  <a href="https://tarek-yagami.github.io/codebase-knowledge-graph/"><img src="https://img.shields.io/badge/Live_Demo-00c853" alt="Live demo" /></a>
  <a href="https://github.com/Tarek-yagami/codebase-knowledge-graph/actions/workflows/tests.yml"><img src="https://github.com/Tarek-yagami/codebase-knowledge-graph/actions/workflows/tests.yml/badge.svg" alt="tests" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
</p>

<p align="center">
  <img src="docs/screenshots/overview.png" width="48%" alt="Module-level overview of the requests library as a 3D graph">
  <img src="docs/screenshots/inside_module.png" width="48%" alt="Inside the sessions module, showing its classes and functions inside a translucent shell">
</p>

---

**You just opened a codebase you've never seen. Where does anything live, and what breaks if you touch it?**

Point this at any repo and it reads the code file by file, tracing every import, call and base class. You get a 3D map you can fly through one module at a time. Claude Code gets the same map as a set of tools, so "who calls this?" becomes one lookup instead of a search through dozens of files.

> **[Try the live demo](https://tarek-yagami.github.io/codebase-knowledge-graph/)** with the `requests` library, pre-built and running in your browser. Nothing to install.

## What you can do

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Fly through your code</h3>
      <p>Every module is its own world. Step inside to see its classes and functions, with lines for the imports, calls and inheritance between them.</p>
    </td>
    <td width="50%" valign="top">
      <h3>Ask Claude Code about it</h3>
      <p>An MCP server lets Claude Code look up who calls a function or what a module depends on directly, and spend fewer tokens getting there.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>See what a change affects</h3>
      <p>Hand it the files you changed and get back everything that depends on them, directly or through a chain of calls and imports.</p>
    </td>
    <td width="50%" valign="top">
      <h3>Know where to start reading</h3>
      <p>Get the modules in reading order, each one after the code it builds on, so an unfamiliar project makes sense from the ground up.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>Search by meaning</h3>
      <p>Ask for "code that retries a failed request" and find it even when nothing is named retry. Runs on a small local model, with no API key.</p>
    </td>
    <td width="50%" valign="top">
      <h3>Works on real stacks</h3>
      <p>Full support for 11 languages plus Laravel, React, Next.js and Vue, and a repo mixing several of them still comes out as one graph.</p>
    </td>
  </tr>
</table>

## Quick start

```bash
pip install git+https://github.com/Tarek-yagami/codebase-knowledge-graph.git
codegraph-viz /path/to/your/project
```

That writes `data/graph3d.html`, which you open in your browser. Click a module to step inside it, and click the empty space around it to step back out. The first install takes a while, since semantic search pulls in PyTorch.

To give Claude Code the map, add this to `.mcp.json` in the project you're working on:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph-mcp",
      "args": ["/absolute/path/to/your/project"]
    }
  }
}
```

Then run `claude` in that folder and approve the `codegraph` server when it asks. The [usage guide](docs/USAGE.md) covers Docker, every tool the server offers, and troubleshooting.

## Languages and frameworks

| | |
|---|---|
| **Full support** | Python, TypeScript, JavaScript, Vue, Go, PHP, Java, Kotlin, C#, Rust, C, C++ |
| **Frameworks** | React, Next.js, Laravel, Vue, TypeScript monorepos |
| **Basic support** | Ruby, Swift, Dart, Scala, Lua, Elixir, and most other languages tree-sitter can read |

With full support, imports, calls and inheritance are all linked across files. Basic support gets definitions, inheritance and calls, but doesn't follow imports yet. See [how each language is handled](docs/LANGUAGES.md) for the details.

## How it works

Everything comes from reading the source. Nothing gets run, and no AI guesses at the structure. Python goes through the standard library's `ast` module and every other language through [tree-sitter](https://tree-sitter.github.io/). Each file reports what it defines and what it refers to, and one shared resolver links those references across the repo using the file's imports, its package and the declared types of its variables. When a name could mean two different things it stays unlinked, so every edge you see is one you can trust.

## Does it actually help?

This project started as a research question and was tested on real codebases. Claude Code with the graph used about 5% fewer tokens on a small library and 14% fewer on Django, and it reached structural answers in fewer steps. Its answers weren't more accurate than with plain semantic search, though: both found all 21 `save()` methods in Django. The payoff is cheaper exploration and a map you can actually see. The [research write-up](docs/RESEARCH.md) has the full story, including what didn't work.

## Documentation

- [Usage guide](docs/USAGE.md): install options, Claude Code setup, tool reference, troubleshooting
- [How each language is handled](docs/LANGUAGES.md): resolution rules, per-language details, tested repos
- [Research findings](docs/RESEARCH.md): the experiments and what they showed
- [Changelog](CHANGELOG.md)

## License

MIT, see [LICENSE](LICENSE).
