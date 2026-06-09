#!/usr/bin/env python3
"""
Evaluate Sonnet pipeline outputs against RBCTest paper RQ1 metric.

Reads from both output sources produced by main.py:
  outputs/outputs_A.jsonl     — services whose output was <= 50 KB
  outputs/<safe_name>_promptA.json  — services whose output was > 50 KB
(same for prompt B)

Usage:
    python3 evaluator.py          # RQ1 for all prompts
    python3 evaluator.py [service_name]  # RQ1 for one service only

Results are printed to stdout and saved to:
    results/rq1_results.json
    results/results_A.jsonl
    results/results_B.jsonl
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR     = Path(__file__).parent
OUTPUT_DIR   = BASE_DIR / "outputs"
RESULTS_DIR  = BASE_DIR / "results"
GT_DIR       = BASE_DIR / ".." / "approaches" / "agora_data" / "our_ground_truth"

PROMPTS = ["A", "B"]

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

# 5-seed mean from CompareAGORAData.xlsx (Mining sheet).
PAPER_BASELINES = {
    "OMDB bySearch":          {"gt":  6, "tp": 5.2, "fp": 1.8, "fn": 0.8, "P": 74.3, "R": 86.7, "F1": 80.0},
    "OMDB byIdOrTitle":       {"gt": 15, "tp":11.8, "fp": 0.8, "fn": 3.2, "P": 93.7, "R": 78.7, "F1": 85.5},
    "Yelp getBusinesses":     {"gt":  4, "tp": 3.2, "fp": 1.8, "fn": 0.8, "P": 64.0, "R": 80.0, "F1": 71.1},
    "Hotel Search":           {"gt": 59, "tp":43.8, "fp": 4.4, "fn":12.4, "P": 90.9, "R": 77.9, "F1": 83.9},
    "Spotify createPlaylist": {"gt": 27, "tp":19.8, "fp": 6.4, "fn": 6.8, "P": 75.6, "R": 74.4, "F1": 75.0},
    "Spotify getAlbumTracks": {"gt": 21, "tp":17.8, "fp": 4.0, "fn": 4.4, "P": 81.7, "R": 80.2, "F1": 80.9},
    "Spotify getArtistAlbums":{"gt": 16, "tp":15.4, "fp": 3.4, "fn": 1.0, "P": 81.9, "R": 93.9, "F1": 87.5},
    "Marvel getComicById":    {"gt": 50, "tp":35.4, "fp": 4.0, "fn":12.4, "P": 89.8, "R": 74.1, "F1": 81.2},
    "Youtube GetVideos":      {"gt":161, "tp":134.2,"fp": 8.4, "fn":24.6, "P": 94.1, "R": 84.5, "F1": 89.1},
}

csv.field_size_limit(10_000_000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)


def sep_output_path(letter: str, service_name: str) -> Path:
    return OUTPUT_DIR / f"{safe_name(service_name)}_prompt{letter}.json"


def jsonl_output_path(letter: str) -> Path:
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


# ---------------------------------------------------------------------------
# Output loading — checks both storage paths
# ---------------------------------------------------------------------------
def load_output(letter: str, service_name: str):
    """
    Return the parsed output dict for (letter, service_name), or None if not found.
    Skipped or parse-failed entries are treated as not available.
    """
    # 1. separate file
    sep = sep_output_path(letter, service_name)
    if sep.exists():
        try:
            data = json.loads(sep.read_text(encoding="utf-8"))
            if not data.get("skipped") and not data.get("parse_failed"):
                return data
        except json.JSONDecodeError:
            pass

    # 2. JSONL
    jpath = jsonl_output_path(letter)
    if not jpath.exists():
        return None
    try:
        for line in jpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("service_name") == service_name:
                if not rec.get("skipped") and not rec.get("parse_failed"):
                    return rec
    except (json.JSONDecodeError, OSError):
        pass

    return None


# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------
def load_ground_truth(service_name: str):
    """
    Return two sets of (operation, response_resource, attribute) triples —
    one for response-property constraints, one for request-response constraints.
    """
    gt_dir  = GT_DIR / service_name
    rp_keys = set()
    rr_keys = set()

    rp_path = gt_dir / "response_property_constraints_all_groups.csv"
    if rp_path.exists():
        with open(rp_path, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                key = (
                    row.get("operation", "").strip().lower(),
                    row.get("response resource", "").strip(),
                    row.get("attribute", "").strip(),
                )
                if all(key):
                    rp_keys.add(key)

    rr_path = gt_dir / "request_response_constraints_all_groups.csv"
    if rr_path.exists():
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


# ---------------------------------------------------------------------------
# Mined key extraction
# ---------------------------------------------------------------------------
def extract_mined_keys(output_data: dict):
    """
    Extract (operation, response_resource, attribute) triples from pipeline output.
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
        op  = c.get("attribute_inferred_from_operation") or c.get("operation", "")
        res = c.get("response_resource", "")
        att = c.get("attribute", "")
        key = (str(op).strip().lower(), str(res).strip(), str(att).strip())
        if all(key):
            rr_keys.add(key)

    return rp_keys, rr_keys


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def prf(tp: int, fp: int, fn: int):
    p  = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return round(p * 100, 1), round(r * 100, 1), round(f1 * 100, 1)


