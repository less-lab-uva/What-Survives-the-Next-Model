"""
ADARULE — evaluator: score NL-to-LTL outputs via Spot semantic equivalence.
Usage: python evaluator.py <A|B>
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl
Conda:  adarule_env  (has spot)
"""

import argparse
import json
import sys
from pathlib import Path

import spot

HERE = Path(__file__).parent


def ltl_equivalent(pred, truth):
    if not pred:
        return False, "no formula"
    try:
        eq = spot.are_equivalent(
            spot.formula(pred.upper()),
            spot.formula(truth.upper()),
        )
        return eq, None
    except Exception as e:
        return False, f"spot error: {e}"


def run_variant(variant):
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = HERE / "results" / f"results_{variant}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    print(f"\n--- Prompt {variant}: {len(records)} outputs ---")

    per_instance = []
    for r in records:
        pred         = r.get("prediction") or ""
        ground_truth = r.get("ground_truth") or ""
        eq, err = ltl_equivalent(pred, ground_truth)
        per_instance.append({
            "id":           r["id"],
            "nl":           r.get("nl", ""),
            "ground_truth": ground_truth,
            "prediction":   pred,
            "equivalent":   eq,
            "error":        err,
            "score":        1 if eq else 0,
        })
        status = "CORRECT" if eq else f"WRONG ({err or ''})"
        print(f"  [{r['id']}] {status}")

    total    = len(per_instance)
    passed   = sum(r["score"] for r in per_instance)
    accuracy = round(passed / total, 4) if total else 0.0

    print(f"\n{'='*40}\nSUMMARY — Prompt {variant}\n{'='*40}")
    print(f"Total   : {total}")
    print(f"Passed  : {passed} ({100*accuracy:.1f}%)")
    print(f"Accuracy: {accuracy}")

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {"accuracy": accuracy, "passed": passed,
                                          "failed": total - passed, "total": total}}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"Results saved to {out_path}")


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
