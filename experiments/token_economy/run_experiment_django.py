"""Same experiment as run_experiment.py, run against Django's core package
instead of requests, to test whether the graph's advantage grows on a much
larger, real codebase (846 files vs. requests' 21).

Usage: python run_experiment_django.py
"""

import json
import shutil
import subprocess
from pathlib import Path

CLAUDE_BIN = shutil.which("claude")
if not CLAUDE_BIN:
    raise SystemExit("claude CLI not found on PATH")

ROOT = Path(__file__).resolve().parent.parent.parent
REPO = ROOT / "data" / "repos" / "django" / "django"
OUT_PATH = Path(__file__).resolve().parent / "results_django.json"

MCP_CONFIG_JSON = json.dumps({
    "mcpServers": {
        "codegraph": {
            "command": str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "args": [str(ROOT / "src" / "codegraph_mcp" / "server.py"), str(REPO)],
        }
    }
})

BASE_TOOLS = "Read Grep Glob"
MCP_TOOLS = BASE_TOOLS + (
    " mcp__codegraph__list_modules mcp__codegraph__get_node mcp__codegraph__list_children"
    " mcp__codegraph__get_relationships mcp__codegraph__search_nodes"
)

QUESTIONS = [
    "What's the full inheritance chain for HttpResponseNotFound up to its base class, and which sibling response classes share that same base? Watch out for classes that look like siblings but actually aren't.",
    "What does the Manager class in django.db.models.manager inherit from, and why might that be hard to determine automatically just from reading the code structure?",
    "How many different classes define a save() method across this codebase, and are they related to each other through inheritance?",
    "How many different places define a clean() method, and what do they have in common?",
    "What's the relationship between BaseManager, Manager, and QuerySet in django.db.models?",
    "What does EmptyManager inherit from, and how does that compare to how the regular Manager class is defined?",
]


def run(question: str, use_mcp: bool) -> dict:
    cmd = [CLAUDE_BIN, "-p", question, "--output-format", "json", "--strict-mcp-config", "--no-session-persistence"]
    if use_mcp:
        cmd += ["--mcp-config", MCP_CONFIG_JSON]
    cmd += ["--allowedTools", MCP_TOOLS if use_mcp else BASE_TOOLS]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:]}
    return json.loads(proc.stdout)


def main() -> None:
    results = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else []
    done_questions = {r["question"] for r in results}

    for q in QUESTIONS:
        if q in done_questions:
            continue
        print(f"[baseline] {q[:70]}")
        baseline = run(q, use_mcp=False)
        print(f"[graph]    {q[:70]}")
        graph = run(q, use_mcp=True)
        results.append({"question": q, "baseline": baseline, "graph": graph})
        OUT_PATH.write_text(json.dumps(results, indent=2))

    print(f"\nDone. {len(results)} questions written to {OUT_PATH}")


if __name__ == "__main__":
    main()
