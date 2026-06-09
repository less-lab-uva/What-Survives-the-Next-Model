"""Derive cost + wall-time for the Specine code-gen oracle from the per-call logs.

Reads logs/log_{A,B}.jsonl (one line per call: start_time, end_time, input_tokens,
output_tokens) and, per prompt, sums call latency and cost (logged tokens x published price),
plus a grand total and the count of failed/unparseable problems (logs/failures_{A,B}.jsonl).
Writes logs/usage.json (overwrites -- it's a pure function of the logs).

There is no pricing API, so the rates below are Anthropic's published claude-sonnet-4-6
pricing, applied at analysis time (not during the run).

Run from the analysis directory:  python3 utils/usage.py
Paths are FIXED relative to that directory. Prerequisites checked up front, hard-abort.
"""

import os
import sys
import json

MODEL = "claude-sonnet-4-6"
PRICE_IN_PER_M = 3.0       # claude-sonnet-4-6 input  $/1M tokens
PRICE_OUT_PER_M = 15.0     # claude-sonnet-4-6 output $/1M tokens

LOGS = {"A": os.path.join("logs", "log_A.jsonl"),
        "B": os.path.join("logs", "log_B.jsonl")}
FAILURES = {"A": os.path.join("logs", "failures_A.jsonl"),
            "B": os.path.join("logs", "failures_B.jsonl")}
USAGE = os.path.join("logs", "usage.json")

# Preconditions.
for path in LOGS.values():
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path} (run main.py first)")
os.makedirs("logs", exist_ok=True)


def count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    return sum(1 for line in open(path, encoding="utf-8") if line.strip())


def summarize(tag: str) -> dict:
    rows = [json.loads(l) for l in open(LOGS[tag], encoding="utf-8") if l.strip()]
    seconds = [r["end_time"] - r["start_time"] for r in rows]
    in_tok = sum(r["input_tokens"] for r in rows)
    out_tok = sum(r["output_tokens"] for r in rows)
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    return {
        "prompt": tag,
        "model": MODEL,
        "n_calls": len(rows),
        "total_seconds": round(sum(seconds), 3),
        "mean_seconds": round(sum(seconds) / len(seconds), 3) if seconds else 0.0,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "failures": count_lines(FAILURES[tag]),
        "cost_usd": round(cost, 4),
    }


a = summarize("A")
b = summarize("B")
grand = {
    "n_calls": a["n_calls"] + b["n_calls"],
    "total_seconds": round(a["total_seconds"] + b["total_seconds"], 3),
    "input_tokens": a["input_tokens"] + b["input_tokens"],
    "output_tokens": a["output_tokens"] + b["output_tokens"],
    "failures": a["failures"] + b["failures"],
    "cost_usd": round(a["cost_usd"] + b["cost_usd"], 4),
}
usage = {
    "model": MODEL,
    "price_in_per_mtok": PRICE_IN_PER_M,
    "price_out_per_mtok": PRICE_OUT_PER_M,
    "A": a,
    "B": b,
    "grand_total": grand,
}

with open(USAGE, "w", encoding="utf-8") as f:
    json.dump(usage, f, indent=2)

print(f"Saved {USAGE}")
print(f"  A: {a['n_calls']} calls, {a['total_seconds']}s, ${a['cost_usd']}")
print(f"  B: {b['n_calls']} calls, {b['total_seconds']}s, ${b['cost_usd']}")
print(f"  grand total: {grand['n_calls']} calls, {grand['total_seconds']}s, ${grand['cost_usd']}")
