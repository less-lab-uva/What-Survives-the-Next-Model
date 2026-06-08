"""
AdapTrack — generation: run Prompt A and Prompt B.
Datasets (stratified):
  tfv1_real     (1000) — real-world TF API completions from GitHub
  tfv1_synthetic ( 419) — template-generated TF API completions

Usage: python main.py [--n N] [--seed S] [--variant {A,B,both}] [--workers W]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
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

MODEL         = "claude-sonnet-4-6"
HERE          = Path(__file__).parent
DATA_DIR      = HERE / "data"
REAL_FILE     = DATA_DIR / "tfv1-real.jsonl"
FUNC_FILE     = DATA_DIR / "tfv1-function.json"
TEMPLATE_FILE = DATA_DIR / "tfv1-template.py"

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def load_dataset(split="both"):
    samples = []

    if split in ("real", "both"):
        with open(REAL_FILE) as f:
            for i, line in enumerate(f):
                d = json.loads(line)
                samples.append({
                    "id":           f"real_{i}",
                    "dataset":      "tfv1_real",
                    "prefix":       d["prefix"],
                    "ground_truth": d["oracle"],
                })

    if split in ("synth", "both"):
        template   = TEMPLATE_FILE.read_text()
        func_names = json.loads(FUNC_FILE.read_text())
        for i, func in enumerate(func_names):
            parts      = func.split(".")
            short_name = parts[-1]
            long_name  = func[len("compat.v1."):] if func.startswith("compat.v1.") else func
            prefix     = template.replace("{short_name}", short_name).replace("{long_name}", long_name)
            prefix     = prefix.rstrip()
            samples.append({
                "id":           f"synth_{i}",
                "dataset":      "tfv1_synthetic",
                "prefix":       prefix,
                "ground_truth": f".{func}",
            })

    return samples


def load_done(path):
    if not path.exists():
        return set()
    return {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()}


def call_claude(system, user):
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=MODEL, max_tokens=256,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    elapsed = time.perf_counter() - t0
    return resp.content[0].text, resp.usage, elapsed


def extract_api_name(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("api_name")
    except Exception:
        pass
    m = re.search(r'"api_name"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    stripped = raw.strip()
    if re.match(r'^\.[a-zA-Z0-9_.]+$', stripped):
        return stripped
    return None


def run_one(sample, variant, prompt, out_path, file_lock, counters, counter_lock, total, setting=None):
    version_hint = ""
    if setting == "v1":
        version_hint = "tensorflow_version: 1.x\n"
    elif setting == "v2":
        version_hint = "tensorflow_version: 2.x\n"
    user = f"{version_hint}prefix:\n{sample['prefix']}"
    raw, usage, elapsed = call_claude(prompt, user)
    pred = extract_api_name(raw)

    record = json.dumps({
        "id":           sample["id"],
        "dataset":      sample["dataset"],
        "ground_truth": sample["ground_truth"],
        "prediction":   pred,
        "raw":          raw,
        "response_time": round(elapsed, 3),
        "setting":      setting,
    })
    with file_lock:
        with open(out_path, "a") as f:
            f.write(record + "\n")

    with counter_lock:
        counters["done"] += 1
        done = counters["done"]

    with _print_lock:
        print(f"[{done}/{total}] {sample['id']} ({sample['dataset']})  "
              f"variant={variant}  pred={pred!r}  t={elapsed:.2f}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both")
    parser.add_argument("--setting", choices=["v1", "v2", "both"], default="both",
                        help="tensorflow version hint injected into prompt (default: both)")
    parser.add_argument("--n",       type=int, default=None)
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run_a = args.variant in ("A", "both")
    run_b = args.variant in ("B", "both")

    prompt_a, prompt_b = load_prompts()
    dataset = load_dataset("synth")

    by_ds = defaultdict(int)
    for s in dataset:
        by_ds[s["dataset"]] += 1
    n_total = len(dataset)
    print(f"Model: {MODEL}  |  Datasets: { {k: v for k, v in by_ds.items()} }  total={n_total}")

    settings = ["v1", "v2"] if args.setting == "both" else [args.setting]

    for setting in settings:
        sfx   = f"_{setting}"
        out_a = HERE / "outputs" / f"outputs_A{sfx}.jsonl"
        out_b = HERE / "outputs" / f"outputs_B{sfx}.jsonl"
        out_a.parent.mkdir(exist_ok=True)

        done_a = load_done(out_a)
        done_b = load_done(out_b)

        tasks = [s for s in dataset
                 if (run_a and s["id"] not in done_a) or (run_b and s["id"] not in done_b)]

        if args.n is not None:
            already = len(done_a | done_b)
            n_need  = max(0, args.n - already)
            by_ds_tasks = defaultdict(list)
            for s in tasks:
                by_ds_tasks[s["dataset"]].append(s)
            total   = len(tasks)
            sampled = []
            rng     = random.Random(args.seed)
            for ds, items in by_ds_tasks.items():
                quota = max(1, round(n_need * len(items) / total))
                sampled.extend(rng.sample(items, min(quota, len(items))))
            rng.shuffle(sampled)
            sampled = sampled[:n_need]
            if len(sampled) < n_need:
                sampled_ids = {s["id"] for s in sampled}
                leftover    = [s for s in tasks if s["id"] not in sampled_ids]
                rng.shuffle(leftover)
                sampled.extend(leftover[:n_need - len(sampled)])
            tasks = sampled

        lock_a = threading.Lock()
        lock_b = threading.Lock()

        all_tasks = []
        for s in tasks:
            if run_a and s["id"] not in done_a:
                all_tasks.append((s, "A", prompt_a, out_a, lock_a))
            if run_b and s["id"] not in done_b:
                all_tasks.append((s, "B", prompt_b, out_b, lock_b))

        print(f"\n--- Setting: {setting} ---")
        print(f"Already done — A: {len(done_a)}  B: {len(done_b)}  |  Tasks to run: {len(all_tasks)}\n")

        counters     = {"done": 0}
        counter_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(run_one, s, v, pr, o, lk, counters, counter_lock, len(all_tasks), setting)
                for s, v, pr, o, lk in all_tasks
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
