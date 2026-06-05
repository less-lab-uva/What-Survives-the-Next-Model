"""Score the RQ2 oracle predictions against the gold derailment labels.

Reports precision / recall / F1 at each decision threshold for prompt A and prompt B
— the paper's metric (P/R/F1 on true_label vs pred_score >= threshold, computed directly
from TP/FP/FN; the paper headlines F1 at threshold 0.3). Writes results/metrics.json.

Like main.py: fixed paths, prerequisites checked up front, hard-abort on anything not set
up, and it will NOT overwrite an existing metrics file.
"""

import os
import sys
import json
import pandas as pd

THRESHOLDS = [0.1, 0.3, 0.5, 0.7]

PRED_A = "outputs/oracle-claude-sonnet-4-6-a-our.csv"
PRED_B = "outputs/oracle-claude-sonnet-4-6-b-our.csv"

METRICS = "results/metrics.json"

# Preconditions.
if not os.path.exists(PRED_A):
    sys.exit(f"ABORT: missing {PRED_A} (run main.py first)")
if not os.path.exists(PRED_B):
    sys.exit(f"ABORT: missing {PRED_B} (run main.py first)")
if os.path.exists(METRICS):
    sys.exit(f"ABORT: output already exists: {METRICS}")

os.makedirs("results", exist_ok=True)


def score(pred_csv):
    df = pd.read_csv(pred_csv)
    if not {"pred_score", "true_label"}.issubset(df.columns):
        sys.exit(f"ABORT: {pred_csv} missing pred_score/true_label columns")

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
        "file": os.path.basename(pred_csv),
        "n_threads": int(len(df)),
        "n_positive": int(y_true.sum()),
        "thresholds": per_threshold,
    }


results = {
    "thresholds": THRESHOLDS,
    "A": score(PRED_A),
    "B": score(PRED_B),
}

with open(METRICS, "w") as f:
    json.dump(results, f, indent=2)

print(f"Saved {METRICS}")
for t in THRESHOLDS:
    a = results["A"]["thresholds"][str(t)]["f1"]
    b = results["B"]["thresholds"][str(t)]["f1"]
    print(f"  F1@{t}:  A={a}  B={b}")
