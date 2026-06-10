"""IntentFix RQ1 single-call repair oracle: vulnerable code + description -> fixed code.

One LLM call per pair replaces IntentFix's whole multi-phase intent-modeling pipeline. The model
receives only the two fields the paper's baseline gets (section 4.3) -- the vulnerable code and a
high-level description of the vulnerability -- and returns JSON {"fixed_code": "..."}, a full
corrected file. Ground truth (the human patch) is never sent; evaluator.py judges the patch later.

Runs Prompt A (black-box) and Prompt B (informed). OUTPUT IS TWO COMMITTED FILES -- one per prompt:
    outputs/output_A.jsonl   outputs/output_B.jsonl     {pair_id, fixed_code}
Per-call logs (timing + tokens), a usage summary, and failures go to logs/ (gitignored):
    logs/log_A.jsonl  logs/usage_A.json  logs/failures_A.jsonl   (and _B)

The two pairs embedded as few-shot examples in the prompts (dataset/heldout_fewshot_ids.json) are
skipped, to avoid evaluating on demonstrations.

Reproducibility (following the sibling reproductions): fixed config, fail-fast preconditions,
no-clobber outputs. DEVIATION (large paid run): a pair whose call fails is logged to the failures
file and skipped, so one bad row doesn't waste the run.
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
MAX_TOKENS = 8192      # a full corrected file (+ prompt B's reasoning before the JSON)

DATASET = "dataset/intentfix_pairs.jsonl"
HELDOUT = "dataset/heldout_fewshot_ids.json"

# Prompt A (black-box).
PROMPT_A   = "prompts/prompt_A.txt"
OUTPUT_A   = "outputs/output_A.jsonl"
LOG_A      = "logs/log_A.jsonl"
USAGE_A    = "logs/usage_A.json"
FAILURES_A = "logs/failures_A.jsonl"

# Prompt B (informed).
PROMPT_B   = "prompts/prompt_B.txt"
OUTPUT_B   = "outputs/output_B.jsonl"
LOG_B      = "logs/log_B.jsonl"
USAGE_B    = "logs/usage_B.json"
FAILURES_B = "logs/failures_B.jsonl"

# Quick smoke test: set to a positive N to run ONLY the first N pairs. 0 = the full dataset.
SMOKE = 5

# Preconditions -- hard abort unless everything is set up.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
if not os.path.exists(PROMPT_A):
    sys.exit(f"ABORT: missing {PROMPT_A} (run utils/prompt_generator.py)")
if not os.path.exists(PROMPT_B):
    sys.exit(f"ABORT: missing {PROMPT_B} (run utils/prompt_generator.py)")
if not os.path.exists(DATASET):
    sys.exit(f"ABORT: missing {DATASET} (run utils/produce_dataset.py)")
if not os.path.exists(HELDOUT):
    sys.exit(f"ABORT: missing {HELDOUT}")
for path in (OUTPUT_A, LOG_A, USAGE_A, FAILURES_A, OUTPUT_B, LOG_B, USAGE_B, FAILURES_B):
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)


@dataclass
class Call:
    pair_id: str
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    raw: str

    def log_row(self) -> dict:
        return {"pair_id": self.pair_id, "start_time": self.start_time, "end_time": self.end_time,
                "duration_s": round(self.end_time - self.start_time, 3),
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "model": MODEL, "raw": self.raw}


def load_dataset() -> list:
    """Pairs from the JSONL, with the held-out few-shot examples removed."""
    heldout = set(json.load(open(HELDOUT, encoding="utf-8"))["heldout_pair_ids"])
    rows = [json.loads(line) for line in open(DATASET, encoding="utf-8") if line.strip()]
    kept = [r for r in rows if r["pair_id"] not in heldout]
    print(f"Loaded {len(rows)} pairs; {len(rows) - len(kept)} held-out example(s) removed; {len(kept)} to run.")
    return kept[:SMOKE] if SMOKE else kept


def parse_fixed_code(raw: str) -> str:
    """Extract the corrected file. Prefer a fenced code block (models usually emit one even when
    asked for JSON); else the {"fixed_code": "..."} JSON; else the raw response."""
    blocks = re.findall(r"```(?:[a-zA-Z0-9+#]*)\s*\n(.*?)\n```", raw, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    m = re.search(r'\{.*"fixed_code"\s*:.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0), strict=False)["fixed_code"]
        except (json.JSONDecodeError, KeyError):
            pass
    return raw.strip()


def ask_oracle(prompt: str, pair: dict) -> Call:
    """One LLM call: prompt + the two input fields (vulnerable code + description) -> raw + facts."""
    record = {"buggy_code": pair.get("buggy_code") or "",
              "vulnerability_description": pair.get("vulnerability_description") or ""}
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt + "\n\n" + json.dumps({"inputs": record}, indent=2)}],
    )
    end = time.time()
    return Call(pair["pair_id"], start, end,
                resp.usage.input_tokens, resp.usage.output_tokens, resp.content[0].text)


def run_prompt(prompt_file, output_file, log_file, usage_file, failures_file, label):
    """Run one prompt over every (non-held-out) pair, writing predictions + logs + failures + usage."""
    prompt = open(prompt_file, encoding="utf-8").read()
    pairs = load_dataset()
    print(f"\n=== prompt {label}: {len(pairs)} pairs ===")

    ok = bad = 0
    in_tok = out_tok = 0
    run_start = time.time()
    with open(output_file, "w", encoding="utf-8") as out, \
         open(log_file, "w", encoding="utf-8") as log, \
         open(failures_file, "w", encoding="utf-8") as fail:
        for i, pair in enumerate(pairs):
            pid = pair["pair_id"]
            call = None
            try:
                call = ask_oracle(prompt, pair)                       # the paid call
                log.write(json.dumps(call.log_row(), ensure_ascii=False) + "\n"); log.flush()
                fixed = parse_fixed_code(call.raw)
                out.write(json.dumps({"pair_id": pid, "fixed_code": fixed}, ensure_ascii=False) + "\n"); out.flush()
                ok += 1
                in_tok += call.input_tokens; out_tok += call.output_tokens
                print(f"  [{i+1}/{len(pairs)}] {pid}: ok (ok={ok} fail={bad})")
            except Exception as e:
                bad += 1
                fail.write(json.dumps({"pair_id": pid, "error_type": type(e).__name__, "error": str(e),
                                       "raw": call.raw if call is not None else None}, ensure_ascii=False) + "\n")
                fail.flush()
                print(f"  [{i+1}/{len(pairs)}] {pid}: FAIL -- {type(e).__name__}: {e}", file=sys.stderr)

    usage = {"prompt": label, "model": MODEL, "pairs_run": len(pairs),
             "predictions": ok, "failures": bad,
             "input_tokens": in_tok, "output_tokens": out_tok,
             "wall_time_s": round(time.time() - run_start, 1)}
    json.dump(usage, open(usage_file, "w"), indent=2)
    print(f"prompt {label}: {ok} predictions, {bad} failures | "
          f"{in_tok}+{out_tok} tok | {usage['wall_time_s']}s -> {output_file}")


run_prompt(PROMPT_A, OUTPUT_A, LOG_A, USAGE_A, FAILURES_A, "A")
run_prompt(PROMPT_B, OUTPUT_B, LOG_B, USAGE_B, FAILURES_B, "B")
