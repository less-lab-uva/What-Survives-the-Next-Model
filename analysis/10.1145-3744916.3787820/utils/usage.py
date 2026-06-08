"""Resource usage (call latency + cost) for the oracle runs — separate from evaluator.py.

Reads the per-call logs logs/log_*.jsonl (one per prompt variant; each line has start_time,
end_time, input_tokens, output_tokens) and derives, per variant, total/mean call seconds and total
cost (logged token counts x published price), plus a grand total. Writes results/usage.json.

There is no pricing API, so the rates below are Anthropic's published pricing for claude-sonnet-4-6,
applied here at analysis time (not during the run).

Run from the analysis directory:  python3 utils/usage.py
"""

import os
import sys
import json
import glob

# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0

USAGE = "results/usage.json"
REQUIRED = {"start_time", "end_time", "input_tokens", "output_tokens"}

logs = sorted(glob.glob("logs/log_*.jsonl"))
if not logs:
    sys.exit("ABORT: no logs/log_*.jsonl (run main.py first)")
os.makedirs("results", exist_ok=True)


def summarize(path: str) -> dict:
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    if rows and not REQUIRED.issubset(rows[0].keys()):
        sys.exit(f"ABORT: {path} missing required keys {sorted(REQUIRED)}")
    seconds = [r["end_time"] - r["start_time"] for r in rows]
    in_tok = sum(r["input_tokens"] for r in rows)
    out_tok = sum(r["output_tokens"] for r in rows)
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    return {"file": os.path.basename(path), "n_calls": len(rows),
            "total_seconds": round(sum(seconds), 1),
            "mean_seconds": round(sum(seconds) / len(seconds), 2) if rows else 0.0,
            "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": round(cost, 4)}


per_log = [summarize(p) for p in logs]
grand = {"n_calls": sum(p["n_calls"] for p in per_log),
         "total_seconds": round(sum(p["total_seconds"] for p in per_log), 1),
         "input_tokens": sum(p["input_tokens"] for p in per_log),
         "output_tokens": sum(p["output_tokens"] for p in per_log),
         "cost_usd": round(sum(p["cost_usd"] for p in per_log), 4)}

for p in per_log:
    print(f"  {p['file']:22} {p['n_calls']:4} calls  {p['total_seconds']:8.1f}s  "
          f"in={p['input_tokens']:,} out={p['output_tokens']:,}  ${p['cost_usd']:.2f}")
print(f"  GRAND: {grand['n_calls']} calls  {grand['total_seconds']:.1f}s  "
      f"in={grand['input_tokens']:,} out={grand['output_tokens']:,}  ${grand['cost_usd']:.2f}")

json.dump({"price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
           "per_log": per_log, "grand_total": grand}, open(USAGE, "w"), indent=2)
print(f"Saved {USAGE}")
