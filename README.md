# Codebase Knowledge Graph

*Work in progress.*

## What this is

An agent that explores a real, unfamiliar codebase and builds a live, explorable knowledge graph of it. You can click through the graph as it forms: nodes are the files, functions, and classes in the repo, and edges capture how they actually relate to each other, through imports, function calls, and class inheritance recovered by static analysis, plus semantic similarity from embeddings. Once the graph exists, you can ask questions about the codebase and get an answer built by walking the graph and retrieving from it, which is the idea behind [GraphRAG](https://arxiv.org/abs/2404.16130) rather than the usual flat-chunk RAG approach.

## The real problem

Understanding an unfamiliar codebase is slow, and it's something almost every developer has felt firsthand. Plain text-chunk RAG treats a codebase as a pile of documents and loses the thing that actually matters, which is the structure: who calls whom, what depends on what, what would break if you changed this one function. A knowledge graph keeps that structure visible, so once you combine it with semantic retrieval the system can answer structural questions like "what would break if I change this" alongside conceptual ones like "where's the logic that handles X", right where flat RAG tends to fall apart.

Microsoft's GraphRAG research treats this as a real, current technique, and tools like Sourcegraph Cody and GitHub's code navigation exist because the need behind it is real too.

## Research questions

1. Does structural graph traversal plus semantic retrieval answer real "how does X relate to Y" questions about a codebase better than plain flat-chunk RAG over the same code?
2. How much of a codebase's real structure can static analysis recover automatically, and where does it break down, say with dynamic dispatch, reflection, or metaprogramming?
3. Can the exploration stay visible and still be fast enough to hold up in a demo on a real, non-trivial repo?
4. How much cheaper is answering a real codebase question through the pre-built graph compared to a general coding agent that explores the repo from scratch with only file tools, at the same answer quality? Static analysis recovers structure for free, so the graph should be trading a near-zero indexing cost against tokens a general agent burns doing that same mechanical exploration by hand, and that difference should widen the more questions get asked against the same codebase.

## Status

The static analysis pipeline and the 3D graph viewer already work end to end, tested against the real `requests` library. It parses a repo into modules, functions, and classes, builds the graph, and renders it as a scene you can click through in 3D, where each node opens into its own self-contained view of what's inside it.

The graph is also exposed as an MCP server (`src/codegraph_mcp/server.py`), so Claude Code itself can call it directly, asking who calls a function or what a module depends on, instead of reading and grepping through files to work that out by hand. Claude Code is the actual agent here, just handed a cheaper tool for the one kind of question a file-reading agent is worst at.

This has already been tested live: asking Claude Code real questions about `requests` through the connected MCP server, it consistently reached for the graph tool instead of opening files, and that testing surfaced two genuine gaps in the static analysis, which are now fixed. Call resolution used to match by name alone with no real confidence behind it, so `self.request()` inside one method could silently resolve to an unrelated function elsewhere that happened to share the name. It now only resolves a call when there's real evidence for where it goes: `self.x()` walks the enclosing class and its bases, a bare `x()` only resolves if the name is unambiguous across the whole codebase, and everything else is left honestly unresolved rather than guessed at. Separately, `@overload`-decorated type stubs were being parsed as if they were real, separate functions, which got cleaned up too.

What's still missing is the semantic embedding layer, a flat-RAG baseline to compare against, and the actual experiment measuring how much cheaper answering codebase questions gets once Claude Code has this tool available.

## Out of scope for now

Python only, rather than trying to parse multiple languages from the start. Static analysis has real limits around dynamic dispatch and reflection, and those limits are being accepted rather than solved. The goal is a strong local demo, not a hosted multi-user product, so there's no deployment work planned. The graph doesn't need a full incremental-update engine either, that's a nice-to-have rather than something the project depends on. And there's no fine-tuning anywhere in this.
