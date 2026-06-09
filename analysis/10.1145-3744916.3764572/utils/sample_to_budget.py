"""Down-sample the Specine benchmarks to a target run cost (~BUDGET), fairly.

Cost-aware (problem sizes vary a lot, so we cost every problem, not a sample): for each problem
count the input tokens for prompt A + prompt B with the free count_tokens endpoint (no spend) and
add a fixed output budget. Project the full run cost, take fraction f = BUDGET / full_cost, and
within each benchmark (apps / code_contests / xCodeEval) randomly select problems until that
benchmark's selected cost reaches f x its total. Same f across benchmarks = fair (each stays
proportionally represented at ~$BUDGET).

Reads inputs/<dataset>.jsonl, writes inputs/<dataset>.down_sampled_15usd.jsonl (verbatim records,
fewer problems) + results/down_sample_report.json (% kept per benchmark, <10% flag). If the full
run already fits the budget (f >= 1.0) it keeps everything. Re-running overwrites the samples.

NOTE: output is budgeted as OUTPUT_TOKENS per program. Code generation output is larger/variabler
than a label and prompt B may add CoT — if the real run overshoots, lower BUDGET or raise OUTPUT_TOKENS.

Run from the analysis directory:  python3 utils/sample_to_budget.py
"""

import os
import sys
import math
import json
import random
import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
OUTPUT_TOKENS = 1000        # per generated program (see NOTE)
BUDGET = 15.0
FLOOR = 0.10                # never keep less than 10% of any benchmark, even if it exceeds BUDGET
SEED = 0
SUFFIX = "down_sampled_15usd"
PROGRESS_EVERY = 50

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"
DATASETS = ["apps", "code_contests", "xCodeEval"]

# Per-dataset oracle input fields — must match main.py / estimate_cost.py exactly.
INPUT_FIELDS = {
    "apps": ["question", "starter_code"],
    "code_contests": ["description"],
    "xCodeEval": ["description", "input_spec", "output_spec", "notes"],
}

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in (PROMPT_A, PROMPT_B):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path} (run utils/prompt_generator.py first)")
for ds in DATASETS:
    if not os.path.exists(os.path.join("inputs", f"{ds}.jsonl")):
        sys.exit(f"ABORT: missing inputs/{ds}.jsonl (run utils/build_inputs.py first)")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
PROMPT_A_TEXT = open(PROMPT_A, encoding="utf-8").read()
PROMPT_B_TEXT = open(PROMPT_B, encoding="utf-8").read()


def count_input(prompt_text: str, dataset: str, row: dict) -> int:
    fields = {f: (row.get(f) or "") for f in INPUT_FIELDS[dataset]}
    msg = prompt_text + "\n\n" + json.dumps({"inputs": fields}, indent=2)
    return client.messages.count_tokens(
        model=MODEL, messages=[{"role": "user", "content": msg}]).input_tokens


def problem_cost(dataset: str, row: dict) -> float:
    """Projected $ for ONE problem across prompt A + prompt B (input exact, output budgeted)."""
    in_tok = count_input(PROMPT_A_TEXT, dataset, row) + count_input(PROMPT_B_TEXT, dataset, row)
    out_tok = 2 * OUTPUT_TOKENS
    return (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6


# Cost every problem in every benchmark.
costed = {}
for ds in DATASETS:
    rows = [json.loads(line) for line in open(os.path.join("inputs", f"{ds}.jsonl"), encoding="utf-8") if line.strip()]
    print(f"costing {ds} ({len(rows)} problems)...")
    items = []
    for i, r in enumerate(rows, 1):
        items.append((r, problem_cost(ds, r)))
        if i % PROGRESS_EVERY == 0:
            print(f"   {i}/{len(rows)}")
    costed[ds] = items

full_cost = sum(c for ds in DATASETS for _, c in costed[ds])
fraction = min(1.0, BUDGET / full_cost)
print(f"\nprojected full-run cost ~ ${full_cost:.2f}; budget ${BUDGET:.0f}  ->  fraction f = {fraction:.3f}")

per_dataset = {}
total_full = total_sampled = 0
total_sampled_cost = 0.0
for ds in DATASETS:
    items = costed[ds][:]
    random.Random(SEED).shuffle(items)
    target = fraction * sum(c for _, c in items)
    floor_count = max(1, math.ceil(FLOOR * len(items)))   # 10% floor — never go below this
    picked, acc = [], 0.0
    for r, c in items:
        if len(picked) >= floor_count and acc >= target:
            break
        picked.append(r)
        acc += c
    out = os.path.join("inputs", f"{ds}.{SUFFIX}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in picked:
            f.write(json.dumps(r) + "\n")
    pct = round(100 * len(picked) / len(items), 2) if items else 0.0
    per_dataset[ds] = {"full_problems": len(items), "sampled_problems": len(picked),
                       "percent_used": pct, "full_cost_usd": round(sum(c for _, c in items), 2),
                       "sampled_cost_usd": round(acc, 2)}
    total_full += len(items)
    total_sampled += len(picked)
    total_sampled_cost += acc
    print(f"  {ds:14} {len(items):4} -> {len(picked):4} problems ({pct:5.1f}%)  ~${acc:.2f}  -> {os.path.basename(out)}")

overall_pct = round(100 * total_sampled / total_full, 2) if total_full else 0.0
over_budget = total_sampled_cost > BUDGET * 1.02    # the 10% floor forced us past the budget
report = {"budget_usd": BUDGET, "floor_fraction": FLOOR,
          "projected_full_cost_usd": round(full_cost, 2),
          "fraction": round(fraction, 4), "output_tokens_budget": OUTPUT_TOKENS,
          "datasets": per_dataset,
          "overall": {"full_problems": total_full, "sampled_problems": total_sampled,
                      "percent_used": overall_pct, "sampled_cost_usd": round(total_sampled_cost, 2)},
          "budget_exceeded_by_floor": over_budget}
if over_budget:
    report["warning"] = (f"REJECT DECISION: holding the {int(FLOOR * 100)}% floor keeps "
                         f"{overall_pct:.1f}% of the data but costs ~${total_sampled_cost:.2f} > "
                         f"${BUDGET:.0f} — ${BUDGET:.0f} buys under {int(FLOOR * 100)}% here, "
                         f"too little to be representative.")

os.makedirs("results", exist_ok=True)
json.dump(report, open("results/down_sample_report.json", "w"), indent=2)
print(f"\noverall: {total_sampled}/{total_full} problems ({overall_pct:.1f}%), "
      f"realized ~${total_sampled_cost:.2f}  -> results/down_sample_report.json")
if over_budget:
    print(f"  *** {report['warning']} ***")
