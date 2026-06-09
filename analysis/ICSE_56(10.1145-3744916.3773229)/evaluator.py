"""Score the ConfuGuard oracle -> Table 5 (active / stealthy / benign + overall, per dataset),
one results file per prompt variant.

Static scoring, no infra. Predictions come from outputs/output_{A,B}.jsonl (one row per package
occurrence, tagged with `dataset`); the gold label/category is recovered from the source CSVs (it
was never sent to the model). The positive class is THREAT (active | stealthy); benign packages
have no positives, so their precision/recall/F1 are reported as null ("-" in the paper) and only
accuracy is meaningful.

Packages appearing in multiple rows are aggregated to one verdict — typosquat if ANY of their rows
is predicted/labelled a typosquat — matching the paper's package-level counts. Category for a
package is the most severe seen (active > stealthy > benign).

Writes results/results_A.json and results/results_B.json. Fixed paths, preconditions up front,
hard-abort, will NOT overwrite existing results files.
"""

import os
import sys
import csv
import json

CATEGORIES = ["active", "stealthy", "benign"]
SEVERITY = {"active": 3, "stealthy": 2, "benign": 1}

# source datasets (gold lives here) — the same $15 sample main.py ran on
CONFUDB      = "inputs/ConfuDB.down_sampled_15usd.csv"
REAL_MALWARE = "inputs/NeupaneDB_real_malware.down_sampled_15usd.csv"
NO_MALWARE   = "inputs/NeupaneDB_no_malware.down_sampled_15usd.csv"

OUTPUTS = {"A": "outputs/output_A.jsonl", "B": "outputs/output_B.jsonl"}
RESULTS = {"A": "results/results_A.json", "B": "results/results_B.json"}

# the package-identifier column per dataset (used to aggregate predictions to packages)
DATASET_KEY = {
    "ConfuDB": "name",
    "NeupaneDB_real_malware": "typosquat_pkg",
    "NeupaneDB_no_malware": "Adversarial pkg",
}

# Preconditions.
for path in (CONFUDB, REAL_MALWARE, NO_MALWARE, OUTPUTS["A"], OUTPUTS["B"]):
    if not os.path.exists(path):
        sys.exit(f"ABORT: missing {path} (run main.py first)")
for path in RESULTS.values():
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists: {path}")


def read_rows(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8") as fin:
        return list(csv.DictReader(fin))


def accumulate(gold: dict, package: str, category: str) -> None:
    """Keep the most severe category seen for a package."""
    if package not in gold or SEVERITY[category] > SEVERITY[gold[package]]:
        gold[package] = category


def gold_confudb() -> dict:
    """name -> category, from ConfuDB threat_type."""
    gold = {}
    for row in read_rows(CONFUDB):
        tt = row["threat_type"].strip().lower()
        category = "benign" if tt == "false_positive" else "stealthy" if tt == "typosquat" else "active"
        accumulate(gold, row["name"], category)
    return gold


def gold_neupane() -> dict:
    """package -> category, from real_malware (active) + no_malware (benign/stealthy)."""
    gold = {}
    for row in read_rows(REAL_MALWARE):
        if row["confusion"].strip().upper() == "TP":          # drop UNK
            accumulate(gold, row["typosquat_pkg"], "active")
    for row in read_rows(NO_MALWARE):
        category = "benign" if row["is_FP?"].strip().lower() == "yes" else "stealthy"
        accumulate(gold, row["Adversarial pkg"], category)
    return gold


def load_preds(tag: str) -> dict:
    """dataset -> {package -> predicted is_typosquat (True if ANY of its rows is a typosquat)}."""
    preds = {}
    with open(OUTPUTS[tag], encoding="utf-8") as fin:
        for line in fin:
            if not line.strip():
                continue
            row = json.loads(line)
            ds = row["dataset"]
            pkg = row[DATASET_KEY[ds]]
            preds.setdefault(ds, {})
            preds[ds][pkg] = preds[ds].get(pkg, False) or bool(row["is_typosquat"])
    return preds


def metrics_from_counts(tp: int, fp: int, tn: int, fn: int) -> dict:
    has_positives = (tp + fn) > 0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else 0.0
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 4) if has_positives else None,
        "recall": round(recall, 4) if has_positives else None,
        "f1": round(f1, 4) if has_positives else None,
        "accuracy": round(accuracy, 4),
    }


def score(gold: dict, preds: dict) -> dict:
    """Bucket packages by gold category, count with threat=positive, compute metrics."""
    counts = {c: [0, 0, 0, 0] for c in CATEGORIES}  # [tp, fp, tn, fn]
    overall = [0, 0, 0, 0]
    for package, category in gold.items():
        gt_threat = category != "benign"
        pred_threat = preds.get(package, False)
        idx = 0 if (gt_threat and pred_threat) else 1 if (not gt_threat and pred_threat) \
            else 2 if (not gt_threat and not pred_threat) else 3
        counts[category][idx] += 1
        overall[idx] += 1
    result = {c: metrics_from_counts(*counts[c]) for c in CATEGORIES}
    result["overall"] = metrics_from_counts(*overall)
    return result


os.makedirs("results", exist_ok=True)
for tag in ("A", "B"):
    preds = load_preds(tag)
    neupane_preds = {**preds.get("NeupaneDB_real_malware", {}),
                     **preds.get("NeupaneDB_no_malware", {})}
    report = {
        "prompt": tag,
        "metric": ("Table 5 (EQ5): per dataset x {active,stealthy,benign,overall} -> tp/fp/tn/fn "
                   "+ precision/recall/f1/accuracy. Positive class = threat; benign has no "
                   "positives so P/R/F1 are null."),
        "ConfuDB": score(gold_confudb(), preds.get("ConfuDB", {})),
        "NeupaneDB": score(gold_neupane(), neupane_preds),
    }
    with open(RESULTS[tag], "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved {RESULTS[tag]}")
    for dataset in ("ConfuDB", "NeupaneDB"):
        o = report[dataset]["overall"]
        print(f"  {tag} {dataset:10} overall: "
              f"P={o['precision']} R={o['recall']} F1={o['f1']} Acc={o['accuracy']}")
