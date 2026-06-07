"""
ARTEMIS — evaluator: score LTL outputs via Spot semantic equivalence.
Metric: pass@10 — a requirement passes if any of its k=10 runs is semantically
equivalent to a plausible label (matches the paper's evaluation protocol).
Usage: python evaluator.py [--variant {A,B,both}]
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import spot

HERE = Path(__file__).parent


def check_equiv(output_ltl, labels):
    if not output_ltl:
        return False
    try:
        out_aut = spot.translate(output_ltl)
        for lbl in labels:
            lbl_aut = spot.translate(lbl)
            if spot.contains(lbl_aut, out_aut) and spot.contains(out_aut, lbl_aut):
                return True
    except Exception:
        pass
    return False


def run_variant(variant):
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = HERE / "results" / f"results_{variant}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    for v in ("A", "B"):
        p = HERE / "outputs" / f"outputs_{v}.jsonl"
        if p.exists():
            times = [json.loads(l)["response_time"] for l in p.read_text().splitlines()
                     if l.strip() and "response_time" in json.loads(l)]
            avg = sum(times) / len(times) if times else 0
            print(f"Avg response time — Prompt {v}: {avg:.2f}s  (n={len(times)})")
    print()

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(records)} runs")

    by_id = defaultdict(list)
    for r in records:
        by_id[r["id"]].append(r)

    print(f"Unique requirements: {len(by_id)}\n")

    per_instance = []
    live = defaultdict(lambda: [0, 0])

    for i, (req_id, runs) in enumerate(sorted(by_id.items())):
        dataset = runs[0]["dataset"]
        labels  = runs[0].get("labels", [])

        passed      = False
        best_ltl    = ""
        run_results = []
        for r in runs:
            ltl  = r.get("output_LTL") or ""
            ok   = check_equiv(ltl, labels)
            run_results.append({"run_idx": r.get("run_idx", 0), "output_LTL": ltl, "pass": ok})
            if ok:
                passed   = True
                best_ltl = ltl

        row = {"id": req_id, "dataset": dataset, "pass@10": passed,
               "score": 1 if passed else 0, "runs": run_results}
        per_instance.append(row)

        live[dataset][0] += passed
        live[dataset][1] += 1
        total_p = sum(v[0] for v in live.values())
        total_n = sum(v[1] for v in live.values())
        parts = "  |  ".join(
            f"{ds}: {p}/{n} ({100*p/n:.1f}%)" for ds, (p, n) in sorted(live.items())
        )
        n_runs = len(runs)
        print(f"  [{i+1}/{len(by_id)}] {req_id} ({n_runs} runs) -> {'PASS' if passed else 'FAIL'}"
              f"  |  {parts}  |  Total: {total_p}/{total_n} ({100*total_p/total_n:.1f}%)",
              flush=True)

    print(f"\n{'='*50}\nSUMMARY\n{'='*50}")
    agg_by_ds = {}
    for ds, (p, n) in sorted(live.items()):
        rate = round(p / n, 4) if n else 0
        agg_by_ds[ds] = {"pass@10": rate, "passed": p, "total": n}
        print(f"  {ds:<20} {p}/{n} ({100*rate:.1f}%)")

    total  = len(per_instance)
    passed = sum(r["score"] for r in per_instance)
    acc    = round(passed / total, 4) if total else 0.0
    print(f"\n  Overall pass@10: {acc}  ({passed}/{total})")

    times = [json.loads(l)["response_time"] for l in in_path.read_text().splitlines()
             if l.strip() and "response_time" in json.loads(l)]
    avg_response_time = round(sum(times) / len(times), 3) if times else None

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {
            "pass@10": acc, "passed": passed, "total": total,
            "by_dataset": agg_by_ds,
            "avg_response_time": avg_response_time,
        }}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"\nResults saved to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to evaluate (default: both)")
    args = parser.parse_args()

    variants = ["A", "B"] if args.variant == "both" else [args.variant]
    for v in variants:
        run_variant(v)


if __name__ == "__main__":
    main()
