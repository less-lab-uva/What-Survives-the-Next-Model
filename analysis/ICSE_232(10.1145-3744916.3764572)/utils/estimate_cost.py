"""Project the cost of running the code-generation oracle over ALL problems — NO SPEND.

Input tokens are counted EXACTLY with Anthropic's free `messages.count_tokens` endpoint (no
generation, no billing), building each message the same way main.py will. Output uses a fixed
per-call budget for the generated program. 6 runs (prompt A/B x apps/code_contests/xCodeEval).
Writes results/cost_estimate.json.

Requires the generated prompts (run utils/prompt_generator.py first). One free count_tokens call
PER problem, so it takes a few minutes and prints progress.

Run from the analysis directory:  python3 utils/estimate_cost.py
"""

import os
import sys
import json
from dataclasses import dataclass, asdict
import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
OUTPUT_TOKENS = 1000        # assumed budget for one generated program (adjust; prompt B may add CoT)
PROGRESS_EVERY = 50

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

# Per-dataset oracle input fields — must match main.py (everything else is filtered out, not sent).
INPUT_FIELDS = {
    "apps": ["question", "starter_code"],
    "code_contests": ["description"],
    "xCodeEval": ["description", "input_spec", "output_spec", "notes"],
}

# (prompt, dataset) pairs to price.
RUNS = [
    (PROMPT_A, "apps"), (PROMPT_B, "apps"),
    (PROMPT_A, "code_contests"), (PROMPT_B, "code_contests"),
    (PROMPT_A, "xCodeEval"), (PROMPT_B, "xCodeEval"),
]
METRICS = "results/cost_estimate.json"

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for prompt_path, ds in RUNS:
    if not os.path.exists(prompt_path):
        sys.exit(f"ABORT: missing {prompt_path} (run utils/prompt_generator.py first)")
    if not os.path.exists(os.path.join("inputs", f"{ds}.jsonl")):
        sys.exit(f"ABORT: missing inputs/{ds}.jsonl (run utils/build_inputs.py first)")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def build_message(prompt: str, dataset: str, row: dict) -> str:
    """Identical to main.py's message construction: prompt + the dataset's input fields as JSON."""
    fields = {f: (row.get(f) or "") for f in INPUT_FIELDS[dataset]}
    return prompt + "\n\n" + json.dumps({"inputs": fields}, indent=2)


@dataclass
class RunCost:
    prompt: str
    dataset: str
    n_problems: int
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        return round((self.input_tokens * PRICE_IN_PER_M + self.output_tokens * PRICE_OUT_PER_M) / 1e6, 2)


results = []
for i, (prompt_path, ds) in enumerate(RUNS, 1):
    prompt = open(prompt_path, encoding="utf-8").read()
    rows = [json.loads(line) for line in open(os.path.join("inputs", f"{ds}.jsonl"), encoding="utf-8") if line.strip()]
    print(f"[{i}/{len(RUNS)}] {os.path.basename(prompt_path)} x {ds}  ({len(rows)} problems) ...")
    total_input = 0
    for j, row in enumerate(rows, 1):
        total_input += client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": build_message(prompt, ds, row)}]).input_tokens
        if j % PROGRESS_EVERY == 0:
            print(f"      counted {j}/{len(rows)}")
    rc = RunCost(os.path.basename(prompt_path), ds, len(rows), total_input, len(rows) * OUTPUT_TOKENS)
    results.append(rc)
    print(f"      -> in={rc.input_tokens:,} tok  out~{rc.output_tokens:,} tok  =  ${rc.cost_usd:.2f}")

grand_total = round(sum(r.cost_usd for r in results), 2)
print(f"\nGRAND TOTAL (prompt A+B over all benchmarks): ${grand_total:.2f}")
print("(input tokens EXACT via free count_tokens — no spend; output is a fixed per-program budget)")

os.makedirs("results", exist_ok=True)
json.dump({"model": MODEL, "output_tokens_budget": OUTPUT_TOKENS,
           "price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
           "input_fields": INPUT_FIELDS,
           "runs": [asdict(r) | {"cost_usd": r.cost_usd} for r in results],
           "grand_total_usd": grand_total},
          open(METRICS, "w"), indent=2)
print(f"Saved {METRICS}")
