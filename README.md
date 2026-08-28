# Codebase Knowledge Graph

*Work in progress.*

## What this is

An agent that explores a real, unfamiliar codebase and builds a live, explorable knowledge graph of it — not a static diagram, but an actual graph you can click through: nodes are files/functions/classes, edges are real relationships (imports, calls, class inheritance) recovered by static analysis, plus semantic "related to" edges from embeddings. You watch it get built in real time as the agent reads through the repo, then you can ask real questions about the codebase and watch it answer by traversing the graph and retrieving from it — [GraphRAG](https://arxiv.org/abs/2404.16130) rather than plain flat-chunk RAG.

## The real problem

Understanding an unfamiliar codebase is slow, and it's a problem almost every developer has felt firsthand. Plain text-chunk RAG treats a codebase as a bag of documents and loses the thing that actually matters — structure: who calls whom, what depends on what, what would break if you changed this function. A knowledge graph captures that structure explicitly. Combining it with semantic retrieval lets a system answer both structural questions ("what would break if I change this") and conceptual ones ("where's the logic that handles X") — something flat RAG systematically gets wrong.

This is a real, current technique (Microsoft's GraphRAG research) and a real, validated need (Sourcegraph Cody and GitHub's code navigation both exist because of it) — not an invented scenario.

## Research questions

1. Does structural graph traversal + semantic retrieval answer real "how does X relate to Y" questions about a codebase better than plain flat-chunk RAG over the same code?
2. How much of a codebase's real structure can static analysis recover automatically, and where does it break down (dynamic dispatch, reflection, metaprogramming)?
3. Can the exploration be visible *and* fast enough to stay demo-friendly on a real, non-trivial repo?

## Status

Scaffolding. Pivoted from an earlier RAG-freshness-monitoring direction (see git history) once it became clear that direction's payoff was a dashboard of scores rather than something worth watching get built.

## Explicitly out of scope (for now)

- Multi-language parsing — Python only to start.
- Perfect call-graph precision for dynamic/reflective code — static analysis limits are acknowledged, not solved.
- Hosted multi-user deployment — a strong local/single-demo tool, not a SaaS.
- Full incremental-update engine for the graph — nice-to-have, not core.
- Fine-tuning anything.
