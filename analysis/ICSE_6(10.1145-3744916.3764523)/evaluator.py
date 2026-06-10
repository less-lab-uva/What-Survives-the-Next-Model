#!/usr/bin/env python3
"""
Evaluator for the single-call LLM log parsing pipeline.
Usage: python3 evaluator.py

Reads:
  outputs/outputs_{A|B}.jsonl              (aggregate mode, default)
  OR outputs/{dataset}_outputs_{A|B}.jsonl  (per-dataset mode)
  data/{dataset}_2k.log_structured_corrected.csv  (ground truth)

Writes:
  results/results_{A|B}.jsonl
    Line 1: aggregated metrics across all evaluated datasets
    Line 2+: one line per dataset, including paper's Table 2 numbers for comparison

Metrics match the paper's Table 2 (InferLog, ICSE 2026):
  PA  — Parsing Accuracy: fraction of logs whose predicted template exactly matches ground truth
  PTA — Precision Template Accuracy: correctly identified templates / total predicted templates
  RTA — Recall Template Accuracy: correctly identified templates / total oracle templates
  GA  — Grouping Accuracy: logs in correctly grouped clusters / total logs in dataset

GA denominator:
  When all 2000 logs are evaluated: denominator = 2000 (matches paper's hardcoded /2000 exactly).
  When partial: denominator = rows_evaluated (gives a meaningful in-subset estimate).

Paper-reported results (Table 2, InferLog ICSE 2026):
  "w/o_inferlog" = original LLM parser without PAIR acceleration (baseline column)
  "w_inferlog"   = same parser with InferLog's PAIR optimisation (paper's system)

  Dataset  | w/o InferLog PA / PTA / RTA / GA  | w/ InferLog PA / PTA / RTA / GA
  HPC      | 98.4 / 75.0 / 84.8 / 94.9        | 99.3 / 71.7 / 82.6 / 93.4
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
OUTPUT_DIR   = BASE_DIR / "outputs"
RESULTS_DIR  = BASE_DIR / "results"
PROMPTS      = ["A", "B"]

TOTAL_ROWS_PER_DATASET = 2000  # Loghub-2k: 2000 logs per dataset

# Table 2 results from InferLog paper (ICSE 2026).
# Hardcoded here so the evaluator never reads from any prior run.
PAPER_RESULTS = {
    "HPC": {
        "w/o_inferlog": {"PA": 98.4, "PTA": 75.0, "RTA": 84.8, "GA": 94.9},
        "w_inferlog":   {"PA": 99.3, "PTA": 71.7, "RTA": 82.6, "GA": 93.4},
    },
}


# ── output loaders ────────────────────────────────────────────────────────────

def load_outputs(letter):
    """Return all output entries for prompt letter, sorted by line_id ascending."""
    aggregate = OUTPUT_DIR / f"outputs_{letter}.jsonl"
    if aggregate.exists():
        entries = _read_jsonl(aggregate)
    else:
        entries = []
        for path in sorted(OUTPUT_DIR.glob(f"*_outputs_{letter}.jsonl")):
            entries.extend(_read_jsonl(path))
    entries.sort(key=lambda e: int(e.get("line_id", 0)))
    return entries


def _read_jsonl(path):
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def load_groundtruth(dataset_name):
    """Return {content: event_template} from the ground truth CSV."""
    path = DATA_DIR / f"{dataset_name}_2k.log_structured_corrected.csv"
    if not path.exists():
        print(f"  [!] Ground truth CSV not found: {path}")
        return {}
    gt = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gt[row["Content"]] = row["EventTemplate"]
    return gt


# ── metrics ───────────────────────────────────────────────────────────────────

def evaluate_PA(merged):
    """Fraction of logs whose predicted template exactly matches ground truth."""
    if not merged:
        return 0.0
    return sum(1 for _, pred, gt in merged if pred == gt) / len(merged)


def evaluate_PTA(merged):
    """Correctly identified templates / total predicted templates."""
    oracle = {}
    result = {}
    for content, pred, gt in merged:
        oracle.setdefault(gt,   []).append(content)
        result.setdefault(pred, []).append(content)
    if not result:
        return 0.0
    correct = sum(
        1 for t, logs in result.items()
        if t in oracle and Counter(oracle[t]) == Counter(logs)
    )
    return correct / len(result)


def evaluate_RTA(merged):
    """Correctly identified templates / total oracle templates."""
    oracle = {}
    result = {}
    for content, pred, gt in merged:
        oracle.setdefault(gt,   []).append(content)
        result.setdefault(pred, []).append(content)
    if not oracle:
        return 0.0
    correct = sum(
        1 for t, logs in oracle.items()
        if t in result and Counter(result[t]) == Counter(logs)
    )
    return correct / len(oracle)


def evaluate_GA(merged, total_rows):
    """
    Logs in correctly grouped clusters / total rows.
    denominator = total_rows when all logs are evaluated (matches paper's /2000).
    denominator = len(merged) for partial evaluations.
    """
    if not merged:
        return 0.0
    denominator = total_rows if len(merged) == total_rows else len(merged)

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
    return count / denominator


# ── per-dataset evaluation ────────────────────────────────────────────────────

def compute_dataset_result(entries, groundtruth, dataset_name):
    merged     = []
    missing_gt = 0
    parse_fail = 0
    for e in entries:
        content  = e.get("content", "")
        template = e.get("log_template", "")
        if e.get("parse_failed"):
            parse_fail += 1
        if content in groundtruth:
            merged.append((content, template, groundtruth[content]))
        else:
            missing_gt += 1

    n          = len(merged)
    total_rows = TOTAL_ROWS_PER_DATASET
    pa  = evaluate_PA(merged)
    pta = evaluate_PTA(merged)
    rta = evaluate_RTA(merged)
    ga  = evaluate_GA(merged, total_rows)

    result = {
        "dataset":        dataset_name,
        "rows_evaluated": n,
        "total_rows":     total_rows,
        "parse_failures": parse_fail,
        "missing_gt":     missing_gt,
        "note": (
            "Full dataset evaluated — directly comparable to paper's Table 2."
            if n == total_rows else
            f"Partial evaluation ({n}/{total_rows} rows). "
            "PA is reliable on partial data. "
            "PTA/RTA/GA require full dataset for reliable comparison with paper."
        ),
        "metrics": {
            "PA":  round(pa,  6),
            "PTA": round(pta, 6),
            "RTA": round(rta, 6),
            "GA":  round(ga,  6),
        },
        "metrics_pct": {
            "PA":  round(pa  * 100, 1),
            "PTA": round(pta * 100, 1),
            "RTA": round(rta * 100, 1),
            "GA":  round(ga  * 100, 1),
        },
    }
    if dataset_name in PAPER_RESULTS:
        result["paper_results"] = PAPER_RESULTS[dataset_name]

    return result, merged


# ── aggregate ─────────────────────────────────────────────────────────────────

def compute_aggregate(per_dataset_results):
    """Weighted mean of metrics across all evaluated datasets."""
    total_n = sum(r["rows_evaluated"] for r in per_dataset_results)
    if total_n == 0:
        return {m: 0.0 for m in ("PA", "PTA", "RTA", "GA")}
    return {
        m: round(
            sum(r["metrics"][m] * r["rows_evaluated"] for r in per_dataset_results) / total_n,
            6,
        )
        for m in ("PA", "PTA", "RTA", "GA")
    }


# ── main ──────────────────────────────────────────────────────────────────────

def sort_output_files():
    """Rewrite outputs_A.jsonl and outputs_B.jsonl sorted by line_id in place."""
    for letter in PROMPTS:
        aggregate = OUTPUT_DIR / f"outputs_{letter}.jsonl"
        paths = [aggregate] if aggregate.exists() else sorted(OUTPUT_DIR.glob(f"*_outputs_{letter}.jsonl"))
        for path in paths:
            entries = _read_jsonl(path)
            if not entries:
                continue
            entries.sort(key=lambda e: int(e.get("line_id", 0)))
            path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
            print(f"[sort] {path.name}: {len(entries)} entries sorted by line_id.")


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sort_output_files()

    for letter in PROMPTS:
        all_entries = load_outputs(letter)
        if not all_entries:
            print(f"[!] No output found for Prompt {letter}. Skipping.")
            continue

        by_dataset = {}
        for e in all_entries:
            ds = e.get("dataset", "unknown")
            by_dataset.setdefault(ds, []).append(e)
        for ds in by_dataset:
            by_dataset[ds].sort(key=lambda e: int(e.get("line_id", 0)))

        print(f"\nPrompt {letter}: {len(all_entries)} entries across "
              f"{len(by_dataset)} dataset(s): {sorted(by_dataset)}")

        per_dataset_results = []

        for dataset_name in sorted(by_dataset):
            groundtruth = load_groundtruth(dataset_name)
            if not groundtruth:
                continue

            entries = by_dataset[dataset_name]
            result, _ = compute_dataset_result(entries, groundtruth, dataset_name)
            per_dataset_results.append(result)

            print(f"\n  {dataset_name}  ({result['rows_evaluated']}/{result['total_rows']} rows)")
            print(f"    PA={result['metrics_pct']['PA']}%  "
                  f"PTA={result['metrics_pct']['PTA']}%  "
                  f"RTA={result['metrics_pct']['RTA']}%  "
                  f"GA={result['metrics_pct']['GA']}%")
            if result.get("parse_failures"):
                print(f"    parse_failures={result['parse_failures']}")
            if result.get("missing_gt"):
                print(f"    missing_gt={result['missing_gt']}")
            if "paper_results" in result:
                p = result["paper_results"]
                wo = p["w/o_inferlog"]
                wi = p["w_inferlog"]
                print(f"    Paper w/o InferLog:  "
                      f"PA={wo['PA']}  PTA={wo['PTA']}  RTA={wo['RTA']}  GA={wo['GA']}")
                print(f"    Paper w/  InferLog:  "
                      f"PA={wi['PA']}  PTA={wi['PTA']}  RTA={wi['RTA']}  GA={wi['GA']}")

        if not per_dataset_results:
            continue

        agg_metrics = compute_aggregate(per_dataset_results)
        total_n     = sum(r["rows_evaluated"] for r in per_dataset_results)
        aggregate   = {
            "type":                 "aggregate",
            "datasets_evaluated":   sorted(by_dataset.keys()),
            "total_rows_evaluated": total_n,
            "metrics":              agg_metrics,
            "metrics_pct":          {k: round(v * 100, 1) for k, v in agg_metrics.items()},
        }

        results_path = RESULTS_DIR / f"results_{letter}.jsonl"
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for r in per_dataset_results:
                f.write(json.dumps(r) + "\n")

        print(f"\n  Aggregate: PA={aggregate['metrics_pct']['PA']}%  "
              f"PTA={aggregate['metrics_pct']['PTA']}%  "
              f"RTA={aggregate['metrics_pct']['RTA']}%  "
              f"GA={aggregate['metrics_pct']['GA']}%")
        print(f"  Saved: {results_path}")

    print()


if __name__ == "__main__":
    main()
