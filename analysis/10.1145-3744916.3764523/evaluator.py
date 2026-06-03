#!/usr/bin/env python3
"""
Compute PA, PTA, RTA, GA (Table 2 metrics) for Thunderbird results
produced by run_random.py for Prompt A and Prompt B.

Usage:
    python3.11 evaluate.py <dataset_name>

Example:
    python3.11 evaluate.py Thunderbird
"""

import csv
import json
import os
import sys
from collections import Counter

INFERLOG_ROOT  = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT   = os.path.join(INFERLOG_ROOT, "benchmark", "dataset")
OUTPUT_FOLDER  = os.path.join(INFERLOG_ROOT, "output")
RESULTS_FOLDER = os.path.join(INFERLOG_ROOT, "results")
PROMPTS        = ["A", "B"]


# ── loaders ───────────────────────────────────────────────────────────────────

def load_groundtruth(dataset_name: str) -> tuple:
    """Return ({content: event_template}, total_row_count) for the ground truth CSV."""
    path = os.path.join(
        DATASET_ROOT, dataset_name,
        f"{dataset_name}_2k.log_structured_corrected.csv",
    )
    gt = {}
    total = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gt[row["Content"]] = row["EventTemplate"]
            total += 1
    return gt, total


def load_results(prompt_letter: str, dataset_name: str) -> list:
    """Return list of (content, predicted_template) from the output CSV."""
    path = os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{prompt_letter}.csv")
    if not os.path.exists(path):
        print(f"[!] Output CSV not found: {path}")
        sys.exit(1)
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((row["Content"], row["log_template"]))
    return rows


# ── metrics (same logic as inferlog.py) ──────────────────────────────────────

def evaluate_PA(merged: list) -> float:
    """Fraction of logs whose predicted template exactly matches ground truth."""
    if not merged:
        return 0.0
    correct = sum(1 for _, pred, gt in merged if pred == gt)
    return correct / len(merged)


def evaluate_PTA(merged: list) -> float:
    """Precision Template Accuracy: correctly identified templates / total identified."""
    oracle = {}   # gt_template  → [content, ...]
    result = {}   # pred_template → [content, ...]
    for content, pred, gt in merged:
        oracle.setdefault(gt,   []).append(content)
        result.setdefault(pred, []).append(content)

    correct = sum(
        1 for t, logs in result.items()
        if t in oracle and Counter(oracle[t]) == Counter(logs)
    )
    return correct / len(result) if result else 0.0


def evaluate_RTA(merged: list) -> float:
    """Recall Template Accuracy: correctly identified templates / total oracle templates."""
    oracle = {}
    result = {}
    for content, pred, gt in merged:
        oracle.setdefault(gt,   []).append(content)
        result.setdefault(pred, []).append(content)

    correct = sum(
        1 for t, logs in oracle.items()
        if t in result and Counter(result[t]) == Counter(logs)
    )
    return correct / len(oracle) if oracle else 0.0


def evaluate_GA(merged: list) -> float:
    """Grouping Accuracy: logs in correctly grouped clusters / total evaluated logs."""
    oracle_groups = {}
    for content, _, gt in merged:
        oracle_groups.setdefault(gt, []).append(content)
    for k in oracle_groups:
        oracle_groups[k].sort()

    result_groups = {}
    for content, pred, _ in merged:
        result_groups.setdefault(pred, []).append(content)
    for k in result_groups:
        result_groups[k].sort()

    oracle_lists = list(oracle_groups.values())
    count = sum(
        len(pred_list)
        for pred_list in result_groups.values()
        if pred_list in oracle_lists
    )
    return count / len(merged) if merged else 0.0


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3.11 evaluate.py <dataset_name>")
        sys.exit(1)

    dataset_name    = sys.argv[1]
    groundtruth, total_rows = load_groundtruth(dataset_name)
    unique_contents = len(groundtruth)

    print(f"\nDataset        : {dataset_name}")
    print(f"Total rows     : {total_rows}  (unique log messages: {unique_contents})")
    print(f"Metrics        : PA | PTA | RTA | GA  (same as Table 2 in paper)")
    print("-" * 60)

    for letter in PROMPTS:
        results = load_results(letter, dataset_name)

        # Join each output row with ground truth by content
        merged = []
        missing_gt = 0
        for content, pred in results:
            if content in groundtruth:
                merged.append((content, pred, groundtruth[content]))
            else:
                missing_gt += 1

        if missing_gt:
            print(f"[!] Prompt {letter}: {missing_gt} entries had no matching ground truth.")

        n = len(merged)
        PA  = evaluate_PA(merged)
        PTA = evaluate_PTA(merged)
        RTA = evaluate_RTA(merged)
        GA  = evaluate_GA(merged)

        print(f"\nPrompt {letter}  ({n}/{total_rows} rows evaluated)")
        print(f"  PA  : {PA*100:.1f}%")
        print(f"  PTA : {PTA*100:.1f}%")
        print(f"  RTA : {RTA*100:.1f}%")
        print(f"  GA  : {GA*100:.1f}%")

        # Save to file
        out = {
            "dataset":           dataset_name,
            "prompt":            letter,
            "total_rows":        total_rows,
            "unique_contents":   unique_contents,
            "rows_evaluated":    n,
            "note": (
                "Metrics computed on evaluated subset. "
                "Full 2000-row run needed for exact Table 2 comparison."
                if n < total_rows else
                "Full dataset evaluated — directly comparable to Table 2."
            ),
            "metrics": {
                "PA":  round(PA,  6),
                "PTA": round(PTA, 6),
                "RTA": round(RTA, 6),
                "GA":  round(GA,  6),
            },
            "metrics_pct": {
                "PA":  round(PA  * 100, 1),
                "PTA": round(PTA * 100, 1),
                "RTA": round(RTA * 100, 1),
                "GA":  round(GA  * 100, 1),
            },
        }

        out_path = os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{letter}_metrics.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"  Saved: {out_path}")

        # Write results/results_{letter}.jsonl
        os.makedirs(RESULTS_FOLDER, exist_ok=True)
        jsonl_path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as jf:
            jf.write(json.dumps(out) + "\n")
            for content, pred, gt in merged:
                jf.write(json.dumps({
                    "Content":                content,
                    "predicted_template":     pred,
                    "ground_truth_template":  gt,
                    "PA_match":               (pred == gt),
                }) + "\n")
        print(f"  Saved: {jsonl_path}")

    print()


if __name__ == "__main__":
    main()
