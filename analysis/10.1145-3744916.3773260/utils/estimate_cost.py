"""Project the FULL-run token usage + cost for IntentFix -- NO SPEND.

Counts INPUT tokens EXACTLY with Anthropic's free count_tokens for every call a full run makes,
using the SAME messages main.py / evaluator.py build:
  - generation prompt A   (one call per pair)   -> main.py
  - generation prompt B   (one call per pair)   -> main.py
  - evaluation / AI oracle (one call per prediction = A's + B's predictions) -> evaluator.py

The judge sees the GENERATED patch, which doesn't exist before a run, so we proxy it with the
human_patch (comparable size). Output has no count_tokens mode, so each phase uses a fixed per-call
output budget calibrated from the smoke run (generation ~2300 tok/call, evaluation ~250).

Writes logs/cost_estimate.json.  Just run it:  python3 utils/estimate_cost.py
"""

import os
import sys
import json
import anthropic

# Hardcoded so the script can be run from anywhere.
ANALYSIS_DIR = "/opt/devel/repos/ephemeral_se/submission/Ephemeral-SE/analysis/10.1145-3744916.3773260"
os.chdir(ANALYSIS_DIR)

MODEL = "claude-sonnet-4-6"
PRICE_IN_PER_M = 3.0          # $/1M input tokens
PRICE_OUT_PER_M = 15.0        # $/1M output tokens
GEN_OUT_TOKENS = 2300         # avg generation output/call (corrected file + reasoning), from the smoke run
EVAL_OUT_TOKENS = 250         # avg judge-verdict output/call, from the smoke run

DATASET = "dataset/intentfix_pairs.jsonl"
HELDOUT = "dataset/heldout_fewshot_ids.json"
PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"
ESTIMATE = "logs/cost_estimate.json"

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set (count_tokens needs a client; it is free, no spend).")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
os.makedirs("logs", exist_ok=True)


def count(content: str) -> int:
    return client.messages.count_tokens(
        model=MODEL, messages=[{"role": "user", "content": content}]).input_tokens


def gen_message(prompt: str, pair: dict) -> str:
    """The exact message main.py sends for one generation call."""
    record = {"buggy_code": pair.get("buggy_code") or "",
              "vulnerability_description": pair.get("vulnerability_description") or ""}
    return prompt + "\n\n" + json.dumps({"inputs": record}, indent=2)


def judge_message(pair: dict) -> str:
    """The exact judge prompt evaluator.py sends, with the generated patch proxied by human_patch."""
    cwe = pair.get("cwe", "Unknown")
    vulnerability_info = (f"{cwe}: {pair.get('vulnerability_description', '')}\n\n"
                          f"Vulnerable code:\n{pair.get('buggy_code', '')}")
    human_patch = pair.get("human_patch", "")
    generated_patch = human_patch   # real patch not available pre-run -> proxy with the human patch
    return (
        "You are an expert security researcher and code reviewer. Your task is to evaluate "
        "whether a generated patch correctly fixes a security vulnerability.\n\n"
        "Context:\n"
        "- Vulnerability Information: " + vulnerability_info + "\n"
        "- Human Patch (Ground Truth): " + human_patch + "\n"
        "- Generated Patch (Candidate): " + generated_patch + "\n\n"
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


# Pairs to run = the dataset minus the held-out few-shot examples (same as main.py).
heldout = set(json.load(open(HELDOUT, encoding="utf-8"))["heldout_pair_ids"])
pairs = [json.loads(l) for l in open(DATASET, encoding="utf-8") if l.strip()]
pairs = [p for p in pairs if p["pair_id"] not in heldout]
N = len(pairs)
prompt_a = open(PROMPT_A, encoding="utf-8").read()
prompt_b = open(PROMPT_B, encoding="utf-8").read()

print(f"Counting input tokens over {N} pairs (3 count_tokens calls each) ...")
gen_a_in = gen_b_in = judge_in = 0
for i, pair in enumerate(pairs, 1):
    gen_a_in += count(gen_message(prompt_a, pair))
    gen_b_in += count(gen_message(prompt_b, pair))
    judge_in += count(judge_message(pair))           # same estimate for A's and B's predictions
    if i % 100 == 0:
        print(f"  {i}/{N}")


def cost(in_tok, out_tok):
    return (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6


# generation = prompt A + prompt B, one call per pair each (2N calls)
gen_in = gen_a_in + gen_b_in
gen_out = 2 * N * GEN_OUT_TOKENS
# evaluation = one judge call per prediction = A's predictions + B's predictions (2N calls)
eval_in = 2 * judge_in
eval_out = 2 * N * EVAL_OUT_TOKENS

generation = {"calls": 2 * N, "input_tokens": gen_in, "output_tokens": gen_out,
              "cost_usd": round(cost(gen_in, gen_out), 2)}
evaluation = {"calls": 2 * N, "input_tokens": eval_in, "output_tokens": eval_out,
              "cost_usd": round(cost(eval_in, eval_out), 2)}
grand = {"calls": generation["calls"] + evaluation["calls"],
         "input_tokens": gen_in + eval_in, "output_tokens": gen_out + eval_out,
         "cost_usd": round(generation["cost_usd"] + evaluation["cost_usd"], 2)}

estimate = {
    "model": MODEL, "pairs": N,
    "price_in_per_mtok": PRICE_IN_PER_M, "price_out_per_mtok": PRICE_OUT_PER_M,
    "input_tokens": "EXACT via free count_tokens (same messages main.py / evaluator.py send)",
    "output_tokens": (f"per-call budgets from the smoke run: generation {GEN_OUT_TOKENS}, "
                      f"evaluation {EVAL_OUT_TOKENS}; judge's generated patch proxied by human_patch"),
    "generation": generation,
    "evaluation": evaluation,
    "grand_total": grand,
}
with open(ESTIMATE, "w", encoding="utf-8") as f:
    json.dump(estimate, f, indent=2)

print(f"\nSaved {ESTIMATE}")
print(f"  generation: {generation['calls']} calls, in={gen_in:,} out~{gen_out:,} tok  =  ${generation['cost_usd']}")
print(f"  evaluation: {evaluation['calls']} calls, in={eval_in:,} out~{eval_out:,} tok  =  ${evaluation['cost_usd']}")
print(f"  GRAND TOTAL ({N} pairs, full run): ${grand['cost_usd']}")
