#!/usr/bin/env python3
"""
Compute Precision, Recall, and F1-score for each prompt's output against the
manually verified ground truth labels, matching the evaluation methodology of
the paper (RQ2). Results are saved to the output folder.

Usage:
    python3 evaluate.py
"""

import json
import os
from datetime import datetime

LASIR_ROOT     = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER  = os.path.join(LASIR_ROOT, "output")
RESULTS_FOLDER = os.path.join(LASIR_ROOT, "results")
PROMPTS        = ["A", "B"]

# Paper's reported numbers for reference
PAPER_RESULTS = {
    "TP": 69, "FP": 15, "TN": 413, "FN": 3,
    "Precision": 0.8214, "Recall": 0.9583, "F1": 0.8846,
}


def evaluate_prompt(prompt_letter: str) -> dict:
    path = os.path.join(OUTPUT_FOLDER, f"RQ2_prompt{prompt_letter}.json")
    if not os.path.exists(path):
        print(f"[!] Not found: {path}")
        return {}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    TP = FP = TN = FN = 0
    per_contract = []

    for contract_id, record in data.items():
        gt      = record["label"]           # "positive" or "negative"
        pred    = record["Exist"]           # True or False
        gt_bool = (gt == "positive")

        if pred and gt_bool:
            outcome = "TP"
            TP += 1
        elif pred and not gt_bool:
            outcome = "FP"
            FP += 1
        elif not pred and gt_bool:
            outcome = "FN"
            FN += 1
        else:
            outcome = "TN"
            TN += 1

        per_contract.append({
            "contract_id": contract_id,
            "ground_truth": gt,
            "predicted_exist": pred,
            "predicted_vuln_type": record.get("Vuln_type", []),
            "outcome": outcome,
        })

    total     = TP + FP + TN + FN
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    recall    = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    accuracy  = (TP + TN) / total if total > 0 else 0.0

    return {
        "prompt":    prompt_letter,
        "dataset":   "RQ2",
        "evaluated": total,
        "confusion_matrix": {
            "TP": TP, "FP": FP, "TN": TN, "FN": FN,
        },
        "metrics": {
            "Precision": round(precision, 4),
            "Recall":    round(recall,    4),
            "F1":        round(f1,        4),
            "Accuracy":  round(accuracy,  4),
        },
        "paper_reference": PAPER_RESULTS,
        "per_contract": per_contract,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def print_summary(result: dict) -> None:
    p = result["prompt"]
    cm = result["confusion_matrix"]
    m  = result["metrics"]
    ref = result["paper_reference"]

    print(f"\n{'─'*52}")
    print(f"  Prompt {p}  |  {result['evaluated']} contracts evaluated")
    print(f"{'─'*52}")
    print(f"  {'':20s}  {'Predicted +':>11}  {'Predicted -':>11}")
    print(f"  {'Actual +  (positive)':20s}  {'TP='+str(cm['TP']):>11}  {'FN='+str(cm['FN']):>11}")
    print(f"  {'Actual -  (negative)':20s}  {'FP='+str(cm['FP']):>11}  {'TN='+str(cm['TN']):>11}")
    print(f"{'─'*52}")
    print(f"  {'Metric':<14}  {'Ours':>8}  {'Paper':>8}")
    print(f"  {'Precision':<14}  {m['Precision']:>8.4f}  {ref['Precision']:>8.4f}")
    print(f"  {'Recall':<14}  {m['Recall']:>8.4f}  {ref['Recall']:>8.4f}")
    print(f"  {'F1-score':<14}  {m['F1']:>8.4f}  {ref['F1']:>8.4f}")
    print(f"  {'Accuracy':<14}  {m['Accuracy']:>8.4f}  {'N/A':>8}")
    print(f"{'─'*52}")

    fps = [c for c in result["per_contract"] if c["outcome"] == "FP"]
    fns = [c for c in result["per_contract"] if c["outcome"] == "FN"]
    if fps:
        print(f"  False Positives ({len(fps)}):")
        for c in fps:
            print(f"    {c['contract_id']}  vuln={c['predicted_vuln_type']}")
    if fns:
        print(f"  False Negatives ({len(fns)}):")
        for c in fns:
            print(f"    {c['contract_id']}")


def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(RESULTS_FOLDER, exist_ok=True)

    for letter in PROMPTS:
        result = evaluate_prompt(letter)
        if not result:
            continue
        print_summary(result)

        out_path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
        aggregate = {k: v for k, v in result.items() if k != "per_contract"}
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for entry in result["per_contract"]:
                f.write(json.dumps(entry) + "\n")
        print(f"\n  [+] Saved → {out_path}")


if __name__ == "__main__":
    main()
