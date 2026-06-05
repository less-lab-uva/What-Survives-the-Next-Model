"""Derive resource usage (call latency + cost) for the RQ2 oracle runs.

Separate from evaluator.py (which scores predictions). Reads the raw per-call logs
(outputs/log-*.csv) and derives, per prompt variant, total/mean call seconds
(end_time - start_time) and total cost (logged token counts x published price).
Writes results/usage.json.

There is no pricing API, so the rates below are Anthropic's published pricing for
claude-sonnet-4-6 (applied here, at analysis time, not during the run).

Like main.py: fixed paths, prerequisites checked up front, hard-abort, no overwrite.
"""

import os
import sys
import json
import pandas as pd

PRICE_IN_PER_M = 3.0    # claude-sonnet-4-6 input  $ per 1M tokens
PRICE_OUT_PER_M = 15.0  # claude-sonnet-4-6 output $ per 1M tokens

LOG_A = "outputs/log-claude-sonnet-4-6-a-our.csv"
LOG_B = "outputs/log-claude-sonnet-4-6-b-our.csv"

USAGE = "results/usage.json"

REQUIRED = {"start_time", "end_time", "input_tokens", "output_tokens"}

# Preconditions.
if not os.path.exists(LOG_A):
    sys.exit(f"ABORT: missing {LOG_A} (run main.py first)")
if not os.path.exists(LOG_B):
    sys.exit(f"ABORT: missing {LOG_B} (run main.py first)")
if os.path.exists(USAGE):
    sys.exit(f"ABORT: output already exists: {USAGE}")

os.makedirs("results", exist_ok=True)


def summarize(log_csv):
    df = pd.read_csv(log_csv)
    if not REQUIRED.issubset(df.columns):
        sys.exit(f"ABORT: {log_csv} missing required columns {sorted(REQUIRED)}")

    seconds = df["end_time"] - df["start_time"]
    in_tok = int(df["input_tokens"].sum())
    out_tok = int(df["output_tokens"].sum())
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    return {
        "file": os.path.basename(log_csv),
        "n_calls": int(len(df)),
        "total_seconds": round(float(seconds.sum()), 3),
        "mean_seconds": round(float(seconds.mean()), 3),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 4),
    }


usage = {
    "price_in_per_mtok": PRICE_IN_PER_M,
    "price_out_per_mtok": PRICE_OUT_PER_M,
    "A": summarize(LOG_A),
    "B": summarize(LOG_B),
}
usage["total_cost_usd"] = round(usage["A"]["cost_usd"] + usage["B"]["cost_usd"], 4)

with open(USAGE, "w") as f:
    json.dump(usage, f, indent=2)

print(f"Saved {USAGE}")
print(f"  A: {usage['A']['n_calls']} calls, {usage['A']['total_seconds']}s, ${usage['A']['cost_usd']}")
print(f"  B: {usage['B']['n_calls']} calls, {usage['B']['total_seconds']}s, ${usage['B']['cost_usd']}")
print(f"  total cost: ${usage['total_cost_usd']}")
