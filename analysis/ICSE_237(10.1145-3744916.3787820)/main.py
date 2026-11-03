"""Single-call oracle: a reasoning chain -> per-step validity + proof-path judgment.

One LLM call per record replaces the paper's whole NL->First-Order-Logic->theorem-prover pipeline.
The model receives the premises, the conclusion (question), and the candidate reasoning_steps, and
returns JSON {"step_correctness_label": ["True"|"False"|"Unknown", ...] (one per step),
"has_valid_proof_path_label": <bool>}. Ground truth lives in inputs/<ds>/<model>_labels.json and is
never sent; the evaluator recovers it by (dataset, model, idx).

TSE RERUN CONFIG: prompt B (informed) only, on claude-sonnet-5-5, over every input file
inputs/<dataset>/<model>.json (all 596 records, same sample as the Sonnet 4.6 run). Outputs carry the
LLM id as a suffix so they sit beside the Sonnet 4.6 originals (output_A.jsonl / output_B.jsonl).
THE ONE COMMITTED OUTPUT:
    outputs/output_B_claude-sonnet-5-5.jsonl   — predictions
Each prediction line is tagged with its dataset + model + idx:
    {"dataset", "model", "idx", "step_correctness_label", "has_valid_proof_path_label"}
Per-call log, failures, and per-call tokens + cost go to logs/ (gitignored):
    logs/log_B_claude-sonnet-5-5.jsonl  logs/failures_B_claude-sonnet-5-5.jsonl  logs/tokens_B_claude-sonnet-5-5.jsonl
The run stops before any call that would start once spend has reached BUDGET_USD.

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

MODEL = "claude-sonnet-5-5"   # rejects the `temperature` param (400: deprecated), so we don't send one
MAX_TOKENS = 4096      # headroom for the per-step label list + prompt B's chain-of-thought

# USD per 1M tokens. ASSUMED: Sonnet 4.6's $3/$15 / 1.5 (team email: "1.5x cheaper") — confirm rate.
PRICE_IN_PER_M = 2.0
PRICE_OUT_PER_M = 10.0
BUDGET_USD = 15.0      # hard stop; ~2x the estimate (Opus run: 2.78M in / 0.17M out tokens)

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

# Sent to the model — the chain to verify, nothing else.
INPUT_FIELDS = ["premises", "question", "reasoning_steps"]

# 30 input files (10 models x 3 datasets), built by utils/build_inputs.py; *_labels.json are gold.
INPUT_FILES = sorted(f for f in glob.glob("inputs/*/*.json") if not f.endswith("_labels.json"))
RUNS = [(PROMPT_B, "B")]    # TSE rerun: prompt B only

# Quick smoke test: set to a positive N to run ONLY the first N records of the FIRST input file
# (a handful of paid calls to validate call -> parse -> output). 0 = the full run.
SMOKE = 0
PLAN_FILES = INPUT_FILES[:1] if SMOKE else INPUT_FILES
PLAN_RUNS = RUNS[:1] if SMOKE else RUNS


def variant_paths(variant: str) -> tuple:
    """(predictions, tokens, log, failures) for one prompt variant, suffixed with the LLM id.
    Predictions are the committed output; tokens/logs/failures go to logs/ (gitignored)."""
    tag = f"{variant}_{MODEL}"
    return (os.path.join("outputs", f"output_{tag}.jsonl"),
            os.path.join("logs", f"tokens_{tag}.jsonl"),
            os.path.join("logs", f"log_{tag}.jsonl"),
            os.path.join("logs", f"failures_{tag}.jsonl"))


def call_cost(input_tokens: int, output_tokens: int) -> dict:
    """USD for one call at this run's prices."""
    i, o = input_tokens * PRICE_IN_PER_M / 1e6, output_tokens * PRICE_OUT_PER_M / 1e6
    return {"input_cost": round(i, 6), "output_cost": round(o, 6), "total_cost": round(i + o, 6)}


# Preconditions — hard abort unless everything is set up.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path, _ in RUNS:
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")
if not INPUT_FILES:
    sys.exit("ABORT: no inputs/*/*.json (run utils/build_inputs.py first)")
