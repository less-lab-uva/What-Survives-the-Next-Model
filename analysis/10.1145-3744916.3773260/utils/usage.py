"""Derive cost + wall-time for the IntentFix run from the per-call logs.

Covers BOTH phases that make paid calls:
  - generation (main.py)     -> logs/log_A.jsonl,      logs/log_B.jsonl
  - evaluation (evaluator.py) -> logs/eval_log_A.jsonl, logs/eval_log_B.jsonl
Each line is one call (start_time, end_time, input_tokens, output_tokens). Per prompt and phase we
sum call latency and cost (logged tokens x published price); then a generation subtotal, an
evaluation subtotal, and a grand total. Writes logs/usage.json (overwrites -- a pure function of the
logs, safe to recompute any time).

The generation logs are required (run main.py first). The evaluation logs are optional: if the
evaluator hasn't run yet, its numbers are zero and `evaluation.ran` is false.

There is no pricing API, so the rates below are Anthropic's published claude-sonnet-4-6 pricing,
applied at analysis time. Cost is computed HERE only -- main.py / evaluator.py record tokens +
runtime, not cost.

Run from the analysis directory:  python3 utils/usage.py
Paths are FIXED relative to that directory. Prerequisites checked up front, hard-abort.
"""

import os
import sys
import json

MODEL = "claude-sonnet-4-6"
PRICE_IN_PER_M = 3.0       # claude-sonnet-4-6 input  $/1M tokens
PRICE_OUT_PER_M = 15.0     # claude-sonnet-4-6 output $/1M tokens

LOG_A = os.path.join("logs", "log_A.jsonl")            # generation, prompt A
LOG_B = os.path.join("logs", "log_B.jsonl")            # generation, prompt B
EVAL_LOG_A = os.path.join("logs", "eval_log_A.jsonl")  # evaluation, prompt A
EVAL_LOG_B = os.path.join("logs", "eval_log_B.jsonl")  # evaluation, prompt B
USAGE = os.path.join("logs", "usage.json")

# Preconditions -- generation logs are required; evaluation logs are optional.
if not os.path.exists(LOG_A):
    sys.exit(f"ABORT: missing {LOG_A} (run main.py first)")
if not os.path.exists(LOG_B):
    sys.exit(f"ABORT: missing {LOG_B} (run main.py first)")


def summarize(log_file, label):
    """One log file -> its call count, latency, tokens, and cost. Zeros if the file is absent."""
    if not os.path.exists(log_file):
        return {"prompt": label, "model": MODEL, "present": False, "n_calls": 0,
                "total_seconds": 0.0, "mean_seconds": 0.0,
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    rows = [json.loads(line) for line in open(log_file, encoding="utf-8") if line.strip()]
    seconds = [r["end_time"] - r["start_time"] for r in rows]
    in_tok = sum(r["input_tokens"] for r in rows)
    out_tok = sum(r["output_tokens"] for r in rows)
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    return {
        "prompt": label, "model": MODEL, "present": True, "n_calls": len(rows),
        "total_seconds": round(sum(seconds), 3),
        "mean_seconds": round(sum(seconds) / len(seconds), 3) if seconds else 0.0,
        "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": round(cost, 4),
    }


def total(scope, parts):
    """Sum a list of per-log summaries into one scope total."""
    return {
        "scope": scope,
        "n_calls": sum(p["n_calls"] for p in parts),
        "total_seconds": round(sum(p["total_seconds"] for p in parts), 3),
        "input_tokens": sum(p["input_tokens"] for p in parts),
        "output_tokens": sum(p["output_tokens"] for p in parts),
        "cost_usd": round(sum(p["cost_usd"] for p in parts), 4),
    }


gen_a = summarize(LOG_A, "A")
gen_b = summarize(LOG_B, "B")
eval_a = summarize(EVAL_LOG_A, "A")
eval_b = summarize(EVAL_LOG_B, "B")

generation = total("generation", [gen_a, gen_b])
evaluation = total("evaluation", [eval_a, eval_b])
grand = total("grand_total", [gen_a, gen_b, eval_a, eval_b])

usage = {
    "model": MODEL,
    "price_in_per_mtok": PRICE_IN_PER_M,
    "price_out_per_mtok": PRICE_OUT_PER_M,
    "generation": {"A": gen_a, "B": gen_b, "subtotal": generation},
    "evaluation": {"A": eval_a, "B": eval_b, "subtotal": evaluation,
                   "ran": eval_a["present"] or eval_b["present"]},
    "grand_total": grand,
}

with open(USAGE, "w", encoding="utf-8") as f:
    json.dump(usage, f, indent=2)

print(f"Saved {USAGE}")
print(f"  generation: {generation['n_calls']} calls, {generation['total_seconds']}s, ${generation['cost_usd']}")
if usage["evaluation"]["ran"]:
    print(f"  evaluation: {evaluation['n_calls']} calls, {evaluation['total_seconds']}s, ${evaluation['cost_usd']}")
else:
    print("  evaluation: not run yet (no eval logs)")
print(f"  grand total: {grand['n_calls']} calls, {grand['total_seconds']}s, ${grand['cost_usd']}")
