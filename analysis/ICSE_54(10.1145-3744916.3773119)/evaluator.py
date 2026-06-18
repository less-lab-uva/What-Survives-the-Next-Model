#!/usr/bin/env python3
"""
Evaluates single-call LLM outputs against the paper's ground-truth PDG.

Usage:
    python3 evaluator.py [dataset_name]

"""

import difflib
import json
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — all relative to this file
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "outputs"
RESULTS_DIR = BASE_DIR / "results"
DATASET_DIR = BASE_DIR / "dataset"

DATASET_FILES = {
    "stattype": DATASET_DIR / "Stattype_res.json",
}

PROMPTS = ["A", "B"]


# ---------------------------------------------------------------------------
# Metric computation (verbatim from paper's RQ3_eval.py)
# ---------------------------------------------------------------------------
def calculate_fp_tp_fn(edges, valid_edges, partial_code):
    tp = fp = fn = 0
    j = None
    for i in edges:
        tp_flag = 0
        for j in valid_edges:
            if (textwrap.dedent(j["node_out"].strip().replace(" ", "")) ==
                    textwrap.dedent(i["node_out"].strip().replace(" ", "")) and
                    i["edge_type"] == "DDG"):
                if (textwrap.dedent(j["node_in"].strip().replace(" ", "")) ==
                        textwrap.dedent(i["node_in"].strip().replace(" ", ""))):
                    tp += 1
                    tp_flag += 1
                    break
        if (i["node_out"] in partial_code and i["node_in"] in partial_code and
                i["edge_type"] == "DDG" and j is not None):
            if textwrap.dedent(j["node_out"].strip()) != textwrap.dedent(i["node_out"].strip()):
                if textwrap.dedent(j["node_in"].strip()) != textwrap.dedent(i["node_in"].strip()):
                    fp += 1
        for j in valid_edges:
            if (i["node_out"] in partial_code and i["node_in"] in partial_code and
                    i["edge_type"] == "DDG" and j["edge_type"] == "DDG"):
                node_out_i = textwrap.dedent(i["node_out"].strip()).replace(" ", "").replace("\t", "")
                node_out_j = textwrap.dedent(j["node_out"].strip()).replace(" ", "").replace("\t", "")
                node_in_i  = textwrap.dedent(i["node_in"].strip()).replace(" ", "").replace("\t", "")
                node_in_j  = textwrap.dedent(j["node_in"].strip()).replace(" ", "").replace("\t", "")
                if (node_out_i == node_out_j and
                        difflib.SequenceMatcher(
                            None,
                            textwrap.dedent(j["node_in"].strip()),
                            textwrap.dedent(i["node_in"].strip()),
                        ).ratio() > 0.8 and node_in_i != node_in_j):
                    fp += 1
                elif (node_in_i == node_in_j and
                        difflib.SequenceMatcher(
                            None,
                            textwrap.dedent(j["node_out"].strip()),
                            textwrap.dedent(i["node_out"].strip()),
                        ).ratio() > 0.8 and node_out_i != node_out_j):
                    fp += 1
    fn = len(valid_edges) - tp
    return tp, fp, fn


def prf(tp: int, fp: int, fn: int) -> tuple:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return round(p * 100, 1), round(r * 100, 1), round(f * 100, 1)


# ---------------------------------------------------------------------------
# Output file loading
# ---------------------------------------------------------------------------
def load_outputs(letter: str) -> list:
    """Load all output entries for this prompt letter (aggregate or per-entry files)."""
    aggregate = OUTPUT_DIR / f"outputs_{letter}.jsonl"
    if aggregate.exists():
        return _read_jsonl(aggregate)
    entries = []
    for path in sorted(OUTPUT_DIR.glob(f"*_{letter}.jsonl")):
        entries.extend(_read_jsonl(path))
    return entries


