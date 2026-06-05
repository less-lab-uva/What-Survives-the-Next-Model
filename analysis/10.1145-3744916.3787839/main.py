"""ToxicityAhead single-call oracle (RQ2): pre-toxicity transcript -> derailment probability.

One LLM call per thread (collapses the paper's two-stage LtM-SCD pipeline into one),
over our curated dataset only. RQ2 = "Can LLMs predict derailment on GitHub?"; it uses
the curated dataset, not Raman et al.'s (Raman is the RQ3 generalization set).
Runs prompt A and prompt B.

Each call writes two things: the prediction (outputs/oracle-*.csv) and a raw per-call
log (outputs/log-*.csv) with start/end timestamps, token counts, and model. The log
records API facts only — any derivation (duration, cost) happens later in evaluation.

Reproducibility: refuses to run unless the API key, both prompts, and the dataset are
present, and it will NOT overwrite existing output/log files. Anything not perfectly
set up is a hard abort.
"""

import os
import sys
import csv
import re
import json
import time
import pandas as pd
import anthropic

MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0      # paper sets temp 0 to minimize output variance
MAX_TOKENS = 2048      # headroom for prompt B's chain-of-thought before the JSON (A needs far less)
MAX_WORDS = 3000       # pre-toxicity transcript cap (verbatim from replication package)

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

DATA = "inputs/our-dataset.csv"

OUT_A = "outputs/oracle-claude-sonnet-4-6-a-our.csv"
OUT_B = "outputs/oracle-claude-sonnet-4-6-b-our.csv"

LOG_A = "outputs/log-claude-sonnet-4-6-a-our.csv"
LOG_B = "outputs/log-claude-sonnet-4-6-b-our.csv"

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")

if not os.path.exists(PROMPT_A):
    sys.exit(f"ABORT: missing {PROMPT_A}")
if not os.path.exists(PROMPT_B):
    sys.exit(f"ABORT: missing {PROMPT_B}")
if not os.path.exists(DATA):
    sys.exit(f"ABORT: missing {DATA}")

if os.path.exists(OUT_A):
    sys.exit(f"ABORT: output already exists: {OUT_A}")
if os.path.exists(OUT_B):
    sys.exit(f"ABORT: output already exists: {OUT_B}")
if os.path.exists(LOG_A):
    sys.exit(f"ABORT: output already exists: {LOG_A}")
if os.path.exists(LOG_B):
    sys.exit(f"ABORT: output already exists: {LOG_B}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)


def run(prompt_file, input_csv, output_csv, log_csv):
    prompt = open(prompt_file, encoding="utf-8").read()
    data = pd.read_csv(input_csv)
    data["text"] = data["text"].astype(str).fillna("")
    print(f"\n=== {prompt_file} x {input_csv} -> {output_csv} ===")

    with open(output_csv, "w", newline="", encoding="utf-8") as f, \
         open(log_csv, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(f, fieldnames=["issue_id", "pred_score", "true_label"])
        writer.writeheader()
        logger = csv.DictWriter(lf, fieldnames=[
            "issue_id", "start_time", "end_time",
            "input_tokens", "output_tokens", "model",
        ])
        logger.writeheader()

        for issue_id, group in data.groupby("issue_id"):
            # pre-toxicity transcript: stop at the first toxic comment, then pack
            # newest-first up to MAX_WORDS (transcript logic from oracle-llama.py).
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
            if not transcript:
                continue  # no pre-toxicity context to forecast from

            start_time = time.time()
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
                messages=[{"role": "user", "content": prompt + "\n\n" + transcript}],
            )
            end_time = time.time()

            raw = resp.content[0].text
            m = re.search(r'\{[^{}]*"derailment_probability"[^{}]*\}', raw, re.DOTALL)
            if not m:
                sys.exit(f"ABORT: no derailment_probability in response for {issue_id}: {raw!r}")
            pred = float(json.loads(m.group(0))["derailment_probability"])

            writer.writerow({
                "issue_id": issue_id,
                "pred_score": pred,
                "true_label": int((group["toxic"] == 1).any()),
            })
            logger.writerow({
                "issue_id": issue_id,
                "start_time": start_time,
                "end_time": end_time,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "model": MODEL,
            })
            f.flush()
            lf.flush()
            print(f"{issue_id}: pred={pred}")


run(PROMPT_A, DATA, OUT_A, LOG_A)
run(PROMPT_B, DATA, OUT_B, LOG_B)
