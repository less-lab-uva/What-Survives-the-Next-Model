#!/usr/bin/env python3
"""
Evaluates the new LLM pipeline (claude-sonnet-4-6) against D2 ground-truth labels.
Also reports EchoFuzz paper Table 3 D2 detection counts as a reference.

Reads   : outputs/outputs_A.jsonl  (new pipeline, prompt A)
          outputs/outputs_B.jsonl  (new pipeline, prompt B)
          dataset/D2/{stem}.sol    (ground-truth labels via <report> annotations)

Writes  : results/results_A.jsonl
          results/results_B.jsonl

Each result JSONL:
  line 1  — aggregate: new pipeline metrics + paper Table 3 D2 reference block
  line 2+ — per-contract breakdown (new pipeline only)

Paper reference (Table 3, D2 EchoFuzz, all 143 D2 contracts, 5 mapped categories):
  IO=53  RE=20  UC=15  BN=8  TP=7  (total=103)

  GL/DG/UE omitted: D2 has no ground-truth labels for those categories.
  EchoFuzz uses a runtime oracle → zero false positives by design.
  Per-contract paper results are not published; only these aggregate totals exist.

D2 label → paper category mapping:
  REENTRANCY         → RE
  UNCHECKED_LL_CALLS → UC
  ARITHMETIC         → IO  (detected if EITHER integer overflow OR underflow > 0)
  TIME_MANIPULATION  → TP
  TIME               → TP
  BAD_RANDOMNESS     → BN
  ACCESS_CONTROL / FRONT_RUNNING / DENIAL_OF_SERVICE / OTHER / SHORT_ADDRESSES
                     → unmapped; contracts with only these labels have no expected_cats

Usage:
    python3 evaluator.py
"""

import json
import os
import re

_BASE       = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(_BASE, "outputs")
RESULTS_DIR = os.path.join(_BASE, "results")
DATASET_DIR = os.path.join(_BASE, "dataset", "D2")

# ── paper reference ───────────────────────────────────────────────────────────
# EchoFuzz paper Table 3, D2 row, EchoFuzz column — only the 5 categories
# that have D2 ground-truth labels (all 143 D2 contracts).
# GL/DG/UE excluded: D2 has no annotations for those categories.
PAPER_TABLE3_D2_ECHOFUZZ = {
    "IO": 53, "RE": 20, "UC": 15, "BN": 8, "TP": 7,
}  # total = 103

# ── label / category mappings ─────────────────────────────────────────────────
D2_LABEL_TO_PAPER_CAT = {
    "REENTRANCY":         "RE",
    "UNCHECKED_LL_CALLS": "UC",
    "ARITHMETIC":         "IO",
    "TIME_MANIPULATION":  "TP",
    "TIME":               "TP",
    "BAD_RANDOMNESS":     "BN",
}

# Only the 5 categories with D2 ground truth.
# GL ("gasless"), DG ("dangerous delegatecall"), UE ("freezing ether" /
# "unexpected ether") are intentionally omitted — detections in those
# fields are ignored (neither TP nor FP).
PAPER_CAT_TO_ECHOFUZZ = {
    "IO": {"integer overflow", "integer underflow"},
    "RE": {"reentrancy"},
    "UC": {"unchecked call"},
    "BN": {"block number dependency"},
    "TP": {"timestamp dependency"},
}

PAPER_CATEGORIES = ["IO", "RE", "UC", "BN", "TP"]


# ── helpers ───────────────────────────────────────────────────────────────────

def extract_d2_labels(stem: str) -> set:
    path = os.path.join(DATASET_DIR, f"{stem}.sol")
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return set(re.findall(r"<report>\s+(\w+)", content))


def labels_to_paper_cats(labels: set) -> set:
    return {D2_LABEL_TO_PAPER_CAT[lbl] for lbl in labels if lbl in D2_LABEL_TO_PAPER_CAT}


def detected_paper_cats(vuln_dict: dict) -> set:
    """Return paper categories detected (any matching EchoFuzz field has number > 0)."""
    detected = set()
    for cat, fields in PAPER_CAT_TO_ECHOFUZZ.items():
        for field in fields:
            if vuln_dict.get(field, {}).get("number", 0) > 0:
                detected.add(cat)
                break
    return detected


# ── per-prompt evaluation ─────────────────────────────────────────────────────

def evaluate_prompt(letter: str) -> list[dict]:
    jsonl_path = os.path.join(OUTPUTS_DIR, f"outputs_{letter}.jsonl")
    if not os.path.exists(jsonl_path):
        print(f"[Prompt {letter}] {jsonl_path} not found — skipping.")
        return []

    results = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[Prompt {letter}] WARNING line {lineno}: {exc}")
                continue

            stem = entry.get("contract")
            if not stem:
                continue

            d2_labels     = extract_d2_labels(stem)
            expected_cats = labels_to_paper_cats(d2_labels)
            unmapped_d2   = {lbl for lbl in d2_labels if lbl not in D2_LABEL_TO_PAPER_CAT}

            vuln_new = entry.get("vulnerabilities", {})
            if not isinstance(vuln_new, dict):
                print(f"[Prompt {letter}] WARNING {stem}: invalid 'vulnerabilities' field")
                vuln_new = {}

            new_detected = detected_paper_cats(vuln_new)
            new_tp = new_detected & expected_cats
            new_fp = new_detected - expected_cats
            new_fn = expected_cats - new_detected

            results.append({
                "contract":        stem,
                "d2_labels":       sorted(d2_labels),
                "unmapped_labels": sorted(unmapped_d2),
                "expected_cats":   sorted(expected_cats),
                "new_detected":    sorted(new_detected),
                "new_TP":          sorted(new_tp),
                "new_FP":          sorted(new_fp),
                "new_FN":          sorted(new_fn),
            })

    return results