for _, variant in PLAN_RUNS:
    for path in variant_paths(variant)[:2]:
        if os.path.exists(path):
            sys.exit(f"ABORT: output already exists: {path}")

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
    stop_reason: str
    thinking: bool

    def log_row(self) -> dict:
        return {"idx": self.idx, "start_time": self.start_time, "end_time": self.end_time,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "stop_reason": self.stop_reason, "thinking": self.thinking, "raw": self.raw}


def ask_oracle(prompt: str, row: dict) -> Call:
    """One LLM call: prompt + the input fields -> raw response + call facts (no parsing)."""
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user",
                   "content": prompt + "\n\n" + json.dumps({"inputs": {f: row[f] for f in INPUT_FIELDS}}, indent=2)}],
    )
    end = time.time()
    # Sonnet 5.5 may think before answering, so content[0] can be a ThinkingBlock: keep text blocks only.
    # (output_tokens already includes any thinking tokens, so cost stays exact.)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return Call(row["idx"], start, end, resp.usage.input_tokens, resp.usage.output_tokens, text,
                resp.stop_reason, any(b.type == "thinking" for b in resp.content))


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
    # Fallback (added for Sonnet 5.5, which sometimes answers, explains, then REVISES with a second
    # JSON object -- the greedy match above then spans both): take the LAST complete JSON object that
    # has both keys, i.e. the model's final answer. Only reached when the original logic fails.
    final = last_prediction_object(raw)
    if final is not None:
        return final
    raise ValueError(f"no parseable prediction in response: {raw[:300]!r}")


def last_prediction_object(raw: str):
    """(steps, path) from the last JSON object in `raw` with both keys, else None."""
    dec, found = json.JSONDecoder(strict=False), None
    for i, ch in enumerate(raw):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(raw, i)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and {"step_correctness_label", "has_valid_proof_path_label"} <= obj.keys():
                found = (obj["step_correctness_label"], obj["has_valid_proof_path_label"])
    return found


def run_variant(prompt_file: str, variant: str) -> None:
    """Run one prompt over every input file, writing all predictions to one tagged JSONL."""
    prompt = open(prompt_file, encoding="utf-8").read()
    out_path, tok_path, log_path, fail_path = variant_paths(variant)
    ok = bad = 0
    spent = 0.0
    with open(out_path, "w", encoding="utf-8") as out, \
         open(tok_path, "w", encoding="utf-8") as tok, \
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
                if spent >= BUDGET_USD:
                    print(f"BUDGET: stopping at ${spent:.4f} >= ${BUDGET_USD} "
                          f"({ok} predictions, {bad} failures)", file=sys.stderr)
                    return
                tag = {"dataset": ds, "model": model, "idx": row["idx"]}
                call = None
                try:
                    call = ask_oracle(prompt, row)                          # the paid call
                    log.write(json.dumps({"dataset": ds, "model": model, **call.log_row()}) + "\n"); log.flush()
                    cost = call_cost(call.input_tokens, call.output_tokens)
                    spent += cost["total_cost"]
                    tok.write(json.dumps({"llm": MODEL, "prompt": variant, **tag,
                                          "duration_seconds": round(call.end_time - call.start_time, 3),
                                          "tokens": {"input_tokens": call.input_tokens,
                                                     "output_tokens": call.output_tokens},
                                          "cost_usd": cost}) + "\n"); tok.flush()
                    steps, path = parse_prediction(call.raw)                # may raise
                    out.write(json.dumps({**tag, "step_correctness_label": steps,
                                          "has_valid_proof_path_label": path}) + "\n"); out.flush()
                    ok += 1
                    print(f"  {model} {row['idx']}: ok (ok={ok} fail={bad} spent=${spent:.4f})")
                except Exception as e:
                    bad += 1
                    fail.write(json.dumps({**tag, "error_type": type(e).__name__, "error": str(e),
                                           "raw": call.raw if call is not None else None}) + "\n"); fail.flush()
                    print(f"{ds}/{model} {row['idx']}: FAIL — {type(e).__name__}: {e}", file=sys.stderr)
    print(f"prompt {variant}: {ok} predictions, {bad} failures, ${spent:.4f} -> {out_path}")


for prompt_file, variant in PLAN_RUNS:
    run_variant(prompt_file, variant)
