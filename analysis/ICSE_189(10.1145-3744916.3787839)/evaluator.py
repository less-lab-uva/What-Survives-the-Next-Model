"""Score the RQ2 oracle predictions against the gold derailment labels, one file per prompt.

Reads outputs/output_{A,B}.jsonl ({issue_id, pred_score, true_label}) and reports
precision / recall / F1 at each decision threshold — the paper's metric (P/R/F1 on true_label
vs pred_score >= threshold, from TP/FP/FN; the paper headlines F1 at threshold 0.3). Writes
results/results_A.json and results/results_B.json.

Like main.py: fixed paths, prerequisites checked up front, hard-abort, will NOT overwrite
existing results files.
"""

import os
import sys
import json
import pandas as pd

THRESHOLDS = [0.1, 0.3, 0.5, 0.7]

OUTPUTS = {"A": "outputs/output_A.jsonl", "B": "outputs/output_B.jsonl"}
RESULTS = {"A": "results/results_A.json", "B": "results/results_B.json"}

# Preconditions.
for path in OUTPUTS.values():
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path} (run main.py first)")
for path in RESULTS.values():
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")

os.makedirs("results", exist_ok=True)


def score(tag: str) -> dict:
    df = pd.read_json(OUTPUTS[tag], lines=True)
    if not {"pred_score", "true_label"}.issubset(df.columns):
        sys.exit(f"ABORT: {OUTPUTS[tag]} missing pred_score/true_label columns")

    y_true = df["true_label"] == 1
    per_threshold = {}
    for t in THRESHOLDS:
        y_pred = df["pred_score"] >= t
        tp = int((y_pred & y_true).sum())
        fp = int((y_pred & ~y_true).sum())
        fn = int((~y_pred & y_true).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0  # zero_division=0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_threshold[str(t)] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return {
        "prompt": tag,
        "metric": "precision/recall/F1 on true_label vs pred_score >= threshold; headline F1@0.3",
        "thresholds": THRESHOLDS,
        "n_threads": int(len(df)),
        "n_positive": int(y_true.sum()),
        "per_threshold": per_threshold,
    }


for tag in ("A", "B"):
    report = score(tag)
    with open(RESULTS[tag], "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved {RESULTS[tag]}")

print("F1 by threshold:")
a = score("A")["per_threshold"]
b = score("B")["per_threshold"]
for t in THRESHOLDS:
    print(f"  F1@{t}:  A={a[str(t)]['f1']}  B={b[str(t)]['f1']}")
