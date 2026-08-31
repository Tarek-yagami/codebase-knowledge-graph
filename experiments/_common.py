"""Shared helpers for running Claude Code headless against a target repo
with a given MCP tool configuration, and for comparing two conditions'
results. Used by every experiment under experiments/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = shutil.which("claude")
PYTHON_BIN = ROOT / ".venv" / "Scripts" / "python.exe"


def mcp_config(server_name: str, server_script: str, repo: Path) -> str:
    """Builds an inline --mcp-config JSON string for one of our MCP servers
    in src/codegraph_mcp/, pointed at the given target repo.
    """
    return json.dumps({
        "mcpServers": {
            server_name: {
                "command": str(PYTHON_BIN),
                "args": [str(ROOT / "src" / "codegraph_mcp" / server_script), str(repo)],
            }
        }
    })


def run_claude(question: str, repo: Path, tools: str, mcp_config_json: str | None = None, timeout: int = 180) -> dict:
    """Runs one headless Claude Code call and returns the parsed JSON result,
    or {"error": ...} if the call itself failed.
    """
    if not CLAUDE_BIN:
        raise SystemExit("claude CLI not found on PATH")
    cmd = [CLAUDE_BIN, "-p", question, "--output-format", "json", "--strict-mcp-config", "--no-session-persistence"]
    if mcp_config_json:
        cmd += ["--mcp-config", mcp_config_json]
    cmd += ["--allowedTools", tools]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:]}
    return json.loads(proc.stdout)


def run_two_conditions(questions: list[str], out_path: Path, run_a, run_b, label_a: str, label_b: str) -> None:
    """Runs each question through both condition functions (each takes just
    the question string), saving after every question so an interrupted run
    doesn't lose progress already made. Skips questions already present in
    out_path, so it's safe to re-run after adding new questions.
    """
    results = json.loads(out_path.read_text()) if out_path.exists() else []
    done = {r["question"] for r in results}
    for q in questions:
        if q in done:
            continue
        print(f"[{label_a}] {q[:70]}")
        a = run_a(q)
        print(f"[{label_b}] {q[:70]}")
        b = run_b(q)
        results.append({"question": q, label_a: a, label_b: b})
        out_path.write_text(json.dumps(results, indent=2))
    print(f"\nDone. {len(results)} questions written to {out_path}")


def stats(run: dict) -> dict:
    """Pulls the comparable numbers out of one claude -p JSON result.
    input+output tokens only - cache_creation/cache_read are dominated by
    the fixed cost of loading the system prompt and tool definitions, which
    doesn't scale with how much exploring actually happened.
    """
    if "error" in run:
        return {"cost": None, "turns": None, "tokens": None}
    usage = run.get("usage", {})
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return {"cost": run.get("total_cost_usd"), "turns": run.get("num_turns"), "tokens": tokens}


def summarize(results_path: Path, label_a: str, label_b: str) -> None:
    """Prints a side-by-side comparison of two conditions' results: cost,
    turns, tokens, and both answers, so quality can be checked by eye
    alongside the numbers.
    """
    results = json.loads(results_path.read_text())
    totals = {label_a: {"cost": 0.0, "tokens": 0}, label_b: {"cost": 0.0, "tokens": 0}}

    for r in results:
        a, b = stats(r[label_a]), stats(r[label_b])
        print("=" * 100)
        print(f"Q: {r['question']}")
        print(f"  {label_a}: {a['tokens']} tokens (input+output), {a['turns']} turns, ${a['cost']} total")
        print(f"  {label_b}: {b['tokens']} tokens (input+output), {b['turns']} turns, ${b['cost']} total")
        if a["tokens"] and b["tokens"]:
            diff = (1 - b["tokens"] / a["tokens"]) * 100
            print(f"  -> {label_b} used {diff:.0f}% {'fewer' if diff > 0 else 'more'} tokens, "
                  f"{a['turns'] - b['turns']:+d} turns")
        print(f"  [{label_a}] {r[label_a].get('result', '(error)')}")
        print(f"  [{label_b}] {r[label_b].get('result', '(error)')}")

        for label, s in ((label_a, a), (label_b, b)):
            if s["cost"]:
                totals[label]["cost"] += s["cost"]
            if s["tokens"]:
                totals[label]["tokens"] += s["tokens"]

    print("=" * 100)
    print(f"TOTAL tokens (input+output): {label_a} {totals[label_a]['tokens']}  vs  {label_b} {totals[label_b]['tokens']}")
    print(f"TOTAL cost (dominated by fixed per-call cache overhead, not exploration): "
          f"{label_a} ${totals[label_a]['cost']:.4f}  vs  {label_b} ${totals[label_b]['cost']:.4f}")
    if totals[label_a]["tokens"]:
        savings = (1 - totals[label_b]["tokens"] / totals[label_a]["tokens"]) * 100
        print(f"Overall: {label_b} used {savings:.0f}% {'fewer' if savings > 0 else 'more'} tokens than {label_a}")
