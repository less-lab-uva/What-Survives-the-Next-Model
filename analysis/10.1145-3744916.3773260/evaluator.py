"""IntentFix RQ1 AI-oracle evaluation: judge each generated patch for correctness.

Uses the IntentFix replication package's ACTUAL AI oracle prompt (prompts/evaluator.txt, the one
run_experiments.py runs with o4-mini) -- 4 criteria + a richer JSON verdict -- rather than the
paper's 2-criteria prose. For each case the oracle gets the vulnerable code + CWE description, the
generated patch, and the ground-truth fix, and returns {"is_correct", ...}. Metric: patch accuracy
(fraction judged correct). See build_judge_prompt for the verbatim prompt + source URL.

Joins each prediction (outputs/output_<v>.jsonl: pair_id + fixed_code) back to the dataset by
pair_id to recover the vulnerable code, ground-truth fix, and CWE description. OUTPUT IS TWO
COMMITTED FILES -- the AGGREGATE only (accuracy + per-CWE breakdown), one per prompt:
    results/result_A.json   results/result_B.json
The per-pair verdicts go to logs/judgements_{A,B}.jsonl (gitignored), alongside the per-call judge
logs (timing + tokens), a usage summary, and failures.

Same rules as main.py: fixed config, fail-fast preconditions (predictions MUST exist; results must
NOT), no-clobber, explicit per-prompt calls. A pair whose judge call fails is logged and skipped.
"""

import os
import sys
import re
import json
import time
from dataclasses import dataclass
from collections import defaultdict
import anthropic

JUDGE_MODEL = "claude-sonnet-4-6"
TEMPERATURE = 0.0
MAX_TOKENS = 1024

DATASET = "dataset/intentfix_pairs.jsonl"

# Prompt A (black-box).
INPUT_A         = "outputs/output_A.jsonl"
RESULT_A        = "results/result_A.json"            # aggregate only (committed)
JUDGEMENTS_A    = "logs/judgements_A.jsonl"           # per-pair verdicts (gitignored)
EVAL_LOG_A      = "logs/eval_log_A.jsonl"
EVAL_USAGE_A    = "logs/eval_usage_A.json"
EVAL_FAILURES_A = "logs/eval_failures_A.jsonl"

# Prompt B (informed).
INPUT_B         = "outputs/output_B.jsonl"
RESULT_B        = "results/result_B.json"            # aggregate only (committed)
JUDGEMENTS_B    = "logs/judgements_B.jsonl"           # per-pair verdicts (gitignored)
EVAL_LOG_B      = "logs/eval_log_B.jsonl"
EVAL_USAGE_B    = "logs/eval_usage_B.json"
EVAL_FAILURES_B = "logs/eval_failures_B.jsonl"

# Preconditions -- hard abort unless everything is set up.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
if not os.path.exists(DATASET):
    sys.exit(f"ABORT: missing {DATASET} (run utils/produce_dataset.py)")
if not os.path.exists(INPUT_A):
    sys.exit(f"ABORT: missing predictions {INPUT_A} (run main.py first)")
if not os.path.exists(INPUT_B):
    sys.exit(f"ABORT: missing predictions {INPUT_B} (run main.py first)")
for path in (RESULT_A, JUDGEMENTS_A, EVAL_LOG_A, EVAL_USAGE_A, EVAL_FAILURES_A,
             RESULT_B, JUDGEMENTS_B, EVAL_LOG_B, EVAL_USAGE_B, EVAL_FAILURES_B):
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("results", exist_ok=True)
os.makedirs("logs", exist_ok=True)



@dataclass
class Judgement:
    pair_id: str
    cwe: str
    is_correct: bool
    reasoning: str
    parse_ok: bool
    start_time: float
    end_time: float
    input_tokens: int
    output_tokens: int
    raw: str

    def log_row(self) -> dict:
        return {"pair_id": self.pair_id, "start_time": self.start_time, "end_time": self.end_time,
                "duration_s": round(self.end_time - self.start_time, 3),
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "model": JUDGE_MODEL, "raw": self.raw}

    def result_row(self) -> dict:
        return {"pair_id": self.pair_id, "cwe": self.cwe, "is_correct": self.is_correct,
                "reasoning": self.reasoning, "judge_parse_ok": self.parse_ok}


