"""Down-sample the three full datasets to a target run cost (~BUDGET), fairly.

Fair = the SAME sampling fraction f across all three datasets (proportional, not equal count),
stratified by gold category so the small categories stay represented. f is chosen so the
projected full run (all datasets x prompt A + B) costs ~BUDGET.

Cost is estimated with the free count_tokens endpoint (no spend) on a small per-dataset sample
of rows, plus a fixed output-token budget for the {"is_typosquat": ...} JSON. Reads the FULL
datasets inputs/<name>.csv and writes inputs/<name>.down_sampled_15usd.csv (full original
columns, fewer rows). If the full run already fits the budget (f >= 1.0) it keeps everything.
The full datasets are not modified; re-running overwrites the samples. Also writes
results/down_sample_report.json with the % of each dataset kept; if the overall sample falls
below 10% it is flagged as a problem (the budget is too small to be representative).

NOTE: output is budgeted as JSON-only (OUTPUT_TOKENS). If prompt B emits chain-of-thought, the
real run costs more than projected — lower BUDGET or raise OUTPUT_TOKENS.

Run from the analysis directory:  python3 utils/sample_to_budget.py
Paths are FIXED relative to that directory (not computed). This is a replication package, not
a general tool: if anything is not exactly where it belongs, it aborts.
"""

import os
import sys
import csv
import json
import random
import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
OUTPUT_TOKENS = 30          # fixed budget for the {"is_typosquat": ...} JSON (see NOTE)
BUDGET = 15.0
COST_SAMPLE = 20            # rows per dataset used to estimate avg input tokens
SEED = 0
SUFFIX = "down_sampled_15usd"

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

CONFUDB      = "inputs/ConfuDB.csv"
REAL_MALWARE = "inputs/NeupaneDB_real_malware.csv"
NO_MALWARE   = "inputs/NeupaneDB_no_malware.csv"

CONFUDB_COLS      = ["type", "name", "namespace"]
REAL_MALWARE_COLS = ["typosquat_pkg", "registry"]
NO_MALWARE_COLS   = ["Adversarial pkg", "Ecosystem"]

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in (PROMPT_A, PROMPT_B, CONFUDB, REAL_MALWARE, NO_MALWARE):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
PROMPT_A_TEXT = open(PROMPT_A, encoding="utf-8").read()
PROMPT_B_TEXT = open(PROMPT_B, encoding="utf-8").read()


def read_source(path: str):
    with open(path, newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        return reader.fieldnames, list(reader)


def categorize_confudb(r: dict) -> str:
    tt = r["threat_type"].strip().lower()
    return "benign" if tt == "false_positive" else "stealthy" if tt == "typosquat" else "active"


def categorize_no_malware(r: dict) -> str:
    return "benign" if r["is_FP?"].strip().lower() == "yes" else "stealthy"


def avg_input_tokens(prompt_text: str, rows: list, cols: list) -> float:
    sample = rows if len(rows) <= COST_SAMPLE else random.Random(SEED).sample(rows, COST_SAMPLE)
    counts = []
    for r in sample:
        msg = prompt_text + "\n\n" + json.dumps({c: r[c] for c in cols})
        counts.append(client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": msg}]).input_tokens)
    return sum(counts) / len(counts)


def cost_per_row(rows: list, cols: list) -> float:
    """Projected $ for ONE row across prompt A + prompt B."""
    out_cost = OUTPUT_TOKENS * PRICE_OUT_PER_M / 1e6
    return sum(avg_input_tokens(p, rows, cols) * PRICE_IN_PER_M / 1e6 + out_cost
               for p in (PROMPT_A_TEXT, PROMPT_B_TEXT))


def stratified_sample(rows: list, categories: list, fraction: float) -> list:
    """Random-sample `fraction` of rows WITHIN each gold category (deterministic via SEED)."""
    rng = random.Random(SEED)
    by_category = {}
    for row, cat in zip(rows, categories):
        by_category.setdefault(cat, []).append(row)
    picked = []
    for cat, group in by_category.items():
        k = min(len(group), max(1, round(fraction * len(group))))
        picked.extend(rng.sample(group, k))
    return picked


def down_path(source: str) -> str:
    return source.replace(".csv", f".{SUFFIX}.csv")


# load full datasets + per-row gold category (for stratification)
fields_c, rows_c = read_source(CONFUDB)
cats_c = [categorize_confudb(r) for r in rows_c]

fields_r, rows_r = read_source(REAL_MALWARE)
rows_r = [r for r in rows_r if r["confusion"].strip().upper() == "TP"]   # drop UNK
cats_r = ["active"] * len(rows_r)

fields_n, rows_n = read_source(NO_MALWARE)
cats_n = [categorize_no_malware(r) for r in rows_n]

# project full-run cost and the budget fraction
full_cost = (len(rows_c) * cost_per_row(rows_c, CONFUDB_COLS)
             + len(rows_r) * cost_per_row(rows_r, REAL_MALWARE_COLS)
             + len(rows_n) * cost_per_row(rows_n, NO_MALWARE_COLS))
# Only down-sample if the full run exceeds the budget; otherwise use everything (f = 1.0).
fraction = min(1.0, BUDGET / full_cost)
print(f"projected full-run cost ~ ${full_cost:.2f}; budget ${BUDGET:.0f}  ->  fraction f = {fraction:.3f}")

# write the f-fraction stratified samples next to the full datasets, tracking coverage
per_dataset = {}
total_full = total_sampled = 0
for source, fields, rows, cats in (
    (CONFUDB, fields_c, rows_c, cats_c),
    (REAL_MALWARE, fields_r, rows_r, cats_r),
    (NO_MALWARE, fields_n, rows_n, cats_n),
):
    picked = stratified_sample(rows, cats, fraction)
    out = down_path(source)
    with open(out, "w", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=fields)
        writer.writeheader()
        writer.writerows(picked)
    pct = round(100 * len(picked) / len(rows), 2) if rows else 0.0
    per_dataset[os.path.basename(source)] = {"full_rows": len(rows), "sampled_rows": len(picked), "percent_used": pct}
    total_full += len(rows)
    total_sampled += len(picked)
    print(f"  {os.path.basename(source):28} {len(rows):5} -> {len(picked):5} rows ({pct:5.1f}%) -> {os.path.basename(out)}")

overall_pct = round(100 * total_sampled / total_full, 2) if total_full else 0.0
below_10 = overall_pct < 10.0
report = {
    "budget_usd": BUDGET,
    "projected_full_cost_usd": round(full_cost, 2),
    "fraction": round(fraction, 4),
    "datasets": per_dataset,
    "overall": {"full_rows": total_full, "sampled_rows": total_sampled, "percent_used": overall_pct},
    "below_10_percent": below_10,
}
if below_10:
    report["warning"] = (f"PROBLEM: ${BUDGET:.0f} buys only {overall_pct:.1f}% of the data (< 10%); "
                         f"the sample may be too small to be representative.")

os.makedirs("results", exist_ok=True)
json.dump(report, open("results/down_sample_report.json", "w"), indent=2)
print(f"\noverall: {total_sampled}/{total_full} rows kept ({overall_pct:.1f}%) -> results/down_sample_report.json")
if below_10:
    print(f"  *** {report['warning']} ***")
