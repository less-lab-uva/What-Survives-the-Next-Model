#!/usr/bin/env python3
"""
Evaluates LASIR with_sonnet output against ground-truth labels.

RQ2: Binary signature replay vulnerability detection (Exist: True/False).
     Computes Precision, Recall, F1 from TP/FP/TN/FN.
     Reads from both outputs/outputs_{A,B}.jsonl and separate
     outputs/<safe_contract_id>_prompt{letter}.json files.

Usage:
    python3 evaluator.py
"""

import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "outputs"
RESULTS_DIR = BASE_DIR / "results"

PROMPTS = ["A", "B"]

PAPER_RESULTS = {
    "TP": 69, "FP": 15, "TN": 413, "FN": 3,
    "Precision": 0.8214, "Recall": 0.9583, "F1": 0.8846,
}


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)


def load_all_outputs(letter: str) -> dict:
    """Return {contract_id: record} for all evaluable entries for prompt letter.

    Skips entries with skipped=True or parse_failed=True.
    Separate files take precedence; JSONL may update them if it has a valid record.
    """
    records = {}

    # Separate files: <safe_contract_id>_prompt<letter>.json
    for path in OUTPUT_DIR.glob(f"*_prompt{letter}.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            cid = rec.get("contract_id")
            if cid and rec.get("Exist") is not None:
                records[cid] = rec
        except (json.JSONDecodeError, OSError):
            continue

    # JSONL
    jpath = OUTPUT_DIR / f"outputs_{letter}.jsonl"
    if jpath.exists():
        try:
            for line in jpath.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                cid = rec.get("contract_id")
                if (cid
                        and not rec.get("skipped")
                        and not rec.get("parse_failed")
                        and rec.get("Exist") is not None):
                    records[cid] = rec
        except (json.JSONDecodeError, OSError):
            pass

    return records


def evaluate_prompt(letter: str) -> dict:
    records = load_all_outputs(letter)
    if not records:
        print(f"[!] No output found for prompt {letter}.")
        return {}

    TP = FP = TN = FN = 0
    per_contract = []

    for contract_id, rec in records.items():
        gt      = rec.get("label", "")
        pred    = bool(rec.get("Exist", False))
        gt_bool = (gt == "positive")

        if pred and gt_bool:
            outcome = "TP"; TP += 1
        elif pred and not gt_bool:
            outcome = "FP"; FP += 1
        elif not pred and gt_bool:
            outcome = "FN"; FN += 1
        else:
            outcome = "TN"; TN += 1

        per_contract.append({
            "contract_id":         contract_id,
            "ground_truth":        gt,
            "predicted_exist":     pred,
            "predicted_vuln_type": rec.get("Vuln_type", []),
            "outcome":             outcome,
        })

    total     = TP + FP + TN + FN
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    recall    = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    accuracy  = (TP + TN) / total if total > 0 else 0.0

    return {
        "prompt":    letter,
        "dataset":   "RQ2",
        "evaluated": total,
        "confusion_matrix": {"TP": TP, "FP": FP, "TN": TN, "FN": FN},
        "metrics": {
            "Precision": round(precision, 4),
            "Recall":    round(recall,    4),
            "F1":        round(f1,        4),
            "Accuracy":  round(accuracy,  4),
        },
        "paper_reference": PAPER_RESULTS,
        "per_contract":    per_contract,
        "timestamp":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def print_summary(result: dict) -> None:
    p   = result["prompt"]
    cm  = result["confusion_matrix"]
    m   = result["metrics"]
    ref = result["paper_reference"]

    print(f"\n{'─'*52}")
    print(f"  Prompt {p}  |  {result['evaluated']} contracts evaluated")
    print(f"{'─'*52}")
    print(f"  {'':22s}  {'Predicted +':>10}  {'Predicted -':>10}")
    print(f"  {'Actual + (positive)':22s}  {'TP='+str(cm['TP']):>10}  {'FN='+str(cm['FN']):>10}")
    print(f"  {'Actual - (negative)':22s}  {'FP='+str(cm['FP']):>10}  {'TN='+str(cm['TN']):>10}")
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
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for letter in PROMPTS:
        result = evaluate_prompt(letter)
        if not result:
            continue
        print_summary(result)

        out_path = RESULTS_DIR / f"results_{letter}.jsonl"
        aggregate = {k: v for k, v in result.items() if k != "per_contract"}
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for entry in result["per_contract"]:
                f.write(json.dumps(entry) + "\n")
        print(f"\n  [+] Saved → {out_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
