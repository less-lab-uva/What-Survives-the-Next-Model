"""ConfuGuard single-call oracle: package (minus ground truth) -> is_typosquat.

Replaces ConfuGuard's whole pipeline with one LLM call per row. Each dataset has its own
function with its own columns hardcoded; the row is stripped to the non-label, non-leaking
columns, handed to the model, and the model returns a binary {"is_typosquat": true|false}.
Runs prompt A and prompt B. Ground truth is never sent — it's recovered later by joining
the result file back to the source CSV on the kept columns.

Each run writes a result CSV (the kept input columns + is_typosquat) and a raw per-call
log CSV (timestamps, token counts, model, and the raw model response).

Reproducibility: refuses to run unless the API key, both prompts, and all three datasets
are present, and it will NOT overwrite existing result/log files. Anything not perfectly
set up is a hard abort.
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

# Columns NOT sent to the LLM, and why (a new package only has its name + registry; the rest
# is the label, the target, or dataset-construction provenance that would leak the answer):
#   ConfuDB:      threat_type (label), description (analyst note->leaks), legitimate_package (target)
#   real_malware: confusion (label), legitimate_pkg (target),
#                 categories/source/study/source_file (confirmed-attack provenance -> leaks),
#                 hallucianated (data-collection artifact)
#   no_malware:   is_FP? (label), Original pkg (target), FP Categories / Comment (leaks)

# the $15 budget-sampled datasets (produced by utils/sample_to_budget.py)
CONFUDB      = "inputs/ConfuDB.down_sampled_15usd.csv"
REAL_MALWARE = "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv"
NO_MALWARE   = "inputs/NeupaneDB_no_malware.down_sampled_15usd.csv"

# output/log names mirror the down-sampled input filenames they were produced from
OUT_A_CONFUDB = "outputs/oracle-claude-sonnet-4-6-a-ConfuDB.down_sampled_15usd.csv"
OUT_B_CONFUDB = "outputs/oracle-claude-sonnet-4-6-b-ConfuDB.down_sampled_15usd.csv"
OUT_A_REAL    = "outputs/oracle-claude-sonnet-4-6-a-NeupaneDB_real_malware.down_sampled_15usd.csv"
OUT_B_REAL    = "outputs/oracle-claude-sonnet-4-6-b-NeupaneDB_real_malware.down_sampled_15usd.csv"
OUT_A_NOMAL   = "outputs/oracle-claude-sonnet-4-6-a-NeupaneDB_no_malware.down_sampled_15usd.csv"
OUT_B_NOMAL   = "outputs/oracle-claude-sonnet-4-6-b-NeupaneDB_no_malware.down_sampled_15usd.csv"

LOG_A_CONFUDB = "outputs/log-claude-sonnet-4-6-a-ConfuDB.down_sampled_15usd.csv"
LOG_B_CONFUDB = "outputs/log-claude-sonnet-4-6-b-ConfuDB.down_sampled_15usd.csv"
LOG_A_REAL    = "outputs/log-claude-sonnet-4-6-a-NeupaneDB_real_malware.down_sampled_15usd.csv"
LOG_B_REAL    = "outputs/log-claude-sonnet-4-6-b-NeupaneDB_real_malware.down_sampled_15usd.csv"
LOG_A_NOMAL   = "outputs/log-claude-sonnet-4-6-a-NeupaneDB_no_malware.down_sampled_15usd.csv"
LOG_B_NOMAL   = "outputs/log-claude-sonnet-4-6-b-NeupaneDB_no_malware.down_sampled_15usd.csv"

LOG_FIELDS = ["package", "start_time", "end_time", "input_tokens", "output_tokens", "model", "raw"]

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")

for path in (PROMPT_A, PROMPT_B, CONFUDB, REAL_MALWARE, NO_MALWARE):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")

for path in (OUT_A_CONFUDB, OUT_B_CONFUDB, OUT_A_REAL, OUT_B_REAL, OUT_A_NOMAL, OUT_B_NOMAL,
             LOG_A_CONFUDB, LOG_B_CONFUDB, LOG_A_REAL, LOG_B_REAL, LOG_A_NOMAL, LOG_B_NOMAL):
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)


@dataclass
class OracleResult:
    is_typosquat: bool
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    model: str
    raw: str

    def log_row(self, package: str) -> dict:
        return {"package": package, "start_time": self.start_time, "end_time": self.end_time,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "model": self.model, "raw": self.raw}


def read_rows(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8") as fin:
        return list(csv.DictReader(fin))


def ask_oracle(prompt: str, record: dict) -> OracleResult:
    """One LLM call: prompt + the record (kept columns) -> typed result + call facts."""
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


def run_confudb(prompt_file: str, output_csv: str, log_csv: str) -> None:
    prompt = open(prompt_file, encoding="utf-8").read()
    print(f"\n=== ConfuDB x {prompt_file} -> {output_csv} ===")
    with open(output_csv, "w", newline="", encoding="utf-8") as f, \
         open(log_csv, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(f, fieldnames=["type", "name", "namespace", "is_typosquat"])
        writer.writeheader()
        logger = csv.DictWriter(lf, fieldnames=LOG_FIELDS)
        logger.writeheader()
        for row in read_rows(CONFUDB):
            record = {"type": row["type"], "name": row["name"], "namespace": row["namespace"]}
            result = ask_oracle(prompt, record)
            writer.writerow({**record, "is_typosquat": result.is_typosquat})
            logger.writerow(result.log_row(record["name"]))
            f.flush(); lf.flush()
            print(f"{record['name']}: is_typosquat={result.is_typosquat}")


def run_real_malware(prompt_file: str, output_csv: str, log_csv: str) -> None:
    prompt = open(prompt_file, encoding="utf-8").read()
    print(f"\n=== NeupaneDB real_malware x {prompt_file} -> {output_csv} ===")
    with open(output_csv, "w", newline="", encoding="utf-8") as f, \
         open(log_csv, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(f, fieldnames=["typosquat_pkg", "registry", "is_typosquat"])
        writer.writeheader()
        logger = csv.DictWriter(lf, fieldnames=LOG_FIELDS)
        logger.writeheader()
        for row in read_rows(REAL_MALWARE):
            record = {"typosquat_pkg": row["typosquat_pkg"], "registry": row["registry"]}
            result = ask_oracle(prompt, record)
            writer.writerow({**record, "is_typosquat": result.is_typosquat})
            logger.writerow(result.log_row(record["typosquat_pkg"]))
            f.flush(); lf.flush()
            print(f"{record['typosquat_pkg']}: is_typosquat={result.is_typosquat}")


def run_no_malware(prompt_file: str, output_csv: str, log_csv: str) -> None:
    prompt = open(prompt_file, encoding="utf-8").read()
    print(f"\n=== NeupaneDB no_malware x {prompt_file} -> {output_csv} ===")
    with open(output_csv, "w", newline="", encoding="utf-8") as f, \
         open(log_csv, "w", newline="", encoding="utf-8") as lf:
        writer = csv.DictWriter(f, fieldnames=["Adversarial pkg", "Ecosystem", "is_typosquat"])
        writer.writeheader()
        logger = csv.DictWriter(lf, fieldnames=LOG_FIELDS)
        logger.writeheader()
        for row in read_rows(NO_MALWARE):
            record = {"Adversarial pkg": row["Adversarial pkg"], "Ecosystem": row["Ecosystem"]}
            result = ask_oracle(prompt, record)
            writer.writerow({**record, "is_typosquat": result.is_typosquat})
            logger.writerow(result.log_row(record["Adversarial pkg"]))
            f.flush(); lf.flush()
            print(f"{record['Adversarial pkg']}: is_typosquat={result.is_typosquat}")


run_confudb(PROMPT_A, OUT_A_CONFUDB, LOG_A_CONFUDB)
run_confudb(PROMPT_B, OUT_B_CONFUDB, LOG_B_CONFUDB)
run_real_malware(PROMPT_A, OUT_A_REAL, LOG_A_REAL)
run_real_malware(PROMPT_B, OUT_B_REAL, LOG_B_REAL)
run_no_malware(PROMPT_A, OUT_A_NOMAL, LOG_A_NOMAL)
run_no_malware(PROMPT_B, OUT_B_NOMAL, LOG_B_NOMAL)
