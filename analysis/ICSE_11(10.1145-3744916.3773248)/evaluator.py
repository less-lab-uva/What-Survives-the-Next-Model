"""
LogPipe — evaluator: compute F1-score (anomaly class) from log anomaly outputs.
Usage: python evaluator.py [--variant {A,B,both}]
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

DATASETS_ORDER = ["BGL", "Spirit", "Thunderbird", "HDFS", "Hadoop2", "Hadoop3", "Spark2", "Spark3"]


def compute_metrics(y_true, y_pred):
    from sklearn.metrics import f1_score, precision_score, recall_score
    n_parsed = sum(1 for p in y_pred if p is not None)
    y_safe   = [p if p is not None else 1 for p in y_pred]
    return {
        "f1":        round(f1_score(y_true, y_safe, pos_label=0, zero_division=0), 4),
        "precision": round(precision_score(y_true, y_safe, pos_label=0, zero_division=0), 4),
        "recall":    round(recall_score(y_true, y_safe, pos_label=0, zero_division=0), 4),
        "n":         len(y_true),
        "n_parsed":  n_parsed,
    }


def run_variant(variant):
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = HERE / "results" / f"results_{variant}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    times = [r["response_time"] for r in records if "response_time" in r]
    avg_rt = round(sum(times) / len(times), 3) if times else None
    print(f"\n--- Variant {variant} ---")
    print(f"Loaded {len(records)} outputs  |  avg_response_time={avg_rt}s")

    by_dataset = defaultdict(list)
    per_instance = []
    for r in records:
        pred  = r.get("pred")
        label = r.get("label")
        correct = (pred == label) if pred is not None else False
        row = {
            "dataset":  r["dataset"],
            "block_id": r["block_id"],
            "label":    label,
            "pred":     pred,
            "correct":  correct,
            "score":    1 if correct else 0,
        }
        per_instance.append(row)
        by_dataset[r["dataset"]].append(row)

    print(f"\n{'='*65}\nSUMMARY (F1, anomaly class, pos_label=0)\n{'='*65}")
    print(f"{'Dataset':<14} {'F1':>6} {'Prec':>6} {'Recall':>6}  {'n':>5}")
    print("-" * 40)

    per_ds_agg = {}
    for name in DATASETS_ORDER:
        rows = by_dataset.get(name, [])
        if not rows:
            continue
        y_true = [r["label"] for r in rows]
        y_pred = [r["pred"] for r in rows]
        m = compute_metrics(y_true, y_pred)
        per_ds_agg[name] = m
        print(f"  {name:<12} {m['f1']:>6.3f} {m['precision']:>6.3f} {m['recall']:>6.3f}  {m['n']:>5}")

    all_true = [r["label"] for r in per_instance]
    all_pred = [r["pred"] for r in per_instance]
    m_all = compute_metrics(all_true, all_pred) if per_instance else {
        "f1": 0.0, "precision": 0.0, "recall": 0.0, "n": 0, "n_parsed": 0,
    }
    print("-" * 40)
    print(f"  {'ALL':<12} {m_all['f1']:>6.3f} {m_all['precision']:>6.3f} {m_all['recall']:>6.3f}  {m_all['n']:>5}")

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {
            "overall_f1": m_all["f1"], "total": m_all["n"],
            "avg_response_time": avg_rt, "by_dataset": per_ds_agg,
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
