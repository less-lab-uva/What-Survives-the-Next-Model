#!/usr/bin/env python3
"""
Analyzes LLM vulnerability detection results against D2 ground truth labels.
Writes results/results_A.jsonl and results/results_B.jsonl.

Usage:
    python3 evaluator.py
"""

import json
import os
import re

OUTPUT_FOLDER  = os.path.join(os.path.dirname(__file__), "output")
RESULTS_FOLDER = os.path.join(os.path.dirname(__file__), "results")
DATASET_D2     = os.path.join(os.path.dirname(__file__), "dataset", "D2")

LABEL_TO_ECHOFUZZ = {
    "REENTRANCY":         {"reentrancy"},
    "UNCHECKED_LL_CALLS": {"unchecked call"},
    "ARITHMETIC":         {"integer overflow", "integer underflow"},
    "TIME_MANIPULATION":  {"timestamp dependency"},
    "BAD_RANDOMNESS":     {"block number dependency"},
}

ALL_CATEGORIES = [
    "gasless",
    "unchecked call",
    "reentrancy",
    "timestamp dependency",
    "block number dependency",
    "dangerous delegatecall",
    "freezing ether",
    "integer overflow",
    "integer underflow",
    "unexpected ether",
]


def extract_labels(sol_path):
    with open(sol_path, "r", encoding="utf-8") as f:
        content = f.read()
    return set(re.findall(r"<report>\s+(\w+)", content))


def get_expected_categories(labels):
    expected = set()
    for label in labels:
        expected |= LABEL_TO_ECHOFUZZ.get(label, set())
    return expected


def analyze_prompt(prompt_letter):
    results = []
    for fname in sorted(os.listdir(OUTPUT_FOLDER)):
        if not fname.endswith(f"_prompt{prompt_letter}.json"):
            continue
        if fname.startswith("tokens_") or fname.startswith("analysis_"):
            continue

        stem     = fname.replace(f"_prompt{prompt_letter}.json", "")
        sol_path = os.path.join(DATASET_D2, f"{stem}.sol")
        if not os.path.exists(sol_path):
            continue

        labels   = extract_labels(sol_path)
        expected = get_expected_categories(labels)

        with open(os.path.join(OUTPUT_FOLDER, fname), "r", encoding="utf-8") as f:
            llm_output = json.load(f)

        vulnerabilities = llm_output.get("vulnerabilities", {})
        detected = {
            cat for cat in ALL_CATEGORIES
            if vulnerabilities.get(cat, {}).get("number", 0) > 0
        }

        tp = detected & expected
        fp = detected - expected
        fn = expected - detected

        results.append({
            "contract":            stem,
            "ground_truth_labels": sorted(labels),
            "expected_categories": sorted(expected),
            "detected_categories": sorted(detected),
            "true_positives":      sorted(tp),
            "false_positives":     sorted(fp),
            "false_negatives":     sorted(fn),
        })

    return results


def build_per_category_stats(results):
    stats = {}
    for cat in ALL_CATEGORIES:
        gt_count = sum(1 for r in results if cat in r["expected_categories"])
        detected = sum(1 for r in results if cat in r["detected_categories"])
        tp       = sum(1 for r in results if cat in r["true_positives"])
        fp       = sum(1 for r in results if cat in r["false_positives"])
        fn       = sum(1 for r in results if cat in r["false_negatives"])
        stats[cat] = {
            "ground_truth_count": gt_count,
            "detected":           detected,
            "true_positives":     tp,
            "false_positives":    fp,
            "false_negatives":    fn,
        }
    return stats


def write_results(prompt_letter, results):
    total_gt       = sum(len(r["expected_categories"]) for r in results)
    total_detected = sum(len(r["detected_categories"]) for r in results)
    total_tp       = sum(len(r["true_positives"])      for r in results)
    total_fp       = sum(len(r["false_positives"])     for r in results)
    total_fn       = sum(len(r["false_negatives"])     for r in results)

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall    = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0

    per_category = build_per_category_stats(results)

    aggregate = {
        "prompt":      prompt_letter,
        "samples_ran": len(results),
        "summary": {
            "total_ground_truth_vulnerabilities": total_gt,
            "total_vulnerabilities_detected":     total_detected,
            "true_positives":                     total_tp,
            "false_positives":                    total_fp,
            "false_negatives":                    total_fn,
            "precision":                          round(precision, 4),
            "recall":                             round(recall, 4),
        },
        "per_vulnerability": per_category,
    }

    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    out_path = os.path.join(RESULTS_FOLDER, f"results_{prompt_letter}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(aggregate) + "\n")
        for entry in results:
            f.write(json.dumps(entry) + "\n")

    print(f"\n[Prompt {prompt_letter}] → {out_path}")
    print(f"  Samples ran                          : {len(results)}")
    print(f"  Total ground truth vulnerabilities   : {total_gt}")
    print(f"  Total vulnerabilities detected        : {total_detected}")
    print(f"  True positives                        : {total_tp}")
    print(f"  False positives                       : {total_fp}")
    print(f"  False negatives                       : {total_fn}")
    print(f"  Precision                             : {precision:.2%}")
    print(f"  Recall                                : {recall:.2%}")
    print(f"\n  {'Vulnerability':<30} {'GT':>4} {'Det':>4} {'TP':>4} {'FP':>4} {'FN':>4}")
    print(f"  {'-'*50}")
    for cat, s in per_category.items():
        print(f"  {cat:<30} {s['ground_truth_count']:>4} {s['detected']:>4} "
              f"{s['true_positives']:>4} {s['false_positives']:>4} {s['false_negatives']:>4}")


def main():
    for letter in ["A", "B"]:
        results = analyze_prompt(letter)
        if not results:
            print(f"[Prompt {letter}] No results found in {OUTPUT_FOLDER}")
            continue
        write_results(letter, results)


if __name__ == "__main__":
    main()
