---
description: Show everything that depends on your uncommitted changes
argument-hint: "[files or git range, defaults to uncommitted changes]"
allowed-tools: Bash(git diff:*), Bash(git status:*)
---

Find out what the user's changes could affect.

1. Get the changed files. If `$ARGUMENTS` names files, use those. If it names a git range (like `main...HEAD`), run `git diff --name-only $ARGUMENTS`. Otherwise combine `git diff --name-only HEAD` with the untracked files from `git status --porcelain`.
2. Call the codegraph `impact_of_changes` tool with those paths, relative to the repo root.
3. Report what it found, grouped by file: the changed functions and classes, then everything that depends on them, noting whether each dependency is direct or reached through a chain and whether it's a call, import or inheritance. Lead with the parts most likely to break. Keep it short, and say plainly if nothing depends on the changes.
