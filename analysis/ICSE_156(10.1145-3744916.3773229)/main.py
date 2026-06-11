"""ConfuGuard single-call oracle: package (minus ground truth) -> is_typosquat.

Replaces ConfuGuard's whole pipeline with one LLM call per row. Each dataset's row is stripped
to the non-label, non-leaking columns, handed to the model, and the model returns a binary
{"is_typosquat": true|false}. Ground truth is never sent — it's recovered later by joining the
output back to the source CSV. Runs prompt A and prompt B.

OUTPUT IS TWO COMMITTED FILES — one per prompt variant — in JSONL, each line tagged with its
dataset:
    outputs/output_A.jsonl   outputs/output_B.jsonl     {dataset, <kept cols>, is_typosquat}
Per-call logs go to logs/ (gitignored), one per variant:
    logs/log_A.jsonl         logs/log_B.jsonl           {dataset, package, start/end_time, tokens, model, raw}

Reproducibility: refuses to run unless the API key, both prompts, and all three datasets are
present, and it will NOT overwrite existing output/log files. Anything not perfectly set up is a
hard abort.
"""

import os
import sys
import csv
import re
import json
import time
from dataclasses import dataclass
import anthropic

MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0
MAX_TOKENS = 2048      # headroom for prompt B's chain-of-thought before the JSON

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

# Columns NOT sent to the LLM (label / target / dataset-construction provenance that would leak
# the answer). Only the kept columns below are handed to the model.
#   ConfuDB:      threat_type (label), description (leaks), legitimate_package (target)
#   real_malware: confusion (label), legitimate_pkg (target), categories/source/study/source_file
#                 (confirmed-attack provenance -> leaks), hallucianated (data-collection artifact)
#   no_malware:   is_FP? (label), Original pkg (target), FP Categories / Comment (leaks)

# (dataset name, source $15 sample, kept columns sent to the model, package-key column)
DATASETS = [
    ("ConfuDB",                "inputs/ConfuDB.down_sampled_15usd.csv",
     ["type", "name", "namespace"], "name"),
    ("NeupaneDB_real_malware", "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv",
     ["typosquat_pkg", "registry"], "typosquat_pkg"),
    ("NeupaneDB_no_malware",   "inputs/NeupaneDB_no_malware.down_sampled_15usd.csv",
     ["Adversarial pkg", "Ecosystem"], "Adversarial pkg"),
]

OUTPUTS = {"A": "outputs/output_A.jsonl", "B": "outputs/output_B.jsonl"}
LOGS = {"A": "logs/log_A.jsonl", "B": "logs/log_B.jsonl"}
PROMPTS = {"A": PROMPT_A, "B": PROMPT_B}

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in [PROMPT_A, PROMPT_B] + [src for _, src, _, _ in DATASETS]:
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")
for path in list(OUTPUTS.values()) + list(LOGS.values()):
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)


@dataclass
class OracleResult:
    is_typosquat: bool
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    model: str
    raw: str

    def log_dict(self) -> dict:
        return {"start_time": self.start_time, "end_time": self.end_time,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "model": self.model, "raw": self.raw}


def read_rows(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8") as fin:
        return list(csv.DictReader(fin))


def ask_oracle(prompt: str, record: dict) -> OracleResult:
    """One LLM call: prompt + the record (kept columns, NO dataset tag) -> typed result."""
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt + "\n\n" + json.dumps(record)}],
    )
    end = time.time()
    raw = resp.content[0].text
    m = re.search(r'\{[^{}]*"is_typosquat"[^{}]*\}', raw, re.DOTALL)
    if not m:
        sys.exit(f"ABORT: no is_typosquat in response: {raw!r}")
    val = json.loads(m.group(0))["is_typosquat"]
    if isinstance(val, str):
        val = val.strip().lower() == "true"
    return OracleResult(
        is_typosquat=bool(val), start_time=start, end_time=end,
        input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
        model=MODEL, raw=raw,
    )


def run_variant(tag: str) -> None:
    prompt = open(PROMPTS[tag], encoding="utf-8").read()
    with open(OUTPUTS[tag], "w", encoding="utf-8") as out, \
         open(LOGS[tag], "w", encoding="utf-8") as log:
        for dsname, src, cols, key in DATASETS:
            print(f"\n=== {dsname} x prompt {tag} ===")
            for row in read_rows(src):
                record = {c: row[c] for c in cols}       # kept columns only — this is what the model sees
                result = ask_oracle(prompt, record)
                out.write(json.dumps({"dataset": dsname, **record,
                                      "is_typosquat": result.is_typosquat}, ensure_ascii=False) + "\n")
                log.write(json.dumps({"dataset": dsname, "package": record[key],
                                      **result.log_dict()}, ensure_ascii=False) + "\n")
                out.flush(); log.flush()
                print(f"  {record[key]}: is_typosquat={result.is_typosquat}")


run_variant("A")
run_variant("B")
