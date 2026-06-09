"""
IntentFix RQ1 reproduction — patch generation (baselines: zero-shot + CoT).

Generates a fixed version of each vulnerable code snippet with a single Claude call,
using either the zero-shot or the CoT prompt. Output feeds evaluator.py.

Usage:
  export ANTHROPIC_API_KEY=your_key_here
  python3 main.py --condition zero_shot --n 200
  python3 main.py --condition cot       --n 200
"""
import os
import re
import json
import random
import argparse
from collections import defaultdict
from pathlib import Path

import anthropic

BASE_DIR     = Path(os.path.dirname(os.path.abspath(__file__)))
DATASET_FILE = BASE_DIR / "dataset" / "intentfix_pairs.jsonl"
PROMPT_FILES = {"zero_shot": "prompts/zero_shot.txt", "cot": "prompts/cot.txt"}

GEN_MODEL   = "claude-sonnet-4-6"
MAX_TOKENS  = 4096
TEMPERATURE = 0.0          # paper section 4.5: deterministic
SEED        = 42

api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found in environment.")
client = anthropic.Anthropic(api_key=api_key)


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def stratified_sample(records, n, seed=SEED):
    """Sample n records preserving the CWE distribution (paper's dataset is heavily skewed to CWE-770)."""
    if n is None or n >= len(records):
        return records
    groups = defaultdict(list)
    for r in records:
        groups[r.get("cwe", "Unknown")].append(r)
    random.seed(seed)
    total = len(records)
    sample = []
    for cwe in sorted(groups):
        grp = groups[cwe]
        k = max(1, round(n * len(grp) / total))
        sample.extend(random.sample(grp, min(k, len(grp))))
    random.shuffle(sample)
    return sample[:n] if len(sample) > n else sample


def render(template, rec):
    """Token replacement (NOT str.format -- buggy_code contains literal braces)."""
    return (template
            .replace("{{BUGGY_CODE}}", rec["buggy_code"])
            .replace("{{CWE}}", str(rec.get("cwe", "Unknown")))
            .replace("{{CVE}}", str(rec.get("cve", "Unknown"))))


def extract_code(text):
    if not text:
        return ""
    for pat in (r"```(?:[a-zA-Z0-9+#]*)\n?(.*?)```", r"```(.*?)```", r"`([^`]+)`"):
        m = re.search(pat, text, re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def main():
    ap = argparse.ArgumentParser(description="IntentFix RQ1 baseline patch generation (Claude).")
    ap.add_argument("--condition", required=True, choices=["zero_shot", "cot"])
    ap.add_argument("--n", type=int, default=200, help="stratified sample size (default 200; omit-large to run all)")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    template = (BASE_DIR / PROMPT_FILES[args.condition]).read_text(encoding="utf-8")
    records  = load_jsonl(DATASET_FILE)
    subset   = stratified_sample(records, args.n, args.seed)
    print(f"Loaded {len(records)} pairs; running {len(subset)} (condition={args.condition}, seed={args.seed}).")

    outputs_dir = BASE_DIR / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    output_path = outputs_dir / f"outputs_{args.condition}.jsonl"

    # resume from cache
    cache = {}
    if output_path.exists():
        for r in load_jsonl(output_path):
            cache[r["pair_id"]] = r
        print(f"Loaded {len(cache)} cached results from {output_path}.")

    results, in_tok, out_tok, cached = [], 0, 0, 0
    for i, rec in enumerate(subset):
        pid = rec["pair_id"]
        print(f"[{i+1}/{len(subset)}] {pid} ({rec.get('cwe')})", end=" ... ")
        if pid in cache:
            print("CACHED")
            results.append(cache[pid]); cached += 1; continue
        try:
            resp = client.messages.create(
                model=GEN_MODEL, max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
                messages=[{"role": "user", "content": render(template, rec)}],
            )
            raw = resp.content[0].text if resp.content else ""
            patch = extract_code(raw)
            in_tok += resp.usage.input_tokens
            out_tok += resp.usage.output_tokens
            print("OK" if patch else "NO_PATCH")
        except Exception as e:
            print(f"ERROR: {e}")
            raw, patch = "", ""
        results.append({
            "pair_id": pid, "cwe": rec.get("cwe", "Unknown"), "cve": rec.get("cve", "Unknown"),
            "buggy_code": rec["buggy_code"], "human_patch": rec["human_patch"],
            "generated_patch": patch, "raw_output": raw, "condition": args.condition,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(outputs_dir / f"tokens_{args.condition}.txt", "w") as f:
        f.write(f"condition       : {args.condition}\n")
        f.write(f"instances run   : {len(subset)} (stratified, seed={args.seed})\n")
        f.write(f"from cache      : {cached}\n")
        f.write(f"input tokens    : {in_tok}\n")
        f.write(f"output tokens   : {out_tok}\n")

    print(f"\nDone. {len(results)} results -> {output_path}")
    print(f"New calls: {len(subset)-cached}  input_tok: {in_tok}  output_tok: {out_tok}")


if __name__ == "__main__":
    main()
