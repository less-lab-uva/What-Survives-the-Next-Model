"""Project the cost of the RQ2 run (prompt A + prompt B over our-dataset) — NO SPEND.

Input tokens are counted EXACTLY with Anthropic's free `messages.count_tokens` endpoint (no
generation, no billing); output uses a fixed budget for the {"derailment_probability": ...}
JSON. The per-thread transcript is built IDENTICALLY to main.py (group by issue_id, keep
pre-toxicity comments, pack newest-first up to MAX_WORDS) so the token counts match the run.

Prints per-run + grand-total cost and writes results/cost_estimate.json. One free
count_tokens call per thread, so it prints progress as it goes.

Run from the analysis directory:  python3 utils/estimate_cost.py
Paths are FIXED relative to that directory (not computed). This is a replication package, not
a general tool: if anything is not exactly where it belongs, it aborts.
"""

import os
import sys
import json
from dataclasses import dataclass, asdict
import pandas as pd
import anthropic

MODEL = "claude-sonnet-4-6"

# claude-sonnet-4-6 published pricing, USD per 1M tokens.
# Source (Wayback snapshot, archived 2026-06-06):
# https://web.archive.org/web/20260606180643/https://platform.claude.com/docs/en/about-claude/pricing
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0

OUTPUT_TOKENS = 30          # fixed budget for the {"derailment_probability": ...} JSON
MAX_WORDS = 3000            # pre-toxicity transcript cap — MUST match main.py (verbatim from repo)
PROGRESS_EVERY = 50         # print a progress line every N threads

DATA = "inputs/our-dataset.csv"
# Prompts priced against DATA (one entry per run). Edit freely.
PROMPTS = ["prompts/prompt_A.txt", "prompts/prompt_B.txt"]
METRICS = "results/cost_estimate.json"

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
if not os.path.exists(DATA):
    sys.exit(f"ABORT: missing {DATA}")
for prompt_path in PROMPTS:
    if not os.path.exists(prompt_path):
        sys.exit(f"ABORT: missing prompt {prompt_path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


@dataclass
class RunCost:
    prompt: str
    n_threads: int
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        cin = self.input_tokens * PRICE_IN_PER_M / 1e6
        cout = self.output_tokens * PRICE_OUT_PER_M / 1e6
        return round(cin + cout, 2)


def build_transcripts(input_csv: str) -> list:
    """Pre-toxicity transcripts, one per issue_id — identical to main.py's logic."""
    data = pd.read_csv(input_csv)
    data["text"] = data["text"].astype(str).fillna("")
    transcripts = []
    for issue_id, group in data.groupby("issue_id"):
        comments = []
        for _, row in group.iterrows():
            if row["toxic"] == 1:
                break
            comments.append(f"{row['speaker']}: <<< {row['text']} >>>")
        transcript = ""
        for item in reversed(comments):
            if len((transcript + item).split()) > MAX_WORDS:
                break
            transcript = item + "\n" + transcript
        if transcript:
            transcripts.append(transcript)
    return transcripts


THREADS = build_transcripts(DATA)
print(f"{DATA}: {len(THREADS)} threads with pre-toxicity context")

results = []
for i, prompt_path in enumerate(PROMPTS, 1):
    prompt = open(prompt_path, encoding="utf-8").read()
    print(f"[{i}/{len(PROMPTS)}] {prompt_path} x {DATA}  ({len(THREADS)} threads) ...")
    total_input = 0
    for k, transcript in enumerate(THREADS, 1):
        msg = prompt + "\n\n" + transcript
        total_input += client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": msg}]).input_tokens
        if k % PROGRESS_EVERY == 0:
            print(f"      counted {k}/{len(THREADS)} threads")
    rc = RunCost(os.path.basename(prompt_path), len(THREADS), total_input, len(THREADS) * OUTPUT_TOKENS)
    results.append(rc)
    print(f"      -> in={rc.input_tokens:,} tok  out~{rc.output_tokens:,} tok  =  ${rc.cost_usd:.2f}")

grand_total = round(sum(r.cost_usd for r in results), 2)
print(f"\nGRAND TOTAL (prompt A + B over {DATA}): ${grand_total:.2f}")
print("(input tokens EXACT via free count_tokens — no spend; output is a fixed JSON budget,"
      " not prompt B's chain-of-thought)")

os.makedirs("results", exist_ok=True)
json.dump({"model": MODEL, "output_tokens_budget": OUTPUT_TOKENS, "max_words": MAX_WORDS,
           "price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
           "runs": [asdict(r) | {"cost_usd": r.cost_usd} for r in results],
           "grand_total_usd": grand_total},
          open(METRICS, "w"), indent=2)
print(f"Saved {METRICS}")
