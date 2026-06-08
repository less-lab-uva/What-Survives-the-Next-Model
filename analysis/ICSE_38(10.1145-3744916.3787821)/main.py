"""
ADARULE — generation: run Prompt A and/or B against all 4 NL-to-LTL validation datasets.
Stratified sampling: --n draws proportionally across all 4 sub-datasets.

Datasets (valid splits from nl2ltl/FinalDataset/):
  final (100), calibration_AP (100), lang2ltl1 (100), nl2spec (18)  →  318 total

Usage:
  python main.py --n 1                   # Prompt B only, 1 random sample (smoke test)
  python main.py --variant A --n 1       # Prompt A only, 1 sample
  python main.py --variant both          # both prompts, all remaining samples
  python main.py --variant both --n 10   # both prompts, 10 stratified samples

Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
Conda:  adarule_env  (pandas, openpyxl)
"""

import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

import anthropic
import pandas as pd

MODEL    = "claude-sonnet-4-6"
HERE     = Path(__file__).parent
DATA_DIR = HERE / "data"

DATASETS = {
    "synthnl":  DATA_DIR / "valid_final_100.xlsx",
    "confonl":  DATA_DIR / "valid_calibration_AP_100.xlsx",
    "langnl":   DATA_DIR / "valid_lang2ltl1_100.xlsx",
    "specnl":   DATA_DIR / "valid_nl2spec_18.xlsx",
}


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def load_dataset():
    samples = []
    for ds_name, path in DATASETS.items():
        df = pd.read_excel(path)
        for i, (_, row) in enumerate(df.iterrows()):
            samples.append({
                "id":      f"{ds_name}_{i}",
                "dataset": ds_name,
                "nl":      str(row["en"]).strip(),
                "ltl":     str(row["ltl"]).strip(),
            })
    return samples


def stratified_sample(tasks, n, seed):
    by_ds   = defaultdict(list)
    for s in tasks:
        by_ds[s["dataset"]].append(s)
    total   = len(tasks)
    sampled = []
    rng     = random.Random(seed)
    for ds, items in by_ds.items():
        quota = max(1, round(n * len(items) / total))
        sampled.extend(rng.sample(items, min(quota, len(items))))
    rng.shuffle(sampled)
    sampled = sampled[:n]
    if len(sampled) < n:
        leftover = [s for s in tasks if s not in sampled]
        rng.shuffle(leftover)
        sampled.extend(leftover[:n - len(sampled)])
    return sampled


def load_done(path):
    if not path.exists():
        return set()
    return {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()}


def call_claude(system, user):
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text, resp.usage


def extract_ltl(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("ltl_formula")
    except Exception:
        pass
    m = re.search(r'"ltl_formula"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to run (default: both)")
    parser.add_argument("--n",    type=int, default=None,
                        help="max new samples; stratified across 4 datasets (default: all remaining)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    prompt_a, prompt_b = load_prompts()
    dataset = load_dataset()

    by_ds = defaultdict(int)
    for s in dataset:
        by_ds[s["dataset"]] += 1
    print(f"Datasets: { {k: v for k, v in by_ds.items()} }  total={len(dataset)}")

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    run_a = args.variant in ("A", "both")
    run_b = args.variant in ("B", "both")

    tasks = [s for s in dataset
             if (run_a and s["id"] not in done_a)
             or (run_b and s["id"] not in done_b)]

    if args.n is not None:
        already = len(done_a | done_b)
        n_need  = max(0, args.n - already)
        tasks   = stratified_sample(tasks, min(n_need, len(tasks)), args.seed)

    n_total = len(dataset)
    print(f"Model: {MODEL}  |  Variant: {args.variant}  |  To run: {len(tasks)}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}\n")

    with open(out_a, "a") as fa, open(out_b, "a") as fb:
        for i, sample in enumerate(tasks):
            user = f"nl_specification: {sample['nl']}"
            print(f"[{i+1}/{len(tasks)}] [{sample['dataset']}] {sample['nl'][:55]}", end="  ", flush=True)

            base = {"id": sample["id"], "dataset": sample["dataset"],
                    "nl": sample["nl"], "ground_truth": sample["ltl"]}

            if run_a and sample["id"] not in done_a:
                raw_a, usage_a = call_claude(prompt_a, user)
                pred_a = extract_ltl(raw_a)
                fa.write(json.dumps({**base, "prediction": pred_a}) + "\n")
                fa.flush()
                print(f"A={pred_a}", end="  ")
                time.sleep(0.2)

            if run_b and sample["id"] not in done_b:
                raw_b, usage_b = call_claude(prompt_b, user)
                pred_b = extract_ltl(raw_b)
                fb.write(json.dumps({**base, "prediction": pred_b}) + "\n")
                fb.flush()
                print(f"B={pred_b}", end="  ")
                time.sleep(0.2)

            print()

    n_ran = len(tasks)
    print(f"\n{'='*50}")
    print(f"Ran: {n_ran}")


if __name__ == "__main__":
    main()
