#!/usr/bin/env python3
"""
Usage:
    python3 evaluator.py
"""

import csv
import json
import re
from pathlib import Path

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "outputs"
RESULTS_DIR = BASE_DIR / "results"
GT_DIR      = BASE_DIR / ".." / "data" / "ground_truth"
RQ1_CSV     = BASE_DIR / ".." / "data" / "real-world_problems.csv"

PROMPTS = ["A", "B"]

# ---------------------------------------------------------------------------
# Paper reference results
# ---------------------------------------------------------------------------
PAPER_RQ3 = {
    "precision": 0.55,
    "recall":    0.67,
    "f1":        0.60,
    "note": "Table 1, GPT-4o-mini multi-question, full 46-PR eval set",
}
PAPER_RQ1 = {
    "total_paper":      30,
    "detected_paper":   30,   # all 30 listed PRs were found by original pipeline
    "recall_paper":     1.00,
    "reported":         13,
    "confirmed":        12,
    "fixed":            11,
    "note": "Table 2; original pipeline found all 30; 13 reported to developers",
}


# ---------------------------------------------------------------------------
# Ground truth for RQ3 (data/ground_truth/)
# ---------------------------------------------------------------------------

def load_rq3_ground_truth() -> dict:
    """Return {(project, pr_number): "intended"|"unintended"} for all 46 GT PRs."""
    gt = {}
    for project_dir in GT_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        project = project_dir.name
        for fname in project_dir.iterdir():
            if fname.suffix != ".json":
                continue
            pr_nb = int(fname.stem)
            with open(fname, encoding="utf-8") as f:
                data = json.load(f)
            labels = [t["label"] for t in data.get("differentiating_tests", [])]
            verdict = (
                "unintended"
                if any(l in ("unintended", "coincidental fix") for l in labels)
                else "intended"
            )
            gt[(project, pr_nb)] = verdict
    return gt


# ---------------------------------------------------------------------------
# Ground truth for RQ1 (real-world_problems.csv)
# ---------------------------------------------------------------------------

