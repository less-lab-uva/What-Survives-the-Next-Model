#!/usr/bin/env python3
"""
Evaluates RQ3 results for Prompt A and Prompt B.

Reads:
  data/outputs/outputs_A.jsonl
  data/outputs/outputs_B.jsonl

Ground truth oracle:
  data/ground_truth/{project}/{pr_number}.json
  A PR is "unintended" if ANY of its test cases has label "unintended",
  otherwise "intended". ("coincidental fix" counts as "intended".)

Writes:
  data/outputs/results_A.jsonl
  data/outputs/results_B.jsonl

Each results file has:
  Line 1 : aggregated metrics (precision, recall, F1, counts)
  Line 2+: one record per PR that appears in both the output and ground truth
"""

import json
import os

TESTORA_ROOT   = os.path.dirname(os.path.abspath(__file__))
GT_DIR         = os.path.join(TESTORA_ROOT, "data", "ground_truth")
OUTPUT_DIR     = os.path.join(TESTORA_ROOT, "outputs")
RESULTS_FOLDER = os.path.join(TESTORA_ROOT, "results")


# ── ground truth ──────────────────────────────────────────────────────────────

def load_ground_truth() -> dict:
    """
    Returns {(project, pr_number): "intended"/"unintended"}.
    A PR is "unintended" if any test case label is "unintended".
    """
    gt = {}
    for project in os.listdir(GT_DIR):
        proj_dir = os.path.join(GT_DIR, project)
        if not os.path.isdir(proj_dir):
            continue
        for fname in os.listdir(proj_dir):
            if not fname.endswith(".json"):
                continue
            pr_nb = int(fname.replace(".json", ""))
            with open(os.path.join(proj_dir, fname), encoding="utf-8") as f:
                data = json.load(f)
            labels = [t["label"] for t in data.get("differentiating_tests", [])]
            verdict = "unintended" if "unintended" in labels else "intended"
            gt[(project, pr_nb)] = verdict
    return gt


# ── metrics ───────────────────────────────────────────────────────────────────

def _prf(tp: int, fp: int, fn: int) -> tuple:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return round(precision, 4), round(recall, 4), round(f1, 4)


def compute_metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    total = tp + fp + fn + tn

    # "intended" is positive class
    p_i, r_i, f1_i = _prf(tn, fn, fp)

    accuracy = round((tp + tn) / total, 4) if total > 0 else 0.0

    return {
        "precision":       p_i,
        "recall":          r_i,
        "f1":              f1_i,
        "accuracy":        accuracy,
        "tp":  tp,
        "fp":  fp,
        "fn":  fn,
        "tn":  tn,
        "total_evaluated": total,
    }


# ── evaluate one output file ──────────────────────────────────────────────────

def evaluate(prompt_letter: str, gt: dict) -> None:
    input_path  = os.path.join(OUTPUT_DIR, f"outputs_{prompt_letter}.jsonl")
    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    output_path = os.path.join(RESULTS_FOLDER, f"results_{prompt_letter}.jsonl")

    if not os.path.exists(input_path):
        print(f"[!] {input_path} not found, skipping prompt {prompt_letter}.")
        return

    with open(input_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    tp = fp = fn = tn = 0
    pr_results = []
    skipped = 0

    for rec in records:
        project  = rec.get("project", "")
        pr_nb    = rec.get("pr_number")
        opus_verdict = (rec.get("verdict") or "").strip().lower()

        key = (project, pr_nb)
        if key not in gt:
            skipped += 1
            continue

        gt_verdict = gt[key]

        # normalise opus verdict to binary
        if "unintended" in opus_verdict:
            opus_binary = "unintended"
        else:
            opus_binary = "intended"

        correct = (opus_binary == gt_verdict)

        if gt_verdict == "unintended" and opus_binary == "unintended":
            tp += 1; conf = "TP"
        elif gt_verdict == "intended"  and opus_binary == "unintended":
            fp += 1; conf = "FP"
        elif gt_verdict == "unintended" and opus_binary == "intended":
            fn += 1; conf = "FN"
        else:
            tn += 1; conf = "TN"

        pr_results.append({
            "pr_number":       pr_nb,
            "project":         project,
            "gt_verdict":      gt_verdict,
            "opus_verdict":    opus_binary,
            "correct":         correct,
            "confusion":       conf,
            "test_case":       rec.get("test_case", ""),
            "predicted_output_before_pr": rec.get("predicted_output_before_pr", ""),
            "predicted_output_after_pr":  rec.get("predicted_output_after_pr", ""),
            "explanation":     rec.get("explanation", ""),
            "timestamp":       rec.get("timestamp", ""),
        })

    metrics = compute_metrics(tp, fp, fn, tn)
    metrics["skipped_no_ground_truth"] = skipped

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(metrics) + "\n")
        for pr in pr_results:
            f.write(json.dumps(pr) + "\n")

    print(f"\n=== Prompt {prompt_letter} ===")
    print(f"  Evaluated : {metrics['total_evaluated']} PRs  "
          f"(skipped {skipped} with no ground truth)")
    print(f"  Accuracy  : {metrics['accuracy']:.4f}")
    print(f"  Precision : {metrics['precision']:.4f}")
    print(f"  Recall    : {metrics['recall']:.4f}")
    print(f"  F1        : {metrics['f1']:.4f}")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Results saved to: {output_path}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    gt = load_ground_truth()
    print(f"[*] Ground truth loaded: {len(gt)} PRs")
    print(f"    Unintended: {sum(1 for v in gt.values() if v == 'unintended')}")
    print(f"    Intended:   {sum(1 for v in gt.values() if v == 'intended')}")

    for letter in ["A", "B"]:
        evaluate(letter, gt)


if __name__ == "__main__":
    main()
