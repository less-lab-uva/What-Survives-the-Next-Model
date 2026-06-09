"""Single-call code-generation oracle: a programming problem -> a solution program.

One LLM call per problem replaces Specine's whole specification-alignment pipeline. The model
receives only the problem statement (the per-dataset input fields) and returns JSON {"code": "..."}
— a full stdin->stdout program. Ground truth (the test cases) is never sent; the evaluator runs the
returned program against `all_test_cases` (kept in the input files) for Pass@1 / AvgPassRatio.

Runs prompt A (black-box) and prompt B (informed) over the $15 down-sampled benchmarks.
OUTPUT IS EXACTLY TWO COMMITTED FILES — one per prompt variant — in JSONL:
    outputs/output_A.jsonl   outputs/output_B.jsonl
Each line is one prediction tagged with its dataset + problem_id:  {"dataset", "problem_id", "code"}
Per-call logs and failures go to logs/ (gitignored), one pair per variant.

Following ConfuGuard/MATP: fixed config, fail-fast preconditions, no-clobber outputs, per-call
logging. DEVIATION (large paid run): a problem whose response can't be parsed is logged to the
failures file and skipped, so one bad row doesn't waste the run.
"""

import os
import sys
import re
import json
import time
from dataclasses import dataclass
import anthropic

MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0
MAX_TOKENS = 8192      # a full solution program (+ prompt B's reasoning before the code)

PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"

# (input file, fields sent to the model) per benchmark — the $15 down-sampled sets. Everything else
# in each record (solutions, all_test_cases, metadata) is filtered out and never sent.
DATASETS = {
    "apps":          ("inputs/apps.down_sampled_15usd.jsonl",          ["question", "starter_code"]),
    "code_contests": ("inputs/code_contests.down_sampled_15usd.jsonl", ["description"]),
    "xCodeEval":     ("inputs/xCodeEval.down_sampled_15usd.jsonl",      ["description", "input_spec", "output_spec", "notes"]),
}
RUNS = [(PROMPT_A, "A"), (PROMPT_B, "B")]

# Quick smoke test: set to a positive N to run ONLY the first N problems of the FIRST benchmark
# with prompt A (a handful of paid calls to validate call -> parse -> output). 0 = the full run.
SMOKE = 0
PLAN_DATASETS = list(DATASETS.items())[:1] if SMOKE else list(DATASETS.items())
PLAN_RUNS = RUNS[:1] if SMOKE else RUNS


def variant_paths(variant: str) -> tuple:
    """(predictions, log, failures) for one prompt variant — predictions committed, logs gitignored."""
    return (os.path.join("outputs", f"output_{variant}.jsonl"),
            os.path.join("logs", f"log_{variant}.jsonl"),
            os.path.join("logs", f"failures_{variant}.jsonl"))


# Preconditions — hard abort unless everything is set up.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in (PROMPT_A, PROMPT_B):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path}")
for ds, (infile, _) in DATASETS.items():
    if not os.path.exists(infile):
        sys.exit(f"ABORT: missing {infile} (run utils/build_inputs.py + utils/sample_to_budget.py)")
for _, variant in PLAN_RUNS:
    out_path, _, _ = variant_paths(variant)
    if os.path.exists(out_path):
        sys.exit(f"ABORT: output already exists: {out_path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)


@dataclass
class Call:
    problem_id: object
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    raw: str

    def log_row(self) -> dict:
        return {"problem_id": self.problem_id, "start_time": self.start_time, "end_time": self.end_time,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "raw": self.raw}


def parse_code(raw: str) -> str:
    """Extract the solution program. Prefer a ```python fenced block (models usually emit one even
    when asked for JSON); else the {"code": "..."} JSON; else the raw response."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    m = re.search(r'\{.*"code"\s*:.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0), strict=False)["code"]
        except (json.JSONDecodeError, KeyError):
            pass
    return raw.strip()


def ask_oracle(prompt: str, fields: list, problem: dict) -> Call:
    """One LLM call: prompt + the dataset's input fields -> raw response + call facts."""
    record = {f: (problem.get(f) or "") for f in fields}
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt + "\n\n" + json.dumps({"inputs": record}, indent=2)}],
    )
    end = time.time()
    return Call(problem["problem_id"], start, end, resp.usage.input_tokens, resp.usage.output_tokens,
                resp.content[0].text)


def run_variant(prompt_file: str, variant: str) -> None:
    """Run one prompt over every benchmark, writing all predictions to one tagged JSONL."""
    prompt = open(prompt_file, encoding="utf-8").read()
    out_path, log_path, fail_path = variant_paths(variant)
    ok = bad = 0
    with open(out_path, "w", encoding="utf-8") as out, \
         open(log_path, "w", encoding="utf-8") as log, \
         open(fail_path, "w", encoding="utf-8") as fail:
        for ds, (infile, fields) in PLAN_DATASETS:
            rows = [json.loads(line) for line in open(infile, encoding="utf-8") if line.strip()]
            if SMOKE:
                rows = rows[:SMOKE]
            print(f"\n=== prompt {variant} x {ds} ({len(rows)} problems) ===")
            for problem in rows:
                tag = {"dataset": ds, "problem_id": problem["problem_id"]}
                call = None
                try:
                    call = ask_oracle(prompt, fields, problem)             # the paid call
                    log.write(json.dumps({"dataset": ds, **call.log_row()}) + "\n"); log.flush()
                    code = parse_code(call.raw)
                    out.write(json.dumps({**tag, "code": code}) + "\n"); out.flush()
                    ok += 1
                    print(f"  {ds} {problem['problem_id']}: ok (ok={ok} fail={bad})")
                except Exception as e:
                    bad += 1
                    fail.write(json.dumps({**tag, "error_type": type(e).__name__, "error": str(e),
                                           "raw": call.raw if call is not None else None}) + "\n"); fail.flush()
                    print(f"  {ds} {problem['problem_id']}: FAIL — {type(e).__name__}: {e}", file=sys.stderr)
    print(f"prompt {variant}: {ok} predictions, {bad} failures -> {out_path}")


for prompt_file, variant in PLAN_RUNS:
    run_variant(prompt_file, variant)