def load_dataset_index() -> dict:
    """pair_id -> {buggy_code, human_patch, vulnerability_description, cwe} for the join."""
    idx = {}
    for line in open(DATASET, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            idx[r["pair_id"]] = r
    return idx


def build_judge_prompt(buggy_code, generated_patch, human_patch, cwe, cwe_description) -> str:
    """The IntentFix AI-oracle prompt, VERBATIM from their replication package's evaluator:
        prompts/evaluator.txt  (== the inline f-string in evaluator.py::check_correct_ai_automated,
        the oracle that run_experiments.py actually runs with o4-mini, 2-of-3 majority).
    Raw source (pinned commit):
        https://raw.githubusercontent.com/mrhjs225/intentfix-icse2026/4873f172e3059c62ddc86980ef321ed25d287ac7/prompts/evaluator.txt

    Their run_experiments.py passed only {"pair_id": ...} as "Vulnerability Information", so the
    judge never saw the vulnerability. Per the paper (sec 4.4.1) the oracle is meant to receive the
    vulnerable code and the CWE description, so we put both in that slot here.
    """
    vulnerability_info = (f"{cwe}: {cwe_description}\n\n"
                          f"Vulnerable code:\n{buggy_code}")
    return (
        "You are an expert security researcher and code reviewer. Your task is to evaluate "
        "whether a generated patch correctly fixes a security vulnerability.\n\n"
        "Context:\n"
        "- Vulnerability Information: " + vulnerability_info + "\n"
        "- Human Patch (Ground Truth): " + human_patch + "\n"
        "- Generated Patch (Candidate): " + (generated_patch or "") + "\n\n"
        "Evaluation Criteria:\n"
        "1. Does the generated patch address the same root cause as the human patch?\n"
        "2. Is the generated patch semantically equivalent to the human patch?\n"
        "3. Does the generated patch properly handle the security vulnerability?\n"
        "4. Are there any potential regressions or side effects?\n\n"
        "Please provide your evaluation in JSON format:\n"
        "{\n"
        '    "is_correct": boolean,\n'
        '    "confidence": float (0.0-1.0),\n'
        '    "reasoning": "Detailed explanation of your evaluation",\n'
        '    "semantic_equivalence": boolean,\n'
        '    "security_effectiveness": boolean\n'
        "}"
    )


def parse_verdict(raw: str) -> tuple:
    """(is_correct, reasoning, parse_ok) from the oracle response, robust to fences/prose."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    blob = fenced.group(1) if fenced else None
    if blob is None:
        s, e = raw.find("{"), raw.rfind("}")
        blob = raw[s:e + 1] if (s != -1 and e > s) else None
    if blob:
        try:
            d = json.loads(blob)
            return bool(d.get("is_correct", False)), str(d.get("reasoning", "")), True
        except json.JSONDecodeError:
            pass
    m = re.search(r'"?is_correct"?\s*[:=]\s*(true|false)', raw, re.IGNORECASE)
    if m:
        return m.group(1).lower() == "true", raw.strip()[:500], True
    return False, raw.strip()[:500], False


def judge_pair(pair_id, fixed_code, data) -> Judgement:
    """One judge call for one prediction. data = the dataset record for this pair_id."""
    prompt = build_judge_prompt(data["buggy_code"], fixed_code, data["human_patch"],
                                data.get("cwe", "Unknown"), data["vulnerability_description"])
    start = time.time()
    resp = client.messages.create(
        model=JUDGE_MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    end = time.time()
    raw = resp.content[0].text
    is_correct, reasoning, parse_ok = parse_verdict(raw)
    return Judgement(pair_id, data.get("cwe", "Unknown"), is_correct, reasoning, parse_ok,
                     start, end, resp.usage.input_tokens, resp.usage.output_tokens, raw)


def write_result(result_file, judgements_file, label, verdicts):
    """Aggregate (accuracy + per-CWE) -> results/result_<v>.json (committed).
    Per-pair verdicts -> logs/judgements_<v>.jsonl (gitignored)."""
    total = len(verdicts)
    correct = sum(1 for j in verdicts if j.is_correct)
    by_cwe = defaultdict(lambda: {"correct": 0, "total": 0})
    for j in verdicts:
        by_cwe[j.cwe]["total"] += 1
        by_cwe[j.cwe]["correct"] += int(j.is_correct)
    aggregate = {
        "prompt": label,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct, "total": total,
        "by_cwe": {k: {"correct": v["correct"], "total": v["total"],
                       "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0.0}
                   for k, v in sorted(by_cwe.items())},
    }
    json.dump(aggregate, open(result_file, "w", encoding="utf-8"), indent=2)
    with open(judgements_file, "w", encoding="utf-8") as f:
        for j in verdicts:
            f.write(json.dumps(j.result_row(), ensure_ascii=False) + "\n")


def evaluate_prompt(input_file, result_file, judgements_file, log_file, usage_file, failures_file, label):
    """Judge every prediction for one prompt; write result + logs + failures + usage."""
    index = load_dataset_index()
    preds = [json.loads(line) for line in open(input_file, encoding="utf-8") if line.strip()]
    print(f"\n=== prompt {label}: judging {len(preds)} predictions ===")

    verdicts = []
    in_tok = out_tok = 0
    run_start = time.time()
    with open(log_file, "w", encoding="utf-8") as log, \
         open(failures_file, "w", encoding="utf-8") as fail:
        for i, pred in enumerate(preds):
            pid = pred["pair_id"]
            if pid not in index:
                fail.write(json.dumps({"pair_id": pid, "error": "pair_id not in dataset"}) + "\n"); fail.flush()
                print(f"  [{i+1}/{len(preds)}] {pid}: FAIL -- not in dataset", file=sys.stderr)
                continue
            fixed = pred.get("fixed_code") or ""
            if not fixed.strip():   # no patch generated -> incorrect, no paid call needed
                j = Judgement(pid, index[pid].get("cwe", "Unknown"), False, "no generated patch",
                              True, time.time(), time.time(), 0, 0, "")
            else:
                try:
                    j = judge_pair(pid, fixed, index[pid])              # the paid call
                except Exception as e:
                    fail.write(json.dumps({"pair_id": pid, "error_type": type(e).__name__,
                                           "error": str(e)}) + "\n"); fail.flush()
                    print(f"  [{i+1}/{len(preds)}] {pid}: FAIL -- {type(e).__name__}: {e}", file=sys.stderr)
                    continue
            log.write(json.dumps(j.log_row(), ensure_ascii=False) + "\n"); log.flush()
            verdicts.append(j)
            in_tok += j.input_tokens; out_tok += j.output_tokens
            print(f"  [{i+1}/{len(preds)}] {pid} ({j.cwe}) -> {'CORRECT' if j.is_correct else 'INCORRECT'}")

    write_result(result_file, judgements_file, label, verdicts)
    usage = {"prompt": label, "model": JUDGE_MODEL, "judged": len(verdicts),
             "input_tokens": in_tok, "output_tokens": out_tok,
             "wall_time_s": round(time.time() - run_start, 1)}
    json.dump(usage, open(usage_file, "w"), indent=2)
    correct = sum(1 for j in verdicts if j.is_correct)
    print(f"prompt {label}: accuracy {correct}/{len(verdicts)} | "
          f"{usage['wall_time_s']}s -> {result_file}")


evaluate_prompt(INPUT_A, RESULT_A, JUDGEMENTS_A, EVAL_LOG_A, EVAL_USAGE_A, EVAL_FAILURES_A, "A")
evaluate_prompt(INPUT_B, RESULT_B, JUDGEMENTS_B, EVAL_LOG_B, EVAL_USAGE_B, EVAL_FAILURES_B, "B")
