# LangChain Docs Freshness Monitor

*Work in progress.*

## Origin

While digging through [`langchain-ai/docs`](https://github.com/langchain-ai/docs) to understand how a fast-moving AI library manages its own documentation, I found [issue #1195](https://github.com/langchain-ai/docs/issues/1195): LangChain's v1.0 migration (Oct 30, 2025) silently broke 31 doc files that still used the removed `langchain.retrievers` import path. It was caught and fixed the same day — but only because a contributor happened to run a manual `grep` search and noticed. Nothing automated flagged it.

That's the actual gap: detection depended on someone happening to look. The question — *how would a RAG system catch this on its own, without a human getting lucky?* — became this project. The incident (issue [#1195](https://github.com/langchain-ai/docs/issues/1195) → fix [#1196](https://github.com/langchain-ai/docs/pull/1196)) is now closed, but it left an exact, real before/after commit pair that serves as ground truth — see [`data/ground_truth/incident_001_v1_retriever_imports.json`](data/ground_truth/incident_001_v1_retriever_imports.json).

## What this is

A RAG system built over `langchain-ai/docs`, replayed across its real commit history spanning the v0.3 → v1.0 migration, with an evaluation and monitoring layer that detects when a frozen index starts serving deprecated-API answers — instead of another "chat with your PDFs" demo.

Grounded entirely in real, checkable artifacts:
- the real incident: [#1195](https://github.com/langchain-ai/docs/issues/1195) → [#1196](https://github.com/langchain-ai/docs/pull/1196), with an exact before/after commit pair
- real commercial validation: [Context7](https://context7.com), the most popular MCP server of 2026, exists specifically to stop LLMs generating code against outdated library docs
- real academic grounding: an [ICSE 2025 study](https://arxiv.org/abs/2406.09834) found frontier LLMs' API-usage plausibility falls below 30% as libraries evolve

## Research questions

1. After a real breaking migration, how much does a frozen index's deprecated-API rate actually spike — and can a deterministic evaluator catch it without a human?
2. Where does a deterministic ground-truth check agree/disagree with an LLM-as-judge on staleness?
3. Given a cost model for reindexing, what cadence actually minimizes staleness exposure per dollar?

## Status

Scaffolding. Data pipeline (commit snapshots + ground-truth mining from #1195) in progress.

## Explicitly out of scope

No multi-tool agent/planner, no fine-tuning, no multi-repo generality, no hyperparameter grid search, no custom vector DB, no real-time ingestion. See project notes for full rationale.
