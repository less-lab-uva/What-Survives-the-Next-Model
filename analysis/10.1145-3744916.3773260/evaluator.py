"""
IntentFix RQ1 reproduction — AI-oracle patch-correctness evaluation.

Mirrors the paper's AI-based oracle (section 4.4.1): for each case the oracle is given the
vulnerable code, the generated patch, the ground-truth fix, and the CWE, and judges correctness
on two criteria — (1) does it fix the vulnerability, (2) does it preserve functionality without
introducing new bugs. Metric: patch accuracy (fraction judged correct).

NOTE: the original artifact's evaluator read result["inputs"][...], a key that is never populated,
so its oracle saw an EMPTY ground-truth fix and no CWE. This reproduction passes all four inputs.

Usage:
  export ANTHROPIC_API_KEY=your_key_here
  python3 evaluator.py --condition zero_shot
  python3 evaluator.py --condition cot
"""
import os
import re
import json
import argparse
from collections import defaultdict
from pathlib import Path

import anthropic

BASE_DIR    = Path(os.path.dirname(os.path.abspath(__file__)))
JUDGE_MODEL = "claude-sonnet-4-6"   # Claude judging Claude => self-eval bias; paper used OpenAI o4-mini
MAX_TOKENS  = 1024
TEMPERATURE = 0.0

api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found in environment.")
client = anthropic.Anthropic(api_key=api_key)

JUDGE_INSTRUCTIONS = (
    "Judge correctness on TWO criteria:\n"
    "1. Does the patch fix the specified vulnerability?\n"
    "2. Does it preserve the original functionality and introduce no new bugs?\n\n"
    "A patch is correct only if BOTH hold. The ground-truth fix is a reference for the intended\n"
    "behavior; a patch need not be textually identical, only semantically correct.\n\n"
    'Respond with ONLY a JSON object: {"is_correct": true or false, "reasoning": "<one paragraph>"}'
)


def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def build_judge_prompt(rec):
    return (
        "You are an expert security oracle evaluating whether a generated patch correctly "
        "fixes a vulnerability.\n\n"
        "CWE: " + str(rec.get("cwe", "Unknown")) + " (" + str(rec.get("cve", "Unknown")) + ")\n\n"
        "Vulnerable code:\n" + rec.get("buggy_code", "") + "\n\n"
        "Ground-truth fix (reference):\n" + rec.get("human_patch", "") + "\n\n"
        "Generated patch (candidate):\n" + (rec.get("generated_patch") or "") + "\n\n"
        + JUDGE_INSTRUCTIONS
    )


def parse_verdict(text):
    if not text:
        return {"is_correct": False, "reasoning": "empty oracle response", "parse_ok": False}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else None
    if blob is None:
        s, e = text.find("{"), text.rfind("}")
        blob = text[s:e + 1] if (s != -1 and e > s) else None
    if blob:
        try:
            d = json.loads(blob)
            return {"is_correct": bool(d.get("is_correct", False)),
                    "reasoning": str(d.get("reasoning", "")), "parse_ok": True}
        except json.JSONDecodeError:
            pass
    m = re.search(r'"?is_correct"?\s*[:=]\s*(true|false)', text, re.IGNORECASE)
    if m:
        return {"is_correct": m.group(1).lower() == "true", "reasoning": text.strip()[:500], "parse_ok": True}
    return {"is_correct": False, "reasoning": text.strip()[:500], "parse_ok": False}


def judge(rec):
    if not (rec.get("generated_patch") or "").strip():
        return {"is_correct": False, "reasoning": "no generated patch", "parse_ok": True}
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
            messages=[{"role": "user", "content": build_judge_prompt(rec)}],
        )
        return parse_verdict(resp.content[0].text if resp.content else "")
    except Exception as e:
        return {"is_correct": False, "reasoning": f"oracle error: {e}", "parse_ok": False}


def main():
    ap = argparse.ArgumentParser(description="IntentFix RQ1 AI-oracle evaluation (Claude).")
    ap.add_argument("--condition", required=True, choices=["zero_shot", "cot"])
    args = ap.parse_args()

    inputs_path = BASE_DIR / "outputs" / f"outputs_{args.condition}.jsonl"
    if not inputs_path.exists():
        raise FileNotFoundError(f"{inputs_path} not found — run main.py --condition {args.condition} first.")
    records = load_jsonl(inputs_path)
    print(f"Loaded {len(records)} generated patches; judging with {JUDGE_MODEL} ...\n")

    per_instance = []
    by_cwe = defaultdict(lambda: {"correct": 0, "total": 0})
    correct = 0
    for i, rec in enumerate(records):
        v = judge(rec)
        ok = bool(v["is_correct"])
        correct += ok
        by_cwe[rec.get("cwe", "Unknown")]["total"] += 1
        by_cwe[rec.get("cwe", "Unknown")]["correct"] += ok
        print(f"[{i+1}/{len(records)}] {rec['pair_id']} ({rec.get('cwe')}) -> {'CORRECT' if ok else 'INCORRECT'}")
        per_instance.append({
            "pair_id": rec["pair_id"], "cwe": rec.get("cwe", "Unknown"), "cve": rec.get("cve", "Unknown"),
            "is_correct": ok, "reasoning": v["reasoning"], "judge_parse_ok": v["parse_ok"],
        })

    total = len(records)
    accuracy = correct / total if total else 0.0
    aggregate = {"aggregate": {
        "condition": args.condition, "accuracy": round(accuracy, 4),
        "correct": correct, "total": total,
        "by_cwe": {k: {"correct": v["correct"], "total": v["total"],
                       "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0.0}
                   for k, v in sorted(by_cwe.items())},
    }}

    results_dir = BASE_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    out_path = results_dir / f"results_{args.condition}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(aggregate, ensure_ascii=False) + "\n")
        for r in per_instance:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n{'='*56}")
    print(f"condition : {args.condition}")
    print(f"accuracy  : {accuracy:.4f}  ({correct}/{total})")
    print("by CWE:")
    for cwe, v in sorted(by_cwe.items()):
        acc = v["correct"] / v["total"] if v["total"] else 0.0
        print(f"  {cwe:<10} {v['correct']:>3}/{v['total']:<3}  {acc*100:5.1f}%")
    print(f"{'='*56}\nResults -> {out_path}")


if __name__ == "__main__":
    main()
