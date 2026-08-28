"""Runs the same real questions about the `requests` codebase through Claude
Code headless twice: once with only generic file tools, once with the
codegraph MCP server also available. Saves both full results so the token
usage and answer quality can be compared side by side.

Usage: python run_experiment.py
"""

import json
import shutil
import subprocess
from pathlib import Path

CLAUDE_BIN = shutil.which("claude")
if not CLAUDE_BIN:
    raise SystemExit("claude CLI not found on PATH")

ROOT = Path(__file__).resolve().parent.parent.parent
REPO = ROOT / "data" / "repos" / "requests" / "src" / "requests"
OUT_PATH = Path(__file__).resolve().parent / "results.json"

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
    "Compare BaseAdapter.send and Session.send: what does each one call, and how are they related?",
    "What does ConnectTimeout inherit from, and if I catch ConnectionError, would that also catch a ConnectTimeout?",
    "Does HTTPProxyAuth define its own __init__ method, or does it inherit one? Where does it actually come from?",
    "What's the difference between the top-level requests.get and Session.get, and what does each one call internally?",
    "What would break if I changed the signature of Session.prepare_request?",
    "Which classes implement a close() method, and how are they related to each other?",
]


def run(question: str, use_mcp: bool) -> dict:
    cmd = [CLAUDE_BIN, "-p", question, "--output-format", "json", "--strict-mcp-config", "--no-session-persistence"]
    if use_mcp:
        cmd += ["--mcp-config", MCP_CONFIG_JSON]
    cmd += ["--allowedTools", MCP_TOOLS if use_mcp else BASE_TOOLS]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=180)
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