# ── aggregate stats ───────────────────────────────────────────────────────────

def _cat_stats(results: list[dict]) -> tuple[dict, dict]:
    per_cat: dict[str, dict] = {}
    for cat in PAPER_CATEGORIES:
        per_cat[cat] = {"ground_truth": 0, "detected": 0, "TP": 0, "FP": 0, "FN": 0}

    for r in results:
        for cat in PAPER_CATEGORIES:
            per_cat[cat]["ground_truth"] += int(cat in r["expected_cats"])
            per_cat[cat]["detected"]     += int(cat in r["new_detected"])
            per_cat[cat]["TP"]           += int(cat in r["new_TP"])
            per_cat[cat]["FP"]           += int(cat in r["new_FP"])
            per_cat[cat]["FN"]           += int(cat in r["new_FN"])

    total_tp  = sum(c["TP"] for c in per_cat.values())
    total_fp  = sum(c["FP"] for c in per_cat.values())
    total_fn  = sum(c["FN"] for c in per_cat.values())
    total_gt  = sum(c["ground_truth"] for c in per_cat.values())
    total_det = sum(c["detected"] for c in per_cat.values())

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall    = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0

    overall = {
        "total_ground_truth": total_gt,
        "total_detected":     total_det,
        "total_TP":           total_tp,
        "total_FP":           total_fp,
        "total_FN":           total_fn,
        # "precision":          round(precision, 4),
        # "recall":             round(recall, 4),
    }
    return per_cat, overall


def aggregate(results: list[dict], letter: str) -> dict:
    per_cat, overall = _cat_stats(results)
    return {
        "type":              "aggregate",
        "prompt":            letter,
        "samples_evaluated": len(results),
        "new_pipeline": {
            "note":         (
                f"Metrics for the {len(results)}-contract sample "
                "(10% of 143 D2 contracts, randomly selected)."
            ),
            "summary":      overall,
            "per_category": per_cat,
        },
        "paper_reference": {
            "source":       "EchoFuzz paper Table 3, D2 dataset, EchoFuzz column",
            "dataset_size": 143,
            "detections":   PAPER_TABLE3_D2_ECHOFUZZ,
            "total":        sum(PAPER_TABLE3_D2_ECHOFUZZ.values()),
            "note": (
                "EchoFuzz uses a runtime oracle — all detections are true positives, "
                "no false positives possible. Counts are over all 143 D2 contracts. "
                "GL/DG/UE excluded from both paper reference and new-pipeline evaluation "
                "because D2 has no ground-truth labels for those categories."
            ),
        },
    }


# ── output ────────────────────────────────────────────────────────────────────

def _print_new_pipeline(n: int, overall: dict, per_cat: dict) -> None:
    s = overall
    print(f"\n  [New pipeline — {n}-contract sample]")
    print(f"    Ground-truth vulns : {s['total_ground_truth']}")
    print(f"    Detected           : {s['total_detected']}")
    print(f"    True  positives    : {s['total_TP']}")
    print(f"    False positives    : {s['total_FP']}")
    print(f"    False negatives    : {s['total_FN']}")
    # print(f"    Precision          : {s['precision']:.2%}")
    # print(f"    Recall             : {s['recall']:.2%}")
    print(f"    {'Cat':<4} {'GT':>5} {'Det':>5} {'TP':>5} {'FP':>5} {'FN':>5}")
    print(f"    {'-'*30}")
    for cat in PAPER_CATEGORIES:
        c = per_cat[cat]
        print(f"    {cat:<4} {c['ground_truth']:>5} {c['detected']:>5} "
              f"{c['TP']:>5} {c['FP']:>5} {c['FN']:>5}")


def _print_paper_reference(ref: dict) -> None:
    print(f"\n  [Paper reference — EchoFuzz Table 3, D2, all {ref['dataset_size']} contracts]")
    print(f"    Total detected : {ref['total']} vulnerabilities")
    print(f"    (Runtime oracle; zero false positives by design.)")
    print(f"    {'Cat':<4} {'Detected':>10}")
    print(f"    {'-'*16}")
    for cat in PAPER_CATEGORIES:
        print(f"    {cat:<4} {ref['detections'].get(cat, 0):>10}")


def write_results(letter: str, agg: dict, results: list[dict]) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"results_{letter}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(agg) + "\n")
        for r in results:
            entry = {"type": "per_contract"}
            entry.update(r)
            f.write(json.dumps(entry) + "\n")

    print(f"\n[Prompt {letter}] → {os.path.relpath(out_path, _BASE)}")
    print(f"  Contracts evaluated : {agg['samples_evaluated']}")
    _print_new_pipeline(
        agg["samples_evaluated"],
        agg["new_pipeline"]["summary"],
        agg["new_pipeline"]["per_category"],
    )
    _print_paper_reference(agg["paper_reference"])


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    for letter in ("A", "B"):
        results = evaluate_prompt(letter)
        if not results:
            print(f"[Prompt {letter}] No valid outputs found.")
            continue
        agg = aggregate(results, letter)
        write_results(letter, agg, results)


if __name__ == "__main__":
    main()