def load_rq1_registry() -> dict:
    """
    Return {(project, pr_number): "unintended"} for all 30 CSV entries.
    All RQ1 PRs are unintended (Regression or Coincidental fix).
    Also returns total paper count (30) and available count.
    """
    registry = {}
    with open(RQ1_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pr_url = row.get("PR", "").strip().rstrip("/")
            proj   = row.get("Project", "").strip().lower()
            if not pr_url or not proj:
                continue
            m = re.search(r"/pull/(\d+)", pr_url)
            if not m:
                continue
            pr_nb = int(m.group(1))
            registry[(proj, pr_nb)] = "unintended"
    return registry


# ---------------------------------------------------------------------------
# Output loading — JSONL + per-PR JSON files
# ---------------------------------------------------------------------------

def load_outputs(letter: str) -> list:
    records = []
    seen    = set()  # tracks ALL keys seen, including skipped/parse_failed

    jsonl_path = OUTPUT_DIR / f"outputs_{letter}.jsonl"
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r   = json.loads(line)
                key = (r.get("project"), r.get("pr_number"))
                if key not in seen:
                    seen.add(key)
                    if not r.get("skipped") and not r.get("parse_failed"):
                        records.append(r)
            except json.JSONDecodeError:
                pass

    for p in sorted(OUTPUT_DIR.glob(f"*_prompt{letter}.json")):
        try:
            r   = json.loads(p.read_text(encoding="utf-8"))
            key = (r.get("project"), r.get("pr_number"))
            if key not in seen:
                seen.add(key)
                if not r.get("skipped") and not r.get("parse_failed"):
                    records.append(r)
        except (json.JSONDecodeError, OSError):
            pass

    return records


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _prf(tp: int, fp: int, fn: int) -> tuple:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _llm_verdict(raw: str) -> str:
    return "unintended" if "unintended" in (raw or "").strip().lower() else "intended"


# ---------------------------------------------------------------------------
# RQ3 evaluation
# ---------------------------------------------------------------------------

def evaluate_rq3(records: list, gt: dict) -> tuple:
    """
    Compute classification metrics for RQ3 records against data/ground_truth/.
    Returns (metrics_dict, per_pr_list, skipped_count).
    """
    tp = fp = fn = tn = skipped = 0
    per_pr = []

    for rec in records:
        key = (rec.get("project"), rec.get("pr_number"))
        if key not in gt:
            skipped += 1
            continue

        gt_verdict  = gt[key]
        llm         = _llm_verdict(rec.get("verdict", ""))
        correct     = llm == gt_verdict

        if   gt_verdict == "unintended" and llm == "unintended": tp += 1; conf = "TP"
        elif gt_verdict == "intended"   and llm == "unintended": fp += 1; conf = "FP"
        elif gt_verdict == "unintended" and llm == "intended":   fn += 1; conf = "FN"
        else:                                                     tn += 1; conf = "TN"

        per_pr.append({
            "dataset":                    "rq3",
            "pr_number":                  rec.get("pr_number"),
            "project":                    rec.get("project"),
            "gt_verdict":                 gt_verdict,
            "llm_verdict":                llm,
            "correct":                    correct,
            "confusion":                  conf,
            "test_case":                  rec.get("test_case", ""),
            "predicted_output_before_pr": rec.get("predicted_output_before_pr", ""),
            "predicted_output_after_pr":  rec.get("predicted_output_after_pr", ""),
            "explanation":                rec.get("explanation", ""),
            "timestamp":                  rec.get("timestamp", ""),
        })

    total    = tp + fp + fn + tn
    p, r, f1 = _prf(tp, fp, fn)
    accuracy = round((tp + tn) / total, 4) if total > 0 else 0.0

    metrics = {
        "type":              "rq3_aggregate",
        "total_evaluated":   total,
        "skipped_no_gt":     skipped,
        "precision":         p,
        "recall":            r,
        "f1":                f1,
        "accuracy":          accuracy,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "paper_rq3_precision": PAPER_RQ3["precision"],
        "paper_rq3_recall":    PAPER_RQ3["recall"],
        "paper_rq3_f1":        PAPER_RQ3["f1"],
        "paper_rq3_note":      PAPER_RQ3["note"],
    }
    return metrics, per_pr, skipped


# ---------------------------------------------------------------------------
# RQ1 evaluation
# ---------------------------------------------------------------------------

def evaluate_rq1(records: list, rq1_gt: dict) -> tuple:
    """
    Compute detection rate for RQ1 records.
    All RQ1 PRs are unintended; we measure recall = detected / available.
    Returns (metrics_dict, per_pr_list, skipped_count).
    """
    detected = not_detected = skipped = 0
    per_pr = []

    for rec in records:
        key = (rec.get("project"), rec.get("pr_number"))
        if key not in rq1_gt:
            skipped += 1
            continue

        llm     = _llm_verdict(rec.get("verdict", ""))
        correct = llm == "unintended"

        if llm == "unintended":
            detected += 1
        else:
            not_detected += 1

        per_pr.append({
            "dataset":                    "rq1",
            "pr_number":                  rec.get("pr_number"),
            "project":                    rec.get("project"),
            "gt_verdict":                 "unintended",
            "llm_verdict":                llm,
            "correct":                    correct,
            "confusion":                  "TP" if correct else "FN",
            "test_case":                  rec.get("test_case", ""),
            "predicted_output_before_pr": rec.get("predicted_output_before_pr", ""),
            "predicted_output_after_pr":  rec.get("predicted_output_after_pr", ""),
            "explanation":                rec.get("explanation", ""),
            "timestamp":                  rec.get("timestamp", ""),
        })

    available  = detected + not_detected
    recall     = round(detected / available, 4) if available > 0 else 0.0
    precision  = 1.0 if detected > 0 else 0.0  # all GT is unintended; no FP possible
    f1         = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    metrics = {
        "type":                  "rq1_aggregate",
        "total_available_us":    available,
        "total_paper":           PAPER_RQ1["total_paper"],
        "coverage":              f"{available}/{PAPER_RQ1['total_paper']}",
        "detected_unintended":   detected,
        "not_detected":          not_detected,
        "skipped_not_in_csv":    skipped,
        "recall":                recall,
        "precision":             precision,
        "f1":                    f1,
        "paper_rq1_detected":    PAPER_RQ1["detected_paper"],
        "paper_rq1_recall":      PAPER_RQ1["recall_paper"],
        "paper_rq1_reported":    PAPER_RQ1["reported"],
        "paper_rq1_confirmed":   PAPER_RQ1["confirmed"],
        "paper_rq1_fixed":       PAPER_RQ1["fixed"],
        "paper_rq1_note":        PAPER_RQ1["note"],
    }
    return metrics, per_pr, skipped


# ---------------------------------------------------------------------------
# Main evaluate function
# ---------------------------------------------------------------------------

def evaluate(letter: str, rq3_gt: dict, rq1_gt: dict) -> None:
    records = load_outputs(letter)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"results_{letter}.jsonl"

    if not records:
        print(f"[!] No output records for prompt {letter}. Skipping.")
        return

    # Split by dataset membership.
    # Handles both new "datasets": [...] list and old "dataset": string field.
    def get_datasets(r):
        ds = r.get("datasets")
        if isinstance(ds, list):
            return ds
        single = r.get("dataset", "rq3")
        return [single] if single else ["rq3"]

    rq3_records = [r for r in records if "rq3" in get_datasets(r)]
    rq1_records = [r for r in records if "rq1" in get_datasets(r)]

    aggregate_lines = []
    per_pr_lines    = []

    if rq3_records:
        rq3_metrics, rq3_per_pr, rq3_skip = evaluate_rq3(rq3_records, rq3_gt)
        aggregate_lines.append(rq3_metrics)
        per_pr_lines.extend(rq3_per_pr)

    if rq1_records:
        rq1_metrics, rq1_per_pr, rq1_skip = evaluate_rq1(rq1_records, rq1_gt)
        aggregate_lines.append(rq1_metrics)
        per_pr_lines.extend(rq1_per_pr)

    if not aggregate_lines:
        print(f"[!] Prompt {letter}: no records matched RQ3 ground truth or RQ1 registry.")
        return

    with open(out_path, "w", encoding="utf-8") as f:
        for agg in aggregate_lines:
            f.write(json.dumps(agg) + "\n")
        for pr in per_pr_lines:
            f.write(json.dumps(pr) + "\n")

    # --- Print summary ---
    print(f"\n=== Prompt {letter} ===")

    if rq3_records:
        m = aggregate_lines[0]
        print(f"\n  [RQ3 — {m['total_evaluated']} PRs evaluated, {m['skipped_no_gt']} skipped]")
        print(f"    Accuracy  : {m['accuracy']:.4f}")
        print(f"    Precision : {m['precision']:.4f}  (paper: {m['paper_rq3_precision']})")
        print(f"    Recall    : {m['recall']:.4f}  (paper: {m['paper_rq3_recall']})")
        print(f"    F1        : {m['f1']:.4f}  (paper: {m['paper_rq3_f1']})")
        print(f"    TP={m['tp']}  FP={m['fp']}  FN={m['fn']}  TN={m['tn']}")
        print(f"    Paper note: {m['paper_rq3_note']}")

    if rq1_records:
        m = [a for a in aggregate_lines if a["type"] == "rq1_aggregate"][0]
        print(f"\n  [RQ1 — {m['total_available_us']} PRs evaluated ({m['coverage']} paper coverage)]")
        print(f"    Detected as unintended : {m['detected_unintended']}/{m['total_available_us']}  (paper: {m['paper_rq1_detected']}/{m['total_paper']})")
        print(f"    Recall                 : {m['recall']:.4f}  (paper: {m['paper_rq1_recall']:.2f})")
        print(f"    F1                     : {m['f1']:.4f}")
        print(f"    Paper downstream       : {m['paper_rq1_reported']} reported / {m['paper_rq1_confirmed']} confirmed / {m['paper_rq1_fixed']} fixed")
        print(f"    Note: {m['paper_rq1_note']}")

    print(f"\n  Results saved to: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rq3_gt = load_rq3_ground_truth()
    rq1_gt = load_rq1_registry()

    n_unintended = sum(1 for v in rq3_gt.values() if v == "unintended")
    n_intended   = len(rq3_gt) - n_unintended

    print(f"[*] RQ3 ground truth: {len(rq3_gt)} PRs  "
          f"({n_unintended} unintended / {n_intended} intended)")
    print(f"[*] RQ1 registry: {len(rq1_gt)} PRs (all unintended)")

    for letter in PROMPTS:
        evaluate(letter, rq3_gt, rq1_gt)


if __name__ == "__main__":
    main()
