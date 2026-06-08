"""
SEER — generation: run Prompt A and Prompt B on HumanEval + MBPP + LCB.
Stratified sampling: --n draws proportionally from all three datasets.
Usage: python main.py [--n N] [--seed S] [--workers W]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
Conda:  ensllm_env  (datasets)
"""

import argparse
import json
import random
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

MODEL    = "claude-sonnet-4-6"
HERE     = Path(__file__).parent
DATA_DIR = HERE / "data"

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def load_humaneval():
    data = json.loads((DATA_DIR / "humaneval.json").read_text())
    return [{"id": item["task_id"], "bench": "HumanEval", "question": item["question"]}
            for item in data]


def load_mbpp():
    data = json.loads((DATA_DIR / "mbpp.json").read_text())
    return [{"id": item["task_id"], "bench": "MBPP", "question": item["question"]}
            for item in data]


def load_lcb():
    data = json.loads((DATA_DIR / "full_problems.json").read_text())
    return [{"id": item["task_id"], "bench": "LCB", "question": item["question"],
             "public_test_cases": item.get("public_test_cases", "[]"),
             "starter": item.get("starter_code", "")}
            for item in data]


def stratified_sample(tasks, n, seed):
    by_bench = defaultdict(list)
    for p in tasks:
        by_bench[p["bench"]].append(p)
    total   = len(tasks)
    sampled = []
    rng     = random.Random(seed)
    for bench, items in by_bench.items():
        quota = max(1, round(n * len(items) / total))
        sampled.extend(rng.sample(items, min(quota, len(items))))
    rng.shuffle(sampled)
    sampled = sampled[:n]
    if len(sampled) < n:
        leftover = [p for p in tasks if p not in sampled]
        rng.shuffle(leftover)
        sampled.extend(leftover[:n - len(sampled)])
    return sampled


def load_done(path):
    if not path.exists():
        return set()
    return {(json.loads(l)["id"], json.loads(l)["bench"])
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


def extract_code(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("solution_code")
    except Exception:
        pass
    m = re.search(r'"solution_code"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    # Fallback: model returned prose + markdown code block instead of JSON
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    return None


def build_user(prob):
    if prob["bench"] == "LCB":
        note = ("\n\nIMPORTANT: This is a competitive programming problem. "
                "Write a complete Python script that reads from stdin and prints to stdout.")
        starter = f"\n\nStarter code:\n{prob['starter']}" if prob.get("starter") else ""
        return f"problem_description:\n{prob['question']}{note}{starter}"
    return f"problem_description:\n{prob['question']}"


def run_one(prob, variant, prompt, out_path, file_lock, counters, counter_lock, total):
    user = build_user(prob)
    raw, usage, elapsed = call_claude(prompt, user)
    code = extract_code(raw)
    record = json.dumps({
        "id":            prob["id"],
        "bench":         prob["bench"],
        "code":          code or "",
        "raw":           raw,
        "response_time": round(elapsed, 3),
    })
    with file_lock:
        with open(out_path, "a") as f:
            f.write(record + "\n")

    with counter_lock:
        counters["done"] += 1
        done = counters["done"]

    with _print_lock:
        print(f"[{done}/{total}] {prob['id']} ({prob['bench']})  "
              f"variant={variant}  t={elapsed:.2f}s")


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
    dataset = load_humaneval() + load_mbpp() + load_lcb()

    by_bench = defaultdict(int)
    for p in dataset:
        by_bench[p["bench"]] += 1
    print(f"Benchmarks: { {k: v for k, v in by_bench.items()} }")

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    candidate_probs = [
        p for p in dataset
        if (run_a and (p["id"], p["bench"]) not in done_a)
        or (run_b and (p["id"], p["bench"]) not in done_b)
    ]

    if args.n is not None:
        already = len(done_a | done_b)
        n_need  = max(0, args.n - already)
        candidate_probs = stratified_sample(
            candidate_probs, min(n_need, len(candidate_probs)), args.seed
        )

    lock_a = threading.Lock()
    lock_b = threading.Lock()

    all_tasks = []
    for p in candidate_probs:
        key = (p["id"], p["bench"])
        if run_a and key not in done_a:
            all_tasks.append((p, "A", prompt_a, out_a, lock_a))
        if run_b and key not in done_b:
            all_tasks.append((p, "B", prompt_b, out_b, lock_b))

    n_total = len(dataset)
    print(f"Model: {MODEL}  |  Dataset: {n_total}  |  Tasks to run: {len(all_tasks)}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}\n")

    counters     = {"done": 0}
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, p, v, pr, o, lk, counters, counter_lock, len(all_tasks))
            for p, v, pr, o, lk in all_tasks
        ]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                with _print_lock:
                    print(f"ERROR: {e}")

    n_ran = counters["done"]
    print(f"\n{'='*50}")
    print(f"Ran: {n_ran}")


if __name__ == "__main__":
    main()
