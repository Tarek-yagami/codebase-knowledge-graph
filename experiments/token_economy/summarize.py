"""Prints a side-by-side comparison of the baseline vs. graph-backed runs
from run_experiment.py: cost, turns, token usage, and both answers so
quality can be checked by eye alongside the numbers.
"""

import json
import sys
from pathlib import Path

RESULTS_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results.json"


def stats(run: dict) -> dict:
    if "error" in run:
        return {"cost": None, "turns": None, "tokens": None}
    usage = run.get("usage", {})
    # input/output only - cache_creation and cache_read are dominated by the
    # fixed cost of loading the system prompt and tool definitions, which is
    # roughly constant regardless of how much exploring actually happened,
    # so including them buries the actual signal under fixed overhead.
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return {"cost": run.get("total_cost_usd"), "turns": run.get("num_turns"), "tokens": tokens}


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text())

    total_cost = {"baseline": 0.0, "graph": 0.0}
    total_tokens = {"baseline": 0, "graph": 0}

    for r in results:
        b, g = stats(r["baseline"]), stats(r["graph"])
        print("=" * 100)
        print(f"Q: {r['question']}")
        print(f"  baseline: {b['tokens']} tokens (input+output), {b['turns']} turns, ${b['cost']} total")
        print(f"  graph:    {g['tokens']} tokens (input+output), {g['turns']} turns, ${g['cost']} total")
        if b["tokens"] and g["tokens"]:
            diff = (1 - g["tokens"] / b["tokens"]) * 100
            print(f"  -> graph used {diff:.0f}% {'fewer' if diff > 0 else 'more'} tokens, {b['turns'] - g['turns']:+d} turns")
        print(f"  [baseline answer] {r['baseline'].get('result', '(error)')}")
        print(f"  [graph answer]    {r['graph'].get('result', '(error)')}")

        if b["cost"]:
            total_cost["baseline"] += b["cost"]
        if g["cost"]:
            total_cost["graph"] += g["cost"]
        if b["tokens"]:
            total_tokens["baseline"] += b["tokens"]
        if g["tokens"]:
            total_tokens["graph"] += g["tokens"]

    print("=" * 100)
    print(f"TOTAL tokens (input+output): baseline {total_tokens['baseline']}  vs  graph {total_tokens['graph']}")
    print(f"TOTAL cost (dominated by fixed per-call cache overhead, not exploration): "
          f"baseline ${total_cost['baseline']:.4f}  vs  graph ${total_cost['graph']:.4f}")
    if total_tokens["baseline"]:
        savings = (1 - total_tokens["graph"] / total_tokens["baseline"]) * 100
        print(f"Overall: graph used {savings:.0f}% {'fewer' if savings > 0 else 'more'} tokens than baseline")


if __name__ == "__main__":
    main()
