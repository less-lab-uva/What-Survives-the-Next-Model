"""
ARTEMIS — generation: run Prompt A and Prompt B against FRETish benchmarks.
Stratified sampling: --n draws proportionally across all 6 sub-datasets.
Usage: python main.py [--n N] [--seed S] [--workers W] [--variant {A,B,both}]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
Conda:  artemis_env  (spot, pandas, openpyxl, tqdm, pydantic, openai, google-genai)
"""

import argparse
import io
import json
import os
import random
import re
import sys
import threading
import time
import types
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
import pandas as pd

MODEL               = "claude-sonnet-4-6"
INPUT_COST_PER_TOK  = 3e-6
OUTPUT_COST_PER_TOK = 15e-6
HERE                = Path(__file__).parent

_dummy = types.ModuleType("llm_prompt")
sys.modules["llm_prompt"] = _dummy
os.environ.setdefault("DATA_HOME_DIR", str(HERE / "data" / "metadata"))
os.environ.setdefault("STRUCTNL_MODE", "fretish")
_old = sys.stdout; sys.stdout = io.StringIO()
sys.path.insert(0, str(HERE / "lib"))
import nl2structnl_fretish
from data_loader import get_all_outputs_for_df_row, get_ap_dict
sys.stdout = _old

import spot

FRET_DIR = HERE / "data" / "fret_specs"
DATASETS = {
    "deepstl-test": False, "FSM-AP": True, "FSM-S": True,
    "REG": True, "RobotExplain": False, "Ventilator": False,
}

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


def _safe_ltl(s):
    try:
        return s if spot.formula(s) is not None else None
    except Exception:
        return None


def _generate_labels(df_row):
    try:
        outputs = get_all_outputs_for_df_row(df_row, max_N_DURATION=5, structnl="fretish")
    except Exception:
        return []
    labels = []
    for out in outputs:
        try:
            ltl = nl2structnl_fretish.get_ltl_from_output(out)
            if _safe_ltl(ltl):
                labels.append(ltl)
        except Exception:
            pass
    return labels


def load_dataset():
    probs = []
    for ds_name, has_vars in DATASETS.items():
        specs_path = FRET_DIR / ds_name / "PlausibleSpecs.xlsx"
        df = pd.read_excel(specs_path, engine="openpyxl")
        global_ap = get_ap_dict(pd.read_excel(FRET_DIR / ds_name / "Variables.xlsx",
                                               engine="openpyxl")) if has_vars else None
        for row_idx in range(len(df)):
            row = df.iloc[row_idx]
            nl = row.get("NL", None)
            if nl is None or (isinstance(nl, float) and pd.isna(nl)):
                continue
            ap = global_ap if global_ap is not None else (
                json.loads(row.get("ap_dict", "{}"))
                if not isinstance(row.get("ap_dict"), float) else None
            )
            if ap is None:
                continue
            labels = _generate_labels(row)
            if not labels:
                continue
            probs.append({
                "id": f"{ds_name}-{row_idx}", "dataset": ds_name,
                "row_idx": row_idx, "nl": nl, "ap_dict": ap, "labels": labels,
            })
    return probs


def stratified_sample(tasks, n, seed):
    by_ds = defaultdict(list)
    for p in tasks:
        by_ds[p["dataset"]].append(p)
    total   = len(tasks)
    sampled = []
    rng     = random.Random(seed)
    for ds, items in by_ds.items():
        quota = max(1, round(n * len(items) / total))
        sampled.extend(rng.sample(items, min(quota, len(items))))
    rng.shuffle(sampled)
    sampled = sampled[:n]
    if len(sampled) < n:
        leftover = [p for p in tasks if p not in sampled]
        rng.shuffle(leftover)
        sampled.extend(leftover[:n - len(sampled)])
    return sampled


K = 10  # candidates per requirement (paper uses k=10)


def load_done(path):
    if not path.exists():
        return set()
    done = set()
    for l in path.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        done.add((r["id"], r.get("run_idx", 0)))
    return done


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


def extract_ltl(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("output_LTL")
    except Exception:
        pass
    m = re.search(r'"output_LTL"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    return m.group(1) if m else None


def run_one(prob, run_idx, variant, prompt, out_path, file_lock, counters, counter_lock, total):
    user = (f"input_natural_language: {prob['nl']}\n"
            f"atomic_propositions: {json.dumps(prob['ap_dict'], indent=2)}")
    raw, usage, elapsed = call_claude(prompt, user)
    ltl = extract_ltl(raw)

    record = json.dumps({
        "id":            prob["id"],
        "run_idx":       run_idx,
        "dataset":       prob["dataset"],
        "row_idx":       prob["row_idx"],
        "nl":            prob["nl"],
        "labels":        prob["labels"],
        "output_LTL":    ltl or "",
        "raw":           raw,
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
        print(f"[{done}/{total}] {prob['id']}[{run_idx}] ({prob['dataset']})  "
              f"variant={variant}  ltl={ltl!r}  t={elapsed:.2f}s  cost=${total_cost:.4f}")


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
    print("Loading benchmark data...")
    dataset = load_dataset()

    by_ds = defaultdict(int)
    for p in dataset:
        by_ds[p["dataset"]] += 1
    n_total = len(dataset)
    print(f"Sub-datasets: { {k: v for k, v in by_ds.items()} }  total={n_total}")

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    # unique problem IDs that have at least one run still needed
    need_a = {p["id"] for p in dataset if any((p["id"], i) not in done_a for i in range(K))}
    need_b = {p["id"] for p in dataset if any((p["id"], i) not in done_b for i in range(K))}

    candidate = [
        p for p in dataset
        if (run_a and p["id"] in need_a) or (run_b and p["id"] in need_b)
    ]

    if args.n is not None:
        if args.variant == "B" and done_a:
            # B must run on exactly the same problems as A — never re-sample
            a_ids     = {pid for pid, _ in done_a}
            candidate = [p for p in dataset if p["id"] in a_ids]
        elif args.variant == "both" and done_a:
            a_ids = {pid for pid, _ in done_a}
            b_ids = {pid for pid, _ in done_b}
            if a_ids - b_ids:
                # B is behind A — catch up to A's existing IDs first
                candidate = [p for p in dataset if p["id"] in a_ids]
            else:
                # A and B in sync — sample new problems beyond what's already done
                done_ids = a_ids
                already  = len(done_ids)
                n_need   = max(0, args.n - already)
                candidate = stratified_sample(
                    [p for p in candidate if p["id"] not in done_ids],
                    min(n_need, len(candidate)), args.seed
                )
        else:
            done_ids = {pid for pid, _ in done_a}  # A variant or fresh both
            already  = len(done_ids)
            n_need   = max(0, args.n - already)
            candidate = stratified_sample(
                [p for p in candidate if p["id"] not in done_ids],
                min(n_need, len(candidate)), args.seed
            )

    lock_a = threading.Lock()
    lock_b = threading.Lock()

    all_tasks = []
    for p in candidate:
        for i in range(K):
            if run_a and (p["id"], i) not in done_a:
                all_tasks.append((p, i, "A", prompt_a, out_a, lock_a))
            if run_b and (p["id"], i) not in done_b:
                all_tasks.append((p, i, "B", prompt_b, out_b, lock_b))

    print(f"Model: {MODEL}  |  k={K}  |  Tasks to run: {len(all_tasks)}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}\n")

    counters     = {"in": 0, "out": 0, "cost": 0.0, "done": 0}
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, p, i, v, pr, o, lk, counters, counter_lock, len(all_tasks))
            for p, i, v, pr, o, lk in all_tasks
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