# ---------------------------------------------------------------------------
# RQ1
# ---------------------------------------------------------------------------
def compute_rq1(service_filter=None):
    services = FEASIBLE_AGORA_SERVICES
    if service_filter:
        services = [s for s in services if s.lower() == service_filter.lower()]
        if not services:
            print(f"[!] Service '{service_filter}' not in FEASIBLE_AGORA_SERVICES.")
            sys.exit(1)

    print("\n" + "=" * 72)
    print("RQ1  Constraint Mining Accuracy  (Precision / Recall / F1)")
    print("=" * 72)
    print("Matching key: (operation, response_resource, attribute) triple")
    print("Paper values: 5-seed mean from CompareAGORAData.xlsx")
    print()

    all_results = {}

    for letter in PROMPTS:
        print(f"{'─'*72}")
        print(f"Prompt {letter}")
        print(f"{'─'*72}")
        print(f"  {'Service':<30}  {'── Sonnet ─────────────':^22}  {'── Paper (mean) ───────':^22}  {'diff':>6}")
        print(f"  {'-'*30}  {'P%':>6} {'R%':>6} {'F1%':>6}  {'P%':>6} {'R%':>6} {'F1%':>6}  {'F1':>6}")
        print(f"  {'-'*30}  {'------':>6} {'------':>6} {'------':>6}  {'------':>6} {'------':>6} {'------':>6}  {'------':>6}")

        rows   = []
        totals = defaultdict(int)

        for service in services:
            output_data = load_output(letter, service)
            base        = PAPER_BASELINES.get(service, {})

            if output_data is None:
                p_str = r_str = f1_str = "    —"
                diff_str = "     —"
                entry = {}
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
                entry = {
                    "gt": len(gt_all), "mined": len(mined_all),
                    "tp": tp, "fp": fp, "fn": fn,
                    "P": op, "R": or_, "F1": of1,
                }

            if base:
                bp_str  = f"{base['P']:>6.1f}"
                br_str  = f"{base['R']:>6.1f}"
                bf1_str = f"{base['F1']:>6.1f}"
                if entry:
                    diff = round(of1 - base["F1"], 1)
                    sign = "+" if diff >= 0 else ""
                    diff_str = f"{sign}{diff:.1f}"
                else:
                    diff_str = "     —"
            else:
                bp_str = br_str = bf1_str = "    —"
                diff_str = "     —"

            print(f"  {service:<30}  {p_str} {r_str} {f1_str}  {bp_str} {br_str} {bf1_str}  {diff_str:>6}")

            rows.append({
                "service": service,
                "sonnet":  entry if entry else None,
                "paper":   base  if base  else None,
                "F1_diff": round(of1 - base["F1"], 1) if (entry and base) else None,
            })

        # Aggregate totals row (Sonnet only — paper total spans all 11 services)
        if totals["tp"] + totals["fp"] + totals["fn"] > 0:
            tp, fp, fn   = totals["tp"], totals["fp"], totals["fn"]
            p, r, f1     = prf(tp, fp, fn)
            print(f"  {'─'*30}  {'──────':>6} {'──────':>6} {'──────':>6}  {'(9/11 svcs, see paper)':>21}  {'':>6}")
            n = len(services)
            label = f"TOTAL ({n} service{'s' if n>1 else ''})"
            print(f"  {label:<30}  {p:>6.1f} {r:>6.1f} {f1:>6.1f}")
            rows.append({
                "service": label,
                "sonnet": {
                    "gt": totals["gt"], "mined": totals["mined"],
                    "tp": tp, "fp": fp, "fn": fn,
                    "P": p, "R": r, "F1": f1,
                },
                "paper": {"note": "Paper total covers all 11 services incl. 2 GitHub"},
                "F1_diff": None,
            })

        all_results[f"prompt_{letter}"] = rows
        print()

    # Save JSON results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rq1_path = RESULTS_DIR / "rq1_results.json"
    rq1_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"[+] RQ1 results saved to {rq1_path.relative_to(BASE_DIR)}")

    # Save per-prompt JSONL results
    for letter in PROMPTS:
        key        = f"prompt_{letter}"
        rows       = all_results[key]
        total_key  = next((r["service"] for r in rows if r["service"].startswith("TOTAL")), None)
        total_row  = next((r for r in rows if r["service"] == total_key), {})
        svc_rows   = [r for r in rows if r["service"] != total_key]
        sonnet_tot = total_row.get("sonnet") or {}
        aggregate  = {
            "prompt": letter, "rq": "rq1", "dataset": "AGORA+ (9 of 11 services)",
            "P":  sonnet_tot.get("P"),
            "R":  sonnet_tot.get("R"),
            "F1": sonnet_tot.get("F1"),
            "tp": sonnet_tot.get("tp"),
            "fp": sonnet_tot.get("fp"),
            "fn": sonnet_tot.get("fn"),
            "gt": sonnet_tot.get("gt"),
        }
        jpath = RESULTS_DIR / f"results_{letter}.jsonl"
        with open(jpath, "w", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for r in svc_rows:
                f.write(json.dumps(r) + "\n")
        print(f"[+] results_{letter}.jsonl saved to {jpath.relative_to(BASE_DIR)}")

    return all_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    service_filter = sys.argv[1] if len(sys.argv) > 1 else None
    compute_rq1(service_filter)


if __name__ == "__main__":
    main()
