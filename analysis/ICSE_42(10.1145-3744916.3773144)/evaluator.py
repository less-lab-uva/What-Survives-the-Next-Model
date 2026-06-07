"""
AdapTrack — evaluator: score outputs against ground_truth using EM@1.
Usage: python evaluator.py <A|B> --setting <v1|v2>
Input:  outputs/outputs_{A|B}_{setting}.jsonl
Output: results/results_{A|B}_{setting}.jsonl

Table 1 evaluates the same 419 synthetic TF API completions under two oracle settings.
In the TFv1 setting, the ground truth is the native short path (e.g. .losses.mean_pairwise_squared_error)
— simulating a user on TF1. In the TFv2 setting, the same API requires the compat.v1. prefix
(e.g. .compat.v1.losses.mean_pairwise_squared_error) — simulating a user on TF2 calling a
deprecated v1 API. The paper enforces each setting via a constrainer; we replicate by
swapping the oracle string on the same model outputs.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def v2_oracle(ground_truth):
    if ground_truth.startswith(".compat.v1."):
        return ground_truth
    return ".compat.v1." + ground_truth[1:]


def run_eval(records, setting):
    per_instance = []
    live = defaultdict(lambda: [0, 0])

    for i, r in enumerate(records):
        pred    = (r.get("prediction") or "").strip()
        gt_raw  = (r.get("ground_truth") or "").strip()
        dataset = r.get("dataset", "unknown")

        oracle  = v2_oracle(gt_raw) if setting == "v2" else gt_raw
        correct = bool(pred) and pred == oracle

        row = {"id": r["id"], "dataset": dataset, "ground_truth": oracle,
               "prediction": pred, "correct": correct, "score": 1 if correct else 0}
        per_instance.append(row)

        live[dataset][0] += correct
        live[dataset][1] += 1
        total_c = sum(v[0] for v in live.values())
        total_n = sum(v[1] for v in live.values())
        parts = "  |  ".join(
            f"{ds}: {p}/{n} ({100*p/n:.1f}%)" for ds, (p, n) in sorted(live.items())
        )
        status = "CORRECT" if correct else "WRONG"
        print(f"  [{i+1}/{len(records)}] {r['id']} -> {status}  pred={pred!r}"
              f"  |  {parts}  |  Total: {total_c}/{total_n} ({100*total_c/total_n:.1f}%)",
              flush=True)

    return per_instance


def summarise(variant, setting, per_instance, in_path, out_path):
    print(f"\n{'='*50}\nSUMMARY  Prompt {variant}  setting={setting}\n{'='*50}")
    live = defaultdict(lambda: [0, 0])
    for r in per_instance:
        live[r["dataset"]][0] += r["score"]
        live[r["dataset"]][1] += 1

    agg_by_ds = {}
    for ds, (p, n) in sorted(live.items()):
        rate = round(p / n, 4) if n else 0
        agg_by_ds[ds] = {"em@1": rate, "passed": p, "total": n}
        print(f"  {ds}: {p}/{n} ({100*rate:.1f}%)")

    total  = len(per_instance)
    passed = sum(r["score"] for r in per_instance)
    em     = round(passed / total, 4) if total else 0.0
    print(f"\n  Overall EM@1: {em}  ({passed}/{total})")

    times = [json.loads(l)["response_time"] for l in in_path.read_text().splitlines()
             if l.strip() and "response_time" in json.loads(l)]
    avg_response_time = round(sum(times) / len(times), 3) if times else None

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {
            "em@1": em, "passed": passed, "total": total,
            "setting": setting,
            "by_dataset": agg_by_ds,
            "avg_response_time": avg_response_time,
        }}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"  Results saved to {out_path}")


def run_variant(variant, setting):
    sfx      = f"_{setting}"
    in_path  = HERE / "outputs" / f"outputs_{variant}{sfx}.jsonl"
    out_path = HERE / "results" / f"results_{variant}_{setting}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    if not in_path.exists():
        print(f"Skipping {variant}/{setting}: {in_path} not found")
        return

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    print(f"\n--- Prompt {variant}  setting={setting}: {len(records)} outputs ---")
    per_instance = run_eval(records, setting)
    summarise(variant, setting, per_instance, in_path, out_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to evaluate (default: both)")
    parser.add_argument("--setting", choices=["v1", "v2", "both"], default="both",
                        help="oracle setting(s) to evaluate (default: both)")
    args = parser.parse_args()

    variants = ["A", "B"] if args.variant == "both" else [args.variant]
    settings = ["v1", "v2"] if args.setting == "both" else [args.setting]

    for v in variants:
        for s in settings:
            run_variant(v, s)


if __name__ == "__main__":
    main()
