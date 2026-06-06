"""Project the cost of a FULL run over each (prompt, dataset) pair — NO SPEND.

Input tokens are counted EXACTLY with Anthropic's free `messages.count_tokens` endpoint (no
generation, no billing); output uses a fixed budget for the {"is_typosquat": ...} JSON. Edit
the RUNS table below to change which (prompt, dataset, columns) pairs are priced. Prints
per-run + grand-total cost and writes results/cost_estimate.json.

This makes one free count_tokens call PER ROW, so it takes a few minutes — it prints progress
as it goes.

Run from the analysis directory:  python3 utils/estimate_cost.py
Paths are FIXED relative to that directory (not computed). This is a replication package, not
a general tool: if anything is not exactly where it belongs, it aborts.
"""

import os
import sys
import csv
import json
from dataclasses import dataclass, asdict
import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
OUTPUT_TOKENS = 30          # fixed budget for the JSON output (assumes JSON-only)
PROGRESS_EVERY = 200        # print a progress line every N rows

# The (prompt, dataset, columns-sent-to-the-LLM) pairs to price. One line per run; edit freely.
RUNS = [
    ("prompts/prompt_A.txt", "inputs/ConfuDB.down_sampled_15usd.csv", ["type", "name", "namespace"]),
    ("prompts/prompt_B.txt", "inputs/ConfuDB.down_sampled_15usd.csv", ["type", "name", "namespace"]),
    ("prompts/prompt_A.txt", "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv", ["typosquat_pkg", "registry"]),
    ("prompts/prompt_B.txt", "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv", ["typosquat_pkg", "registry"]),
    ("prompts/prompt_A.txt", "inputs/NeupaneDB_no_malware.down_sampled_15usd.csv", ["Adversarial pkg", "Ecosystem"]),
    ("prompts/prompt_B.txt", "inputs/NeupaneDB_no_malware.down_sampled_15usd.csv", ["Adversarial pkg", "Ecosystem"]),
    #("prompts/prompt_A.txt", "inputs/ConfuDB.csv", ["type", "name", "namespace"]),
    #("prompts/prompt_B.txt", "inputs/ConfuDB.csv", ["type", "name", "namespace"]),
    #("prompts/prompt_A.txt", "inputs/NeupaneDB_real_malware.csv", ["typosquat_pkg", "registry"]),
    #("prompts/prompt_B.txt", "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv", ["typosquat_pkg", "registry"]),
    #("prompts/prompt_A.txt", "inputs/NeupaneDB_no_malware.csv", ["Adversarial pkg", "Ecosystem"]),
    #("prompts/prompt_B.txt", "inputs/NeupaneDB_no_malware.csv", ["Adversarial pkg", "Ecosystem"]),
]
METRICS = "results/cost_estimate.json"

# Preconditions — abort unless everything a run needs is exactly present.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for prompt_path, dataset_path, _ in RUNS:
    if not os.path.exists(prompt_path):
        sys.exit(f"ABORT: missing prompt {prompt_path}")
    if not os.path.exists(dataset_path):
        sys.exit(f"ABORT: missing dataset {dataset_path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


@dataclass
class RunCost:
    prompt: str
    dataset: str
    n_rows: int
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        cin = self.input_tokens * PRICE_IN_PER_M / 1e6
        cout = self.output_tokens * PRICE_OUT_PER_M / 1e6
        return round(cin + cout, 2)


def read_rows(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as fin:
        return list(csv.DictReader(fin))


results = []
for i, (prompt_path, dataset_path, cols) in enumerate(RUNS, 1):
    prompt = open(prompt_path, encoding="utf-8").read()
    rows = read_rows(dataset_path)
    print(f"[{i}/{len(RUNS)}] {prompt_path} x {dataset_path}  ({len(rows)} rows) ...")
    total_input = 0
    for j, row in enumerate(rows, 1):
        msg = prompt + "\n\n" + json.dumps({c: row[c] for c in cols})
        total_input += client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": msg}]).input_tokens
        if j % PROGRESS_EVERY == 0:
            print(f"      counted {j}/{len(rows)} rows")
    rc = RunCost(os.path.basename(prompt_path), os.path.basename(dataset_path),
                 len(rows), total_input, len(rows) * OUTPUT_TOKENS)
    results.append(rc)
    print(f"      -> in={rc.input_tokens:,} tok  out~{rc.output_tokens:,} tok  =  ${rc.cost_usd:.2f}")

grand_total = round(sum(r.cost_usd for r in results), 2)
print(f"\nGRAND TOTAL (all runs, full datasets): ${grand_total:.2f}")
print("(input tokens EXACT via free count_tokens — no spend; output is a fixed JSON budget,"
      " not prompt B's chain-of-thought)")

os.makedirs("results", exist_ok=True)
json.dump({"model": MODEL, "output_tokens_budget": OUTPUT_TOKENS,
           "price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
           "runs": [asdict(r) | {"cost_usd": r.cost_usd} for r in results],
           "grand_total_usd": grand_total},
          open(METRICS, "w"), indent=2)
print(f"Saved {METRICS}")
