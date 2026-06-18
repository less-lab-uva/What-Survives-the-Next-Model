"""ToxicityAhead single-call oracle (RQ2): pre-toxicity transcript -> derailment probability.

One LLM call per thread (collapses the paper's two-stage LtM-SCD pipeline into one), over our
curated dataset only. RQ2 = "Can LLMs predict derailment on GitHub?". Runs prompt A and prompt B.

OUTPUT IS TWO COMMITTED FILES — one per prompt variant — in JSONL:
    outputs/output_A.jsonl   outputs/output_B.jsonl     {issue_id, pred_score, true_label}
Per-call logs go to logs/ (gitignored), one per variant:
    logs/log_A.jsonl         logs/log_B.jsonl           {issue_id, start/end_time, tokens, model}

Reproducibility: refuses to run unless the API key, both prompts, and the dataset are present,
and it will NOT overwrite existing output/log files. Anything not perfectly set up is a hard abort.
"""

import os
import sys
import re
import json
import time
import pandas as pd
import anthropic

MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0      # paper sets temp 0 to minimize output variance
MAX_TOKENS = 2048      # headroom for prompt B's chain-of-thought before the JSON
MAX_WORDS = 3000       # pre-toxicity transcript cap (verbatim from replication package)

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"
DATA = "inputs/our-dataset.csv"

PROMPTS = {"A": PROMPT_A, "B": PROMPT_B}
OUTPUTS = {"A": "outputs/output_A.jsonl", "B": "outputs/output_B.jsonl"}
LOGS = {"A": "logs/log_A.jsonl", "B": "logs/log_B.jsonl"}

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in (PROMPT_A, PROMPT_B, DATA):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")
for path in list(OUTPUTS.values()) + list(LOGS.values()):
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)


def run(tag: str) -> None:
    prompt = open(PROMPTS[tag], encoding="utf-8").read()
    data = pd.read_csv(DATA)
    data["text"] = data["text"].astype(str).fillna("")
    print(f"\n=== prompt {tag}: {PROMPTS[tag]} -> {OUTPUTS[tag]} ===")

    with open(OUTPUTS[tag], "w", encoding="utf-8") as out, \
         open(LOGS[tag], "w", encoding="utf-8") as log:
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

            out.write(json.dumps({
                "issue_id": issue_id,
                "pred_score": pred,
                "true_label": int((group["toxic"] == 1).any()),
            }, ensure_ascii=False) + "\n")
            log.write(json.dumps({
                "issue_id": issue_id,
                "start_time": start_time,
                "end_time": end_time,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "model": MODEL,
            }, ensure_ascii=False) + "\n")
            out.flush(); log.flush()
            print(f"{issue_id}: pred={pred}")


run("A")
run("B")
