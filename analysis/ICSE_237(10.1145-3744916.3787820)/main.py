"""Single-call oracle: a reasoning chain -> per-step validity + proof-path judgment.

One LLM call per record replaces the paper's whole NL->First-Order-Logic->theorem-prover pipeline.
The model receives the premises, the conclusion (question), and the candidate reasoning_steps, and
returns JSON {"step_correctness_label": ["True"|"False"|"Unknown", ...] (one per step),
"has_valid_proof_path_label": <bool>}. Ground truth lives in inputs/<ds>/<model>_labels.json and is
never sent; the evaluator recovers it by (dataset, model, idx).

Runs prompt A (black-box) and prompt B (informed) over every input file inputs/<dataset>/<model>.json.
OUTPUT IS EXACTLY TWO COMMITTED FILES — one per prompt variant — in JSONL:
    outputs/output_A.jsonl   outputs/output_B.jsonl
Each line is one prediction tagged with its dataset + model + idx:
    {"dataset", "model", "idx", "step_correctness_label", "has_valid_proof_path_label"}
Per-call logs and failures go to logs/ (gitignored), one pair per variant.

Following ConfuGuard: fixed config, fail-fast preconditions, no-clobber outputs, per-call logging.
DEVIATION (like AssertFlip's large paid run): a record whose response can't be parsed is logged to
the failures file and skipped, so one bad row doesn't waste a multi-hundred-row paid run.
"""

import os
import sys
import re
import json
import time
import glob
from pathlib import Path
from dataclasses import dataclass
import anthropic

MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0
MAX_TOKENS = 4096      # headroom for the per-step label list + prompt B's chain-of-thought

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

# Sent to the model — the chain to verify, nothing else.
INPUT_FIELDS = ["premises", "question", "reasoning_steps"]

# 30 input files (10 models x 3 datasets), built by utils/build_inputs.py; *_labels.json are gold.
INPUT_FILES = sorted(f for f in glob.glob("inputs/*/*.json") if not f.endswith("_labels.json"))
RUNS = [(PROMPT_A, "A"), (PROMPT_B, "B")]

# Quick smoke test: set to a positive N to run ONLY the first N records of the FIRST input file
# with prompt A (a handful of paid calls to validate call -> parse -> output). 0 = the full run.
SMOKE = 0
PLAN_FILES = INPUT_FILES[:1] if SMOKE else INPUT_FILES
PLAN_RUNS = RUNS[:1] if SMOKE else RUNS


def variant_paths(variant: str) -> tuple:
    """(predictions, log, failures) for one prompt variant. Predictions are the committed output;
    logs/failures go to logs/ (gitignored)."""
    return (os.path.join("outputs", f"output_{variant}.jsonl"),
            os.path.join("logs", f"log_{variant}.jsonl"),
            os.path.join("logs", f"failures_{variant}.jsonl"))


# Preconditions — hard abort unless everything is set up.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in (PROMPT_A, PROMPT_B):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")
if not INPUT_FILES:
    sys.exit("ABORT: no inputs/*/*.json (run utils/build_inputs.py first)")
for _, variant in PLAN_RUNS:
    out_path, _, _ = variant_paths(variant)
    if os.path.exists(out_path):
        sys.exit(f"ABORT: output already exists: {out_path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)


@dataclass
class Call:
    """One LLM call's raw result + facts (parsing happens separately so a parse failure can log raw)."""
    idx: str
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    raw: str

    def log_row(self) -> dict:
        return {"idx": self.idx, "start_time": self.start_time, "end_time": self.end_time,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "raw": self.raw}


def ask_oracle(prompt: str, row: dict) -> Call:
    """One LLM call: prompt + the input fields -> raw response + call facts (no parsing)."""
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
        messages=[{"role": "user",
                   "content": prompt + "\n\n" + json.dumps({"inputs": {f: row[f] for f in INPUT_FIELDS}}, indent=2)}],
    )
    end = time.time()
    return Call(row["idx"], start, end, resp.usage.input_tokens, resp.usage.output_tokens, resp.content[0].text)


def parse_prediction(raw: str) -> tuple:
    """Extract (step_correctness_label, has_valid_proof_path_label) from the model's JSON.
    Prompt B may reason before the JSON, so pick the fenced block that contains the key."""
    blocks = re.findall(r"```[a-zA-Z0-9]*\s*\n(.*?)\n```", raw, re.DOTALL)
    candidates = [b for b in blocks if '"step_correctness_label"' in b] or [raw]
    for cand in candidates:
        m = re.search(r'\{.*"step_correctness_label".*\}', cand, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0), strict=False)
                return obj["step_correctness_label"], obj["has_valid_proof_path_label"]
            except (json.JSONDecodeError, KeyError):
                continue
    raise ValueError(f"no parseable prediction in response: {raw[:300]!r}")


def run_variant(prompt_file: str, variant: str) -> None:
    """Run one prompt over every input file, writing all predictions to one tagged JSONL."""
    prompt = open(prompt_file, encoding="utf-8").read()
    out_path, log_path, fail_path = variant_paths(variant)
    ok = bad = 0
    with open(out_path, "w", encoding="utf-8") as out, \
         open(log_path, "w", encoding="utf-8") as log, \
         open(fail_path, "w", encoding="utf-8") as fail:
        for in_path in PLAN_FILES:
            ds = in_path.split(os.sep)[1]
            model = Path(in_path).stem
            rows = json.load(open(in_path, encoding="utf-8"))
            if SMOKE:
                rows = rows[:SMOKE]
            print(f"\n=== prompt {variant} x {in_path} ({len(rows)} rows) ===")
            for row in rows:
                tag = {"dataset": ds, "model": model, "idx": row["idx"]}
                call = None
                try:
                    call = ask_oracle(prompt, row)                          # the paid call
                    log.write(json.dumps({"dataset": ds, "model": model, **call.log_row()}) + "\n"); log.flush()
                    steps, path = parse_prediction(call.raw)                # may raise
                    out.write(json.dumps({**tag, "step_correctness_label": steps,
                                          "has_valid_proof_path_label": path}) + "\n"); out.flush()
                    ok += 1
                    print(f"  {model} {row['idx']}: ok (ok={ok} fail={bad})")
                except Exception as e:
                    bad += 1
                    fail.write(json.dumps({**tag, "error_type": type(e).__name__, "error": str(e),
                                           "raw": call.raw if call is not None else None}) + "\n"); fail.flush()
                    print(f"{ds}/{model} {row['idx']}: FAIL — {type(e).__name__}: {e}", file=sys.stderr)
    print(f"prompt {variant}: {ok} predictions, {bad} failures -> {out_path}")


for prompt_file, variant in PLAN_RUNS:
    run_variant(prompt_file, variant)