def _read_jsonl(path: Path) -> list:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def load_dataset_json(dataset_name: str) -> dict:
    path = DATASET_FILES.get(dataset_name)
    if path is None or not path.exists():
        print(f"[!] Dataset file not found: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Per-entry evaluation
# ---------------------------------------------------------------------------
def evaluate_entry(output_entry: dict, dataset_data: dict) -> dict:
    """
    Evaluate one LLM output entry.

    Returns a dict with:
      entry_name, variant, parse_failed,
      our: {tp, fp, fn, precision, recall, f1}
    """
    entry_name   = output_entry["entry_name"]
    variant      = output_entry["variant"]
    partial_code = output_entry.get("partial_code", "")
    parse_failed = output_entry.get("parse_failed", False)
    sonnet_ddg   = output_entry.get("ddg", [])

    result = {
        "entry_name":   entry_name,
        "variant":      variant,
        "parse_failed": parse_failed,
    }

    # Ground truth PDG — only field read from dataset
    entry_data = dataset_data.get(entry_name, {})
    gt_res     = entry_data.get("ground_truth", {}).get("ground_truth_res", {})
    if not gt_res or isinstance(gt_res, str):
        result["our"]  = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        result["note"] = "no_ground_truth"
        return result

    gt_pdg = gt_res.get("pdg_in_code", [])
    valid_edges = [
        e for e in gt_pdg
        if e["node_out"].strip() in partial_code.strip()
        and e["node_in"].strip()  in partial_code.strip()
        and e["edge_type"] == "DDG"
    ]

    if not valid_edges:
        result["note"]             = "no_valid_edges"
        result["valid_edge_count"] = 0
        result["our"]              = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        return result

    # Evaluate using LLM-generated DDG
    if parse_failed or not sonnet_ddg:
        our_tp, our_fp, our_fn = 0, 0, len(valid_edges)
    else:
        our_tp, our_fp, our_fn = calculate_fp_tp_fn(sonnet_ddg, valid_edges, partial_code)

    our_p, our_r, our_f = prf(our_tp, our_fp, our_fn)
    result["our"]              = {"tp": our_tp, "fp": our_fp, "fn": our_fn,
                                  "precision": our_p, "recall": our_r, "f1": our_f}
    result["valid_edge_count"] = len(valid_edges)

    return result


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
def aggregate_results(per_entry: list) -> dict:
    """Aggregate TP/FP/FN across all evaluated entries (same logic as paper)."""
    our_tp = our_fp = our_fn = 0
    n_parse_failed = n_no_gt = n_no_valid_edges = 0

    for r in per_entry:
        if r.get("note") == "no_ground_truth":
            n_no_gt += 1
            continue
        if r.get("note") == "no_valid_edges":
            n_no_valid_edges += 1
            continue
        if r.get("parse_failed"):
            n_parse_failed += 1
        our_tp += r["our"]["tp"]
        our_fp += r["our"]["fp"]
        our_fn += r["our"]["fn"]

    our_p, our_r, our_f = prf(our_tp, our_fp, our_fn)
    n_evaluated = len(per_entry) - n_no_gt - n_no_valid_edges

    return {
        "type":             "aggregate",
        "n_evaluated":      n_evaluated,
        "n_parse_failed":   n_parse_failed,
        "n_no_gt":          n_no_gt,
        "n_no_valid_edges": n_no_valid_edges,
        "metric_note":      "DDG edges only (Data column in paper Table 1)",
        "our_metrics": {
            "precision": our_p, "recall": our_r, "f1": our_f,
            "tp": our_tp, "fp": our_fp, "fn": our_fn,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    dataset_name = sys.argv[1].lower() if len(sys.argv) > 1 else "stattype"

    dataset_data = load_dataset_json(dataset_name)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for letter in PROMPTS:
        output_entries = load_outputs(letter)
        if not output_entries:
            print(f"[!] No outputs found for Prompt {letter}. Skipping.")
            continue

        print(f"\n[*] Prompt {letter}: {len(output_entries)} entries")

        per_entry_results = []
        for i, out_entry in enumerate(output_entries, 1):
            en = out_entry.get("entry_name", "?")
            vk = out_entry.get("variant", "?")
            print(f"  [{i}/{len(output_entries)}] {en}/{vk} ...", end=" ", flush=True)
            r = evaluate_entry(out_entry, dataset_data)
            per_entry_results.append(r)
            status = "PARSE_FAIL"     if r.get("parse_failed") else \
                     "NO_GT"          if r.get("note") == "no_ground_truth" else \
                     "NO_VALID_EDGES" if r.get("note") == "no_valid_edges" else \
                     f"P={r['our']['precision']}% R={r['our']['recall']}% F1={r['our']['f1']}%"
            print(status)

        agg = aggregate_results(per_entry_results)
        agg["prompt"]  = letter
        agg["dataset"] = dataset_name

        results_path = RESULTS_DIR / f"results_{letter}.jsonl"
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(agg) + "\n")
            for r in per_entry_results:
                f.write(json.dumps(r) + "\n")

        print(f"\n  === Prompt {letter} Aggregate ({dataset_name.upper()}) ===")
        print(f"  Our pipeline:  "
              f"P={agg['our_metrics']['precision']}%  "
              f"R={agg['our_metrics']['recall']}%  "
              f"F1={agg['our_metrics']['f1']}%  "
              f"(n={agg['n_evaluated']}, parse_failed={agg['n_parse_failed']}, "
              f"skipped_no_valid_edges={agg['n_no_valid_edges']})")
        print(f"  Saved → {results_path}")
        print(f"  Note: {agg['metric_note']}")

    print()


if __name__ == "__main__":
    main()
