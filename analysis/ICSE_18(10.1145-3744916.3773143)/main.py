

import argparse
import base64
import json
import pickle
import random
import re
import threading
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

HERE                = Path(__file__).parent
MODEL               = "claude-sonnet-4-6"
HE_SAMPLES          = 164
LCB_SAMPLES         = 511
CACHE_DIR           = str(HERE / "data" / "hf_cache")
LCB_DIR             = str(HERE / "data" / "lcb")

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def load_humaneval():
    from datasets import load_dataset
    ds = load_dataset("openai/openai_humaneval", split="test", cache_dir=CACHE_DIR)
    return [{"id": ds[i]["task_id"], "bench": "HumanEval", "prompt": ds[i]["prompt"],
              "entry_point": ds[i]["entry_point"], "test": ds[i]["test"]}
            for i in range(HE_SAMPLES)]


def _decode_private(raw):
    try:
        return json.loads(pickle.loads(zlib.decompress(base64.b64decode(raw))))
    except Exception:
        return []


def load_lcb():
    rows = []
    for fname in ["test.jsonl", "test2.jsonl"]:
        rows += [json.loads(l) for l in open(f"{LCB_DIR}/{fname}")]
    rows = rows[:LCB_SAMPLES]
    out = []
    for r in rows:
        pub  = json.loads(r["public_test_cases"]) if isinstance(r["public_test_cases"], str) else r["public_test_cases"]
        priv = _decode_private(r.get("private_test_cases", ""))
        out.append({"id": r["question_id"], "bench": "LiveCodeBench",
                    "description": r["question_content"], "starter": r.get("starter_code", ""),
                    "tests": pub + priv})
    return out


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
        return json.loads(text).get("selected_program_code")
    except Exception:
        pass
    m = re.search(r'"selected_program_code"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    # Fallback: model returned a plain markdown code block instead of JSON
    m = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def build_user(prob):
    if prob["bench"] == "HumanEval":
        return f"problem_description:\n{prob['prompt']}"
    note = ("\n\nIMPORTANT: This is a competitive programming problem. "
            "Write a complete Python script that reads from stdin and prints to stdout.")
    starter = f"\n\nStarter code:\n{prob['starter']}" if prob.get("starter") else ""
    return f"problem_description:\n{prob['description']}{note}{starter}"


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
    print("Loading datasets...")
    dataset = load_humaneval() + load_lcb()

    by_bench = defaultdict(int)
    for p in dataset:
        by_bench[p["bench"]] += 1
    print(f"Benchmarks: { {k: v for k, v in by_bench.items()} }")

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    # Problems that still need at least one variant run
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
