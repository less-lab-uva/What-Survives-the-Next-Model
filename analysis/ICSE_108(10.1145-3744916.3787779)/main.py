"""
GuideSyn — generation: run Prompt A and Prompt B against .mls benchmark files.
Usage: python main.py [--n N] [--seed S] [--workers W] [--variant {A,B,both}]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
"""

import argparse
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

MODEL               = "claude-sonnet-4-6"
INPUT_COST_PER_TOK  = 3e-6
OUTPUT_COST_PER_TOK = 15e-6
HERE                = Path(__file__).parent
BENCH               = HERE / "data"

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def load_done(path):
    if not path.exists():
        return set()
    return {json.loads(l)["prob"] for l in path.read_text().splitlines() if l.strip()}


def call_claude(system, user):
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=MODEL, max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    elapsed = time.perf_counter() - t0
    return resp.content[0].text, resp.usage, elapsed


def sample_cost(usage):
    return usage.input_tokens * INPUT_COST_PER_TOK + usage.output_tokens * OUTPUT_COST_PER_TOK


def extract_function(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("synthesized_function")
    except Exception:
        pass
    m = re.search(r'"synthesized_function"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    return None


def run_one(mls_path, variant, prompt, out_path, file_lock, counters, counter_lock, total):
    prob = mls_path.stem
    spec = mls_path.read_text()
    user = f"specification: {spec}"
    raw, usage, elapsed = call_claude(prompt, user)
    func = extract_function(raw)

    record = json.dumps({
        "prob": prob,
        "raw_output": raw,
        "synthesized_function": func or "",
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
        print(f"[{done}/{total}] {prob}  variant={variant}  "
              f"func={'ok' if func else 'NONE'}  t={elapsed:.2f}s  cost=${total_cost:.4f}")


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
    benchmarks = sorted(BENCH.glob("*.mls"))
    n_total    = len(benchmarks)

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    print(f"Model: {MODEL}  |  Dataset: {n_total}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}")

    # Build candidate list
    candidates = [b for b in benchmarks
                  if (run_a and b.stem not in done_a) or (run_b and b.stem not in done_b)]

    if args.n is not None:
        if args.variant == "B" and done_a:
            # B must run on exactly the same problems as A
            candidates = [b for b in benchmarks if b.stem in done_a]
        elif args.variant == "both" and done_a:
            a_stems = done_a
            b_stems = done_b
            if a_stems - b_stems:
                # B is behind A — catch up to A's existing problems
                candidates = [b for b in benchmarks if b.stem in a_stems]
            else:
                # A and B in sync — sample new problems
                done_stems = a_stems
                already    = len(done_stems)
                n_need     = max(0, args.n - already)
                pool       = [b for b in candidates if b.stem not in done_stems]
                random.seed(args.seed)
                candidates = random.sample(pool, min(n_need, len(pool)))
        else:
            # A variant or fresh both
            done_stems = done_a
            already    = len(done_stems)
            n_need     = max(0, args.n - already)
            pool       = [b for b in candidates if b.stem not in done_stems]
            random.seed(args.seed)
            candidates = random.sample(pool, min(n_need, len(pool)))

    # Build task list
    lock_a = threading.Lock()
    lock_b = threading.Lock()
    all_tasks = []
    for b in candidates:
        if run_a and b.stem not in done_a:
            all_tasks.append((b, "A", prompt_a, out_a, lock_a))
        if run_b and b.stem not in done_b:
            all_tasks.append((b, "B", prompt_b, out_b, lock_b))

    print(f"Tasks to run: {len(all_tasks)}\n")

    counters     = {"in": 0, "out": 0, "cost": 0.0, "done": 0}
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, b, v, pr, o, lk, counters, counter_lock, len(all_tasks))
            for b, v, pr, o, lk in all_tasks
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
        print(f"Avg/task (Prompt {prompts_run}): ${avg:.4f}")
        print(f"Projected full run ({n_total} samples, Prompt {prompts_run}): ${avg * n_total:.2f}")
        if args.variant != "both":
            print(f"Projected full run ({n_total} samples, both A+B):  ${avg * n_total * 2:.2f}")


if __name__ == "__main__":
    main()
