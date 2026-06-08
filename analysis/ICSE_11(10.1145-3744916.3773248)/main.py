"""
LogPipe — generation: run Prompt A and Prompt B against log anomaly datasets.
Stratified sampling: --n draws proportionally across all 8 sub-datasets.
Usage: python main.py [--n N] [--seed S] [--workers W] [--variant {A,B,both}]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
"""

import argparse
import csv
import json
import random
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

csv.field_size_limit(sys.maxsize)

MODEL               = "claude-sonnet-4-6"
INPUT_COST_PER_TOK  = 3e-6
OUTPUT_COST_PER_TOK = 15e-6
HERE                = Path(__file__).parent
DATA                = HERE / "data"

DATASETS = {
    "BGL":         (DATA / "BGL/100l_BGL.csv",                 "success_fail"),
    "Spirit":      (DATA / "Spirit/100l_Spirit.csv",           "success_fail"),
    "Thunderbird": (DATA / "Thunderbird/200l_Thunderbird.csv", "success_fail"),
    "HDFS":        (DATA / "HDFS/HDFS.csv",                    "Success_Fail"),
    "Hadoop2":     (DATA / "hadoop2/hadoop2.csv",              "1_0"),
    "Hadoop3":     (DATA / "hadoop3/hadoop3.csv",              "1_0"),
    "Spark2":      (DATA / "spark/spark2.csv",                 "1_0"),
    "Spark3":      (DATA / "spark3/spark3.csv",                "1_0"),
}

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def normalize_status(val, convention):
    v = val.strip()
    if convention == "success_fail":  return 1 if v == "success" else 0
    if convention == "Success_Fail":  return 1 if v == "Success" else 0
    if convention == "1_0":           return 0 if int(v) == 1 else 1
    raise ValueError(f"Unknown convention: {convention}")


def load_dataset():
    samples = []
    for name, (path, convention) in DATASETS.items():
        with open(path, newline="", encoding="utf-8") as f:
            all_rows = list(csv.DictReader(f))
        for row in all_rows[int(len(all_rows) * 0.8):]:
            samples.append({
                "dataset":     name,
                "block_id":    row.get("BlockID", ""),
                "log_content": row["Content"],
                "event_list":  row["EventList"],
                "label":       normalize_status(row["Status"], convention),
            })
    return samples


def stratified_sample(tasks, n, seed):
    by_ds = defaultdict(list)
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
    return {(json.loads(l)["dataset"], json.loads(l)["block_id"])
            for l in path.read_text().splitlines() if l.strip()}


def call_claude(system, user):
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=MODEL, max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    elapsed = time.perf_counter() - t0
    return resp.content[0].text, resp.usage, elapsed


def sample_cost(usage):
    return usage.input_tokens * INPUT_COST_PER_TOK + usage.output_tokens * OUTPUT_COST_PER_TOK


def parse_status(raw):
    json_blocks = re.findall(r'\{[^{}]*"status"[^{}]*\}', raw, re.DOTALL)
    if json_blocks:
        for block in reversed(json_blocks):
            try:
                val = json.loads(block).get("status", "").lower().strip(); break
            except Exception:
                continue
        else:
            val = ""
    else:
        m = re.search(r'"status"\s*:\s*"([^"]+)"', raw)
        val = m.group(1).lower().strip() if m else ""
    if val in ("success",):                               return 1
    if val in ("fail", "failure", "anomaly", "abnormal"): return 0
    return None


def run_one(s, variant, prompt, out_path, file_lock, counters, counter_lock, total):
    user = f"log_content: {s['log_content']}\nevent_list: {s['event_list']}"
    raw, usage, elapsed = call_claude(prompt, user)
    pred = parse_status(raw)

    record = json.dumps({
        "dataset":  s["dataset"],
        "block_id": s["block_id"],
        "label":    s["label"],
        "pred":     pred,
        "raw_output": raw,
        "response_time": round(elapsed, 3),
    })
    with file_lock:
        with open(out_path, "a") as f:
            f.write(record + "\n")

    cost = sample_cost(usage)
    with counter_lock:
        counters["in"]   += usage.input_tokens
        counters["out"]  += usage.output_tokens
        counters["cost"] += cost
        counters["done"] += 1
        done       = counters["done"]
        total_cost = counters["cost"]

    with _print_lock:
        print(f"[{done}/{total}] {s['dataset']} {s['block_id'][:8]}  "
              f"variant={variant}  pred={pred}  t={elapsed:.2f}s  cost=${total_cost:.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to run (default: both)")
    parser.add_argument("--n",       type=int, default=None)
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel threads (default: 4)")
    args = parser.parse_args()
    run_a = args.variant in ("A", "both")
    run_b = args.variant in ("B", "both")

    prompt_a, prompt_b = load_prompts()
    dataset = load_dataset()

    by_ds = defaultdict(int)
    for s in dataset:
        by_ds[s["dataset"]] += 1
    n_total = len(dataset)
    print(f"Sub-datasets: { {k: v for k, v in by_ds.items()} }  total={n_total}")

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    candidate = [s for s in dataset
                 if (run_a and (s["dataset"], s["block_id"]) not in done_a)
                 or (run_b and (s["dataset"], s["block_id"]) not in done_b)]

    if args.n is not None:
        if args.variant == "A":
            already = len(done_a)
        elif args.variant == "B":
            already = len(done_b)
        else:
            already = len(done_a & done_b)
        n_need    = max(0, args.n - already)
        done_keys = done_a if args.variant == "A" else (done_b if args.variant == "B" else done_a & done_b)
        candidate = stratified_sample(
            [s for s in candidate if (s["dataset"], s["block_id"]) not in done_keys],
            min(n_need, len(candidate)), args.seed
        )

    lock_a = threading.Lock()
    lock_b = threading.Lock()

    all_tasks = []
    for s in candidate:
        key = (s["dataset"], s["block_id"])
        if run_a and key not in done_a:
            all_tasks.append((s, "A", prompt_a, out_a, lock_a))
        if run_b and key not in done_b:
            all_tasks.append((s, "B", prompt_b, out_b, lock_b))

    print(f"Model: {MODEL}  |  Tasks to run: {len(all_tasks)}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}\n")

    counters     = {"in": 0, "out": 0, "cost": 0.0, "done": 0}
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, s, v, pr, o, lk, counters, counter_lock, len(all_tasks))
            for s, v, pr, o, lk in all_tasks
        ]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                with _print_lock:
                    print(f"ERROR: {e}")

    n_ran      = counters["done"]
    total_cost = counters["cost"]
    print(f"\n{'='*50}")
    print(f"Ran: {n_ran}  |  Tokens in: {counters['in']}  out: {counters['out']}")
    print(f"Session cost: ${total_cost:.4f}")
    if n_ran > 0:
        avg = total_cost / n_ran
        prompts_run = "A+B" if args.variant == "both" else args.variant
        print(f"Avg/sample (Prompt {prompts_run}): ${avg:.4f}")
        print(f"Projected full run ({n_total} samples, Prompt {prompts_run}): ${avg * n_total:.2f}")
        if args.variant != "both":
            print(f"Projected full run ({n_total} samples, both A+B):  ${avg * n_total * 2:.2f}")


if __name__ == "__main__":
    main()
