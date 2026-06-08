"""Project the cost of a FULL run over the whole dataset — NO SPEND.

Input tokens are counted EXACTLY with Anthropic's free `messages.count_tokens` endpoint (no
generation, no billing), building each message the same way main.py will. Output uses a fixed
budget for the {"step_correctness_label": [...], "has_valid_proof_path_label": ...} JSON.

The dataset is the per-(dataset, model) files under inputs/ (built by utils/build_inputs.py).
Each RUN prices one prompt over one dataset's 10 model files. Prints per-run + grand-total cost
and writes results/cost_estimate.json. One free count_tokens call PER record, so it takes a few
minutes and prints progress.

Run from the analysis directory:  python3 utils/estimate_cost.py
Paths are FIXED relative to that directory. Replication package, not a general tool: if anything
is not exactly where it belongs, it aborts.
"""

import os
import sys
import json
import glob
from dataclasses import dataclass, asdict
import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
OUTPUT_TOKENS = 200         # fixed budget for the label JSON (assumes JSON-only, not B's CoT)
PROGRESS_EVERY = 100        # print a progress line every N records

# Fields sent to the LLM — must match main.py exactly. The reasoning chain to verify, nothing else.
INPUT_FIELDS = ["premises", "question", "reasoning_steps"]

# (prompt, dataset directory) pairs to price. Each dir holds the 10 per-model files for that dataset.
RUNS = [
    ("prompts/prompt_A.txt", "inputs/folio"),
    ("prompts/prompt_B.txt", "inputs/folio"),
    ("prompts/prompt_A.txt", "inputs/prontoqa_ood"),
    ("prompts/prompt_B.txt", "inputs/prontoqa_ood"),
    ("prompts/prompt_A.txt", "inputs/proofwriter"),
    ("prompts/prompt_B.txt", "inputs/proofwriter"),
]
METRICS = "results/cost_estimate.json"

# Preconditions — abort unless everything a run needs is exactly present.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for prompt_path, dataset_dir in RUNS:
    if not os.path.exists(prompt_path):
        sys.exit(f"ABORT: missing prompt {prompt_path}")
    if not glob.glob(os.path.join(dataset_dir, "*.json")):
        sys.exit(f"ABORT: no input files in {dataset_dir} (run utils/build_inputs.py)")

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


def input_files(dataset_dir: str) -> list:
    """The per-model input files in a dataset dir, skipping the *_labels.json gold files."""
    return sorted(f for f in glob.glob(os.path.join(dataset_dir, "*.json"))
                  if not f.endswith("_labels.json"))


def read_dataset(dataset_dir: str) -> list:
    """All records across the dataset's per-model input files."""
    rows = []
    for path in input_files(dataset_dir):
        rows.extend(json.load(open(path, encoding="utf-8")))
    return rows


results = []
for i, (prompt_path, dataset_dir) in enumerate(RUNS, 1):
    prompt = open(prompt_path, encoding="utf-8").read()
    rows = read_dataset(dataset_dir)
    print(f"[{i}/{len(RUNS)}] {prompt_path} x {dataset_dir}  ({len(rows)} records) ...")
    total_input = 0
    for j, row in enumerate(rows, 1):
        msg = prompt + "\n\n" + json.dumps({"inputs": {f: row[f] for f in INPUT_FIELDS}}, indent=2)
        total_input += client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": msg}]).input_tokens
        if j % PROGRESS_EVERY == 0:
            print(f"      counted {j}/{len(rows)} records")
    rc = RunCost(os.path.basename(prompt_path), os.path.basename(dataset_dir),
                 len(rows), total_input, len(rows) * OUTPUT_TOKENS)
    results.append(rc)
    print(f"      -> in={rc.input_tokens:,} tok  out~{rc.output_tokens:,} tok  =  ${rc.cost_usd:.2f}")

grand_total = round(sum(r.cost_usd for r in results), 2)
print(f"\nGRAND TOTAL (prompt A+B over the whole dataset): ${grand_total:.2f}")
print("(input tokens EXACT via free count_tokens — no spend; output is a fixed JSON budget,"
      " not prompt B's chain-of-thought)")

os.makedirs("results", exist_ok=True)
json.dump({"model": MODEL, "output_tokens_budget": OUTPUT_TOKENS,
           "price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
           "input_fields": INPUT_FIELDS,
           "runs": [asdict(r) | {"cost_usd": r.cost_usd} for r in results],
           "grand_total_usd": grand_total},
          open(METRICS, "w"), indent=2)
print(f"Saved {METRICS}")
