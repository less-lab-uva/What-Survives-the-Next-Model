"""
HoarePrompt evaluator.
Reads outputs JSONL produced by main.py and computes classification metrics.

Usage:
  python evaluator.py [--prompt A|B|both] [--n N]

Input:  outputs/outputs_{P}.jsonl
Output: results/results_{P}.jsonl
"""

import argparse
import json
import math
from pathlib import Path


def compute_metrics(records):
    n = len(records)
    if n == 0:
        return {}
    tp = sum(1 for r in records if r["ground_truth"] == "CORRECT"   and r["predicted"] == "CORRECT")
    tn = sum(1 for r in records if r["ground_truth"] == "INCORRECT" and r["predicted"] == "INCORRECT")
    fp = sum(1 for r in records if r["ground_truth"] == "INCORRECT" and r["predicted"] == "CORRECT")
    fn = sum(1 for r in records if r["ground_truth"] == "CORRECT"   and r["predicted"] == "INCORRECT")
    accuracy = (tp + tn) / n
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    tnr = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0  # miss rate
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0  # fall-out
    balanced_acc = (tpr + tnr) / 2
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn) - (fp * fn)) / denom if denom != 0 else 0.0
    return {
        "accuracy":           round(accuracy,     4),
        "balanced_accuracy":  round(balanced_acc, 4),
        "true_positive_rate": round(tpr, 4),
        "true_negative_rate": round(tnr, 4),
        "false_negative_rate": round(fnr, 4),
        "false_positive_rate": round(fpr, 4),
        "mcc":  round(mcc, 4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


def evaluate_prompt(prompt_label: str, n):
    outputs_path = Path(__file__).parent / "outputs" / f"outputs_{prompt_label}.jsonl"
    if not outputs_path.exists():
        print(f"ERROR: outputs file not found: {outputs_path}")
        print("Run main.py first.")
        return

    records = []
    with open(outputs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    valid = [r for r in records if r.get("predicted") in ("CORRECT", "INCORRECT")]
    metrics = compute_metrics(valid)

    print(f"\n{'='*50}")
    print(f"SUMMARY — Prompt {prompt_label} — {len(records)} examples ({len(valid)} with valid verdict)")
    print(f"  Accuracy          : {metrics.get('accuracy', 0):.1%}")
    print(f"  Balanced Accuracy : {metrics.get('balanced_accuracy', 0):.3f}")
    print(f"  True Pos Rate     : {metrics.get('true_positive_rate', 0):.3f}")
    print(f"  True Neg Rate     : {metrics.get('true_negative_rate', 0):.3f}")
    print(f"  False Neg Rate    : {metrics.get('false_negative_rate', 0):.3f}")
    print(f"  False Pos Rate    : {metrics.get('false_positive_rate', 0):.3f}")
    print(f"  MCC               : {metrics.get('mcc', 0):.3f}")
    print(f"  TP={metrics.get('tp',0)} TN={metrics.get('tn',0)} FP={metrics.get('fp',0)} FN={metrics.get('fn',0)}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {**metrics, "total": len(records), "valid_verdicts": len(valid), "total_llm_time": round(sum(r.get("llm_response_time", 0.0) for r in records), 3)}
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nResults saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n", type=lambda v: "all" if str(v).lower() == "all" else int(v), default=5)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
