#!/usr/bin/env python3
"""
Evaluate Opus pipeline outputs against RBCTest paper RQ1 and RQ4 metrics.

Usage:
    python3 evaluate.py rq1    # Constraint mining: Precision / Recall / F1
    python3 evaluate.py rq4    # Mismatch detection: matched / mismatched / unknown
    python3 evaluate.py all    # Both

Results are printed to stdout and saved under output/.
    output/rq1_results.json
    output/rq4_results.json
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict


RBCTEST_ROOT   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER  = os.path.join(RBCTEST_ROOT, "output")
RESULTS_FOLDER = os.path.join(RBCTEST_ROOT, "results")
GT_ROOT       = os.path.join(RBCTEST_ROOT, "approaches", "agora_data", "our_ground_truth")
PROMPTS       = ["A", "B"]

# 5-seed mean values from CompareAGORAData.xlsx (Mining sheet, mean block).
# GT / TP / FP / FN are counts; P / R / F1 are percentages.
PAPER_BASELINES = {
    "OMDB bySearch":         {"gt":  6, "tp": 5.2, "fp": 1.8, "fn": 0.8, "P": 74.3, "R": 86.7, "F1": 80.0},
    "OMDB byIdOrTitle":      {"gt": 15, "tp":11.8, "fp": 0.8, "fn": 3.2, "P": 93.7, "R": 78.7, "F1": 85.5},
    "Yelp getBusinesses":    {"gt":  4, "tp": 3.2, "fp": 1.8, "fn": 0.8, "P": 64.0, "R": 80.0, "F1": 71.1},
    "Hotel Search":          {"gt": 59, "tp":43.8, "fp": 4.4, "fn":12.4, "P": 90.9, "R": 77.9, "F1": 83.9},
    "Spotify createPlaylist":{"gt": 27, "tp":19.8, "fp": 6.4, "fn": 6.8, "P": 75.6, "R": 74.4, "F1": 75.0},
    "Spotify getAlbumTracks":{"gt": 21, "tp":17.8, "fp": 4.0, "fn": 4.4, "P": 81.7, "R": 80.2, "F1": 80.9},
    "Spotify getArtistAlbums":{"gt":16, "tp":15.4, "fp": 3.4, "fn": 1.0, "P": 81.9, "R": 93.9, "F1": 87.5},
    "Marvel getComicById":   {"gt": 50, "tp":35.4, "fp": 4.0, "fn":12.4, "P": 89.8, "R": 74.1, "F1": 81.2},
    "Youtube GetVideos":     {"gt":161, "tp":134.2,"fp": 8.4, "fn":24.6, "P": 94.1, "R": 84.5, "F1": 89.1},
}

FEASIBLE_AGORA_SERVICES = [
    "OMDB bySearch",
    "OMDB byIdOrTitle",
    "Yelp getBusinesses",
    "Hotel Search",
    "Spotify createPlaylist",
    "Spotify getAlbumTracks",
    "Spotify getArtistAlbums",
    "Marvel getComicById",
    "Youtube GetVideos",
]

csv.field_size_limit(10_000_000)


# ── path helpers ──────────────────────────────────────────────────────────────

def safe_name(name):
    return re.sub(r"[^\w\-]", "_", name)


def output_json_path(prompt_letter, service_name):
    return os.path.join(
        OUTPUT_FOLDER,
        f"agora_{safe_name(service_name)}_prompt{prompt_letter}.json",
    )


def load_opus_output(prompt_letter, service_name):
    path = output_json_path(prompt_letter, service_name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── ground truth loading ──────────────────────────────────────────────────────

def load_ground_truth(service_name):
    """
    Return two sets of (operation, response_resource, attribute) triples —
    one for response-property constraints, one for request-response constraints.
    """
    gt_dir = os.path.join(GT_ROOT, service_name)
    rp_keys = set()
    rr_keys = set()

    rp_path = os.path.join(gt_dir, "response_property_constraints_all_groups.csv")
    if os.path.exists(rp_path):
        with open(rp_path, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                key = (
                    row.get("operation", "").strip().lower(),
                    row.get("response resource", "").strip(),
                    row.get("attribute", "").strip(),
                )
                if all(key):
                    rp_keys.add(key)

    rr_path = os.path.join(gt_dir, "request_response_constraints_all_groups.csv")
    if os.path.exists(rr_path):
        with open(rr_path, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                key = (
                    row.get("operation", "").strip().lower(),
                    row.get("response resource", "").strip(),
                    row.get("attribute", "").strip(),
                )
                if all(key):
                    rr_keys.add(key)

    return rp_keys, rr_keys


# ── Opus output parsing ───────────────────────────────────────────────────────

def extract_mined_keys(output_data):
    """
    Extract (operation, response_resource, attribute) triples from Opus output.
    Returns (rp_keys, rr_keys) as sets.
    """
    rp_keys = set()
    rr_keys = set()

    for c in output_data.get("response_property_constraints", []):
        op  = c.get("operation", "")
        res = c.get("response_resource", "")
        att = c.get("attribute", "")
        key = (str(op).strip().lower(), str(res).strip(), str(att).strip())
        if all(key):
            rp_keys.add(key)

    for c in output_data.get("request_response_constraints", []):
        # Opus may use either field name for the operation
        op  = c.get("attribute_inferred_from_operation") or c.get("operation", "")
        res = c.get("response_resource", "")
        att = c.get("attribute", "")
        key = (str(op).strip().lower(), str(res).strip(), str(att).strip())
        if all(key):
            rr_keys.add(key)

    return rp_keys, rr_keys


# ── metrics ───────────────────────────────────────────────────────────────────

def prf(tp, fp, fn):
    p  = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return round(p * 100, 1), round(r * 100, 1), round(f1 * 100, 1)


# ── RQ1 ───────────────────────────────────────────────────────────────────────

def compute_rq1():
    print("\n" + "=" * 70)
    print("RQ1  Constraint Mining Accuracy  (Precision / Recall / F1)")
    print("=" * 70)
    print("Matching key: (operation, response_resource, attribute) triple")
    print("Paper values: 5-seed mean from CompareAGORAData.xlsx")
    print()

    baselines = PAPER_BASELINES

    all_results = {}

    for prompt_letter in PROMPTS:
        print(f"{'─'*70}")
        print(f"Prompt {prompt_letter}")
        print(f"{'─'*70}")
        hdr = f"  {'Service':<30}  {'':^22}  {'':^22}"
        print(f"  {'Service':<30}  {'── Opus ──────────────':^22}  {'── Paper (mean) ──────':^22}")
        print(f"  {'-'*30}  {'P%':>6} {'R%':>6} {'F1%':>6}  {'P%':>6} {'R%':>6} {'F1%':>6}  {'diff F1':>8}")
        print(f"  {'-'*30}  {'------':>6} {'------':>6} {'------':>6}  {'------':>6} {'------':>6} {'------':>6}  {'--------':>8}")

        rows   = []
        totals = defaultdict(int)

        for service in FEASIBLE_AGORA_SERVICES:
            output_data = load_opus_output(prompt_letter, service)
            base = baselines.get(service, {})

            if output_data is None:
                p_str = r_str = f1_str = "    —"
                diff_str = "       —"
                opus_entry = {}
            else:
                gt_rp, gt_rr       = load_ground_truth(service)
                mined_rp, mined_rr = extract_mined_keys(output_data)
                gt_all    = gt_rp | gt_rr
                mined_all = mined_rp | mined_rr
                tp = len(mined_all & gt_all)
                fp = len(mined_all - gt_all)
                fn = len(gt_all - mined_all)
                op, or_, of1 = prf(tp, fp, fn)
                p_str   = f"{op:>6.1f}"
                r_str   = f"{or_:>6.1f}"
                f1_str  = f"{of1:>6.1f}"
                totals["gt"]    += len(gt_all)
                totals["mined"] += len(mined_all)
                totals["tp"]    += tp
                totals["fp"]    += fp
                totals["fn"]    += fn
                opus_entry = {
                    "gt": len(gt_all), "mined": len(mined_all),
                    "tp": tp, "fp": fp, "fn": fn,
                    "P": op, "R": or_, "F1": of1,
                }

            if base:
                bp, br, bf1 = base["P"], base["R"], base["F1"]
                bp_str  = f"{bp:>6.1f}"
                br_str  = f"{br:>6.1f}"
                bf1_str = f"{bf1:>6.1f}"
                if opus_entry:
                    diff = round(of1 - bf1, 1)
                    sign = "+" if diff >= 0 else ""
                    diff_str = f"{sign}{diff:>6.1f}%"
                else:
                    diff_str = "       —"
            else:
                bp_str = br_str = bf1_str = "    —"
                diff_str = "       —"

            print(f"  {service:<30}  {p_str} {r_str} {f1_str}  {bp_str} {br_str} {bf1_str}  {diff_str}")

            rows.append({
                "service": service,
                "opus":    opus_entry if opus_entry else None,
                "paper":   base if base else None,
                "F1_diff": round(of1 - base["F1"], 1) if (opus_entry and base) else None,
            })

        # Totals row (Opus only — paper total spans all 11 services including GitHub)
        if totals["tp"] + totals["fp"] + totals["fn"] > 0:
            tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
            p, r, f1 = prf(tp, fp, fn)
            print(f"  {'─'*30}  {'──────':>6} {'──────':>6} {'──────':>6}  {'(9/11 svcs)':>21}  {'':>8}")
            print(f"  {'TOTAL (9 services)':<30}  {p:>6.1f} {r:>6.1f} {f1:>6.1f}  "
                  f"{'see paper':>6} {'Table 3':>6} {'col':>6}")
            rows.append({
                "service": "TOTAL (9 of 11 services)",
                "opus": {
                    "gt": totals["gt"], "mined": totals["mined"],
                    "tp": totals["tp"], "fp": totals["fp"], "fn": totals["fn"],
                    "P": p, "R": r, "F1": f1,
                },
                "paper": {
                    "note": "Paper total covers all 11 services incl. 2 GitHub — not directly comparable"
                },
                "F1_diff": None,
            })

        all_results[f"prompt_{prompt_letter}"] = rows
        print()

    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    out_path = os.path.join(OUTPUT_FOLDER, "rq1_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"[+] RQ1 results saved to {out_path}")

    # Write results_A.jsonl / results_B.jsonl
    for letter in PROMPTS:
        key  = f"prompt_{letter}"
        rows = all_results[key]
        total_row    = next((r for r in rows if r["service"] == "TOTAL (9 of 11 services)"), {})
        service_rows = [r for r in rows if r["service"] != "TOTAL (9 of 11 services)"]
        opus_total   = (total_row.get("opus") or {})
        aggregate = {
            "prompt": letter, "rq": "rq1", "dataset": "AGORA+ (9 of 11 services)",
            "P": opus_total.get("P"), "R": opus_total.get("R"), "F1": opus_total.get("F1"),
            "tp": opus_total.get("tp"), "fp": opus_total.get("fp"),
            "fn": opus_total.get("fn"), "gt": opus_total.get("gt"),
        }
        jsonl_path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
        mode = "w"
        with open(jsonl_path, mode, encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for r in service_rows:
                f.write(json.dumps(r) + "\n")
        print(f"[+] results_{letter}.jsonl (rq1) saved to {jsonl_path}")

    return all_results


# ── RQ4 ───────────────────────────────────────────────────────────────────────

def compute_rq4():
    print("\n" + "=" * 70)
    print("RQ4  Mismatch Detection  (matched / mismatched / unknown)")
    print("=" * 70)
    print("Verdicts are read directly from the 'verdict' field in each constraint.")
    print()

    all_results = {}

    for prompt_letter in PROMPTS:
        print(f"{'─'*70}")
        print(f"Prompt {prompt_letter}")
        print(f"{'─'*70}")
        print(f"  {'Service':<35}  {'Total':>5}  {'Matched':>7}  {'Mismatch':>8}  {'Unknown':>7}")
        print(f"  {'-'*35}  {'-----':>5}  {'-------':>7}  {'--------':>8}  {'-------':>7}")

        rows   = []
        totals = defaultdict(int)

        for service in FEASIBLE_AGORA_SERVICES:
            output_data = load_opus_output(prompt_letter, service)
            if output_data is None:
                print(f"  {service:<35}  (no output file — skipped)")
                continue

            all_constraints = (
                output_data.get("response_property_constraints", []) +
                output_data.get("request_response_constraints", [])
            )

            matched    = sum(1 for c in all_constraints if c.get("verdict") == "matched")
            mismatched = sum(1 for c in all_constraints if c.get("verdict") == "mismatched")
            unknown    = sum(1 for c in all_constraints if c.get("verdict") == "unknown")
            total      = len(all_constraints)

            print(f"  {service:<35}  {total:>5}  {matched:>7}  {mismatched:>8}  {unknown:>7}")

            totals["total"]      += total
            totals["matched"]    += matched
            totals["mismatched"] += mismatched
            totals["unknown"]    += unknown

            rows.append({
                "service":    service,
                "total":      total,
                "matched":    matched,
                "mismatched": mismatched,
                "unknown":    unknown,
            })

        if totals["total"] > 0:
            print(f"  {'─'*35}  {'─────':>5}  {'───────':>7}  {'────────':>8}  {'───────':>7}")
            print(f"  {'TOTAL':<35}  {totals['total']:>5}  {totals['matched']:>7}  "
                  f"{totals['mismatched']:>8}  {totals['unknown']:>7}")
            rows.append({
                "service":    "TOTAL",
                "total":      totals["total"],
                "matched":    totals["matched"],
                "mismatched": totals["mismatched"],
                "unknown":    totals["unknown"],
            })

        all_results[f"prompt_{prompt_letter}"] = rows
        print()

    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    out_path = os.path.join(OUTPUT_FOLDER, "rq4_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"[+] RQ4 results saved to {out_path}")

    # Append rq4 rows to results_A.jsonl / results_B.jsonl
    for letter in PROMPTS:
        key  = f"prompt_{letter}"
        rows = all_results[key]
        total_row    = next((r for r in rows if r["service"] == "TOTAL"), {})
        service_rows = [r for r in rows if r["service"] != "TOTAL"]
        aggregate = {
            "prompt": letter, "rq": "rq4", "dataset": "AGORA+ (9 of 11 services)",
            "total":      total_row.get("total"),
            "matched":    total_row.get("matched"),
            "mismatched": total_row.get("mismatched"),
            "unknown":    total_row.get("unknown"),
        }
        jsonl_path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for r in service_rows:
                f.write(json.dumps(r) + "\n")
        print(f"[+] results_{letter}.jsonl (rq4) appended to {jsonl_path}")

    # Paper baseline for reference
    print()
    print("Paper baseline (AGORA+ dataset, Table 6):")
    print("  RBCTest: 361 matched  9 mismatched  73 unknown  (out of 443 constraints)")

    return all_results


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("rq1", "rq4", "all"):
        print("Usage: python3 evaluate.py <rq1|rq4|all>")
        print()
        print("  rq1  Constraint mining accuracy  — Precision / Recall / F1")
        print("         Matches mined constraints against ground truth triples.")
        print("         Reads:  output/agora_<service>_prompt[AB].json")
        print("         Saves:  output/rq1_results.json")
        print()
        print("  rq4  Mismatch detection counts   — matched / mismatched / unknown")
        print("         Aggregates verdict fields from all mined constraints.")
        print("         Reads:  output/agora_<service>_prompt[AB].json")
        print("         Saves:  output/rq4_results.json")
        print()
        print("  all  Both RQ1 and RQ4")
        sys.exit(1)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    rq = sys.argv[1].lower()

    if rq in ("rq1", "all"):
        compute_rq1()
    if rq in ("rq4", "all"):
        compute_rq4()


if __name__ == "__main__":
    main()
