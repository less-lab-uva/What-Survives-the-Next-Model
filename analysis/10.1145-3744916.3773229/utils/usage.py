"""Derive resource usage (call latency + cost) for the ConfuGuard oracle runs.

Separate from evaluator.py (which scores predictions). Reads the raw per-call logs
(outputs/log-*.csv) for all 6 runs (prompt A/B x ConfuDB / real_malware / no_malware) and
derives, per run, total/mean call seconds (end_time - start_time) and total cost (logged token
counts x published price), plus per-prompt and grand totals. Writes results/usage.json.

There is no pricing API, so the rates below are Anthropic's published pricing for
claude-sonnet-4-6, applied here at analysis time (not during the run).

Run from the analysis directory:  python3 utils/usage.py
Paths are FIXED relative to that directory (not computed). Like main.py: prerequisites checked
up front, hard-abort, no overwrite.
"""

import os
import sys
import csv
import json

# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0

# the 6 per-call logs written by main.py (names mirror the down-sampled inputs)
LOG_A_CONFUDB = "outputs/log-claude-sonnet-4-6-a-ConfuDB.down_sampled_15usd.csv"
LOG_B_CONFUDB = "outputs/log-claude-sonnet-4-6-b-ConfuDB.down_sampled_15usd.csv"
LOG_A_REAL    = "outputs/log-claude-sonnet-4-6-a-NeupaneDB_real_malware.down_sampled_15usd.csv"
LOG_B_REAL    = "outputs/log-claude-sonnet-4-6-b-NeupaneDB_real_malware.down_sampled_15usd.csv"
LOG_A_NOMAL   = "outputs/log-claude-sonnet-4-6-a-NeupaneDB_no_malware.down_sampled_15usd.csv"
LOG_B_NOMAL   = "outputs/log-claude-sonnet-4-6-b-NeupaneDB_no_malware.down_sampled_15usd.csv"

USAGE = "results/usage.json"

REQUIRED = {"start_time", "end_time", "input_tokens", "output_tokens"}

# Preconditions.
for path in (LOG_A_CONFUDB, LOG_B_CONFUDB, LOG_A_REAL, LOG_B_REAL, LOG_A_NOMAL, LOG_B_NOMAL):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path} (run main.py first)")
if os.path.exists(USAGE):
    sys.exit(f"ABORT: output already exists: {USAGE}")

os.makedirs("results", exist_ok=True)


def summarize(log_csv: str) -> dict:
    with open(log_csv, newline="", encoding="utf-8") as fin:
        rows = list(csv.DictReader(fin))
    if rows and not REQUIRED.issubset(rows[0].keys()):
        sys.exit(f"ABORT: {log_csv} missing required columns {sorted(REQUIRED)}")
    seconds = [float(r["end_time"]) - float(r["start_time"]) for r in rows]
    in_tok = sum(int(r["input_tokens"]) for r in rows)
    out_tok = sum(int(r["output_tokens"]) for r in rows)
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    return {
        "file": os.path.basename(log_csv),
        "n_calls": len(rows),
        "total_seconds": round(sum(seconds), 3),
        "mean_seconds": round(sum(seconds) / len(seconds), 3) if seconds else 0.0,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 4),
    }


def totals(summaries: list) -> dict:
    return {
        "n_calls": sum(s["n_calls"] for s in summaries),
        "total_seconds": round(sum(s["total_seconds"] for s in summaries), 3),
        "input_tokens": sum(s["input_tokens"] for s in summaries),
        "output_tokens": sum(s["output_tokens"] for s in summaries),
        "cost_usd": round(sum(s["cost_usd"] for s in summaries), 4),
    }


usage = {
    "price_in_per_mtok": PRICE_IN_PER_M,
    "price_out_per_mtok": PRICE_OUT_PER_M,
    "A": {
        "ConfuDB": summarize(LOG_A_CONFUDB),
        "real_malware": summarize(LOG_A_REAL),
        "no_malware": summarize(LOG_A_NOMAL),
    },
    "B": {
        "ConfuDB": summarize(LOG_B_CONFUDB),
        "real_malware": summarize(LOG_B_REAL),
        "no_malware": summarize(LOG_B_NOMAL),
    },
}
usage["A"]["total"] = totals(list(usage["A"].values()))
usage["B"]["total"] = totals(list(usage["B"].values()))
usage["grand_total"] = totals([usage["A"]["total"], usage["B"]["total"]])

with open(USAGE, "w") as f:
    json.dump(usage, f, indent=2)

print(f"Saved {USAGE}")
for variant in ("A", "B"):
    t = usage[variant]["total"]
    print(f"  {variant}: {t['n_calls']} calls, {t['total_seconds']}s, ${t['cost_usd']}")
print(f"  grand total: {usage['grand_total']['n_calls']} calls, "
      f"{usage['grand_total']['total_seconds']}s, ${usage['grand_total']['cost_usd']}")
