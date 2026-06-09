#!/usr/bin/env python3
"""
Evaluates single-call LLM outputs against the paper's ground-truth PDG using Joern.

Usage:
    python3 evaluator.py [dataset_name]

    dataset_name: stattype  (default)

Reads:
    outputs/outputs_A.jsonl  and  outputs/outputs_B.jsonl
    (or per-entry files outputs/{entry_name}_{variant}_{letter}.jsonl)

For each output entry:
  1. Runs Joern on the LLM-generated approximated_code to obtain a PDG.
     Joern results are cached in outputs/joern_cache.json so reruns are fast.
  2. Loads the ground-truth PDG from dataset/Stattype_res.json.
  3. Computes valid_edges: DDG edges whose both endpoints (stripped) appear in
     partial_code — identical to the paper's pruning step.
  4. Calls calculate_fp_tp_fn (verbatim from the paper's RQ3_eval.py).
  5. Also computes metrics for the Original PrePA pipeline on the same entries,
     using the pre-stored PrePA_code_res from the dataset JSON.

Writes:
    results/results_A.jsonl  and  results/results_B.jsonl
    Line 1:  aggregate JSON  — our metrics + Original PrePA metrics
    Lines 2+: per-entry JSON — our metrics + Original PrePA metrics per entry

Metric note:
    Only DDG (data dependence) edges are evaluated — this corresponds to the
    "Data" column in the paper's Table 1, not the "Data+Control" headline.
    The paper's evaluate_fp_tp_fn function is reproduced verbatim.

Joern path:
    Update JOERN_PATH below if your Joern installation is elsewhere.
    The evaluator is otherwise fully self-contained within this folder.
"""

import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pydot
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths — all relative to this file
# ---------------------------------------------------------------------------
BASE_DIR       = Path(__file__).parent
OUTPUT_DIR     = BASE_DIR / "outputs"
RESULTS_DIR    = BASE_DIR / "results"
DATASET_DIR    = BASE_DIR / "dataset"
def joern_cache_path(letter: str) -> Path:
    return OUTPUT_DIR / f"joern_cache_{letter}.json"

DATASET_FILES = {
    "stattype": DATASET_DIR / "Stattype_res.json",
}

PROMPTS = ["A", "B"]

# Joern binary directory — update if your installation differs
JOERN_PATH = "/project/lesslab/nm8tm/joern-cli/joern-cli/bin"


# ---------------------------------------------------------------------------
# Joern invocation (compatible with PrePA/evaluator.py)
# ---------------------------------------------------------------------------
def generate_prolog(code):
    if not code or not code.strip():
        return ("Joern Failed to parse the code",) * 3 + ("Empty file",) * 2
    tmp_dir  = tempfile.TemporaryDirectory()
    md5_v    = hashlib.md5(code.encode()).hexdigest()
    fname    = "func_" + md5_v + ".java"
    with open(os.path.join(tmp_dir.name, fname), "w") as f:
        f.write(code)
    try:
        joern_parse = subprocess.run(
            [f"{JOERN_PATH}/joern-parse", tmp_dir.name],
            capture_output=True, text=True, cwd=tmp_dir.name,
        )
    except Exception as e:
        joern_parse = str(e)
    try:
        joern_pdg = subprocess.run(
            [f"{JOERN_PATH}/joern-export", "--repr", "pdg",
             "--out", os.path.join(tmp_dir.name, "output")],
            capture_output=True, text=True, cwd=tmp_dir.name,
        )
    except Exception as e:
        joern_pdg = str(e)
    subprocess.run(
        [f"{JOERN_PATH}/joern-export", "--repr", "all",
         "--out", os.path.join(tmp_dir.name, "label")],
        capture_output=True, text=True, cwd=tmp_dir.name,
    )
    subprocess.run(
        [f"{JOERN_PATH}/joern-export", "--repr", "all",
         "--format=graphml", "--out", os.path.join(tmp_dir.name, "code")],
        capture_output=True, text=True, cwd=tmp_dir.name,
    )
    try:
        out_dir  = os.path.join(tmp_dir.name, "output")
        pdg_list = [
            open(os.path.join(out_dir, fn)).read()
            for fn in sorted(os.listdir(out_dir))
            if fn.endswith("-pdg.dot")
        ]
        if not pdg_list:
            pdg_list = None
    except Exception:
        pdg_list = None
    try:
        with open(os.path.join(tmp_dir.name, "label", "export.dot")) as f:
            all_dot = f.read()
    except Exception:
        all_dot = "Joern Failed to parse the code"
    try:
        with open(os.path.join(tmp_dir.name, "code", "export.xml")) as f:
            xml = f.read()
    except Exception:
        xml = "Joern Failed to parse the code"
    tmp_dir.cleanup()
    return pdg_list, all_dot, xml, str(joern_parse), str(joern_pdg)


def construct_pdg(pdg, all_dot, xml):
    nodes_in_dot, line_in_label, code_of_node = set(), {}, {}
    namespaces = {"graphml": "http://graphml.graphdrawing.org/xmlns"}
    parsed_all = pydot.graph_from_dot_data(all_dot)
    parsed_pdg = pydot.graph_from_dot_data(pdg)
    if not parsed_all or not parsed_pdg:
        return []
    label_node = parsed_all[0]
    dot_file   = parsed_pdg[0]
    label      = ET.fromstring(xml)
    for node in dot_file.get_nodes():
        node_id    = node.get_name().replace('"', "")
        node_label = label.find(f".//graphml:node[@id='{node_id}']", namespaces)
        if node_label is None:
            continue
        node_call_code = ""
        for keys in node_label:
            if "CODE" in keys.attrib.get("key", ""):
                node_call_code = keys.text
                break
        code_of_node[node_id] = node_call_code
    for node in label_node.get_nodes():
        raw = node.get_attributes().get("LINE_NUMBER", "")
        line_in_label[node.get_name().replace('"', "")] = str(raw).strip('"')
    unique_edges = []
    for edge in dot_file.get_edges():
        node_in  = edge.get_destination().replace('"', "")
        node_out = edge.get_source().replace('"', "")
        label_html = dot_file.get_node(edge.get_destination())[0].get_label()
        soup       = BeautifulSoup(label_html, "html.parser")
        label_text = soup.get_text()
        if "METHOD" in label_text or "METHOD_RETURN" in label_text:
            continue
        label_html = dot_file.get_node(edge.get_source())[0].get_label()
        soup       = BeautifulSoup(label_html, "html.parser")
        label_text = soup.get_text()
        if "METHOD" in label_text or "METHOD_RETURN" in label_text:
            continue
        try:
            line_in  = line_in_label[node_in]
            line_out = line_in_label[node_out]
        except Exception:
            continue
        edge_type  = edge.get_label().split(":")[0].split('"')[1]
        identifier = (line_in, line_out, edge_type)
        if identifier not in nodes_in_dot:
            if int(line_in) > int(line_out):
                nodes_in_dot.add(identifier)
                unique_edges.append(
                    {"node_out": line_out, "node_in": line_in, "edge_type": edge_type}
                )
    return unique_edges


def construct_edge_with_code(code, edges):
    lines  = code.splitlines(keepends=True)
    result = []
    for e in edges:
        try:
            result.append({
                "node_out":  lines[int(e["node_out"]) - 1],
                "node_in":   lines[int(e["node_in"])  - 1],
                "edge_type": e["edge_type"],
            })
        except (IndexError, ValueError):
            pass
    return result


def run_joern(code: str) -> dict | str:
    """Return code_res dict on success, or a failure string."""
    try:
        pdg_list, all_dot, xml, joern_parse, joern_pdg = generate_prolog(code)
        if any("Joern Failed" in str(x) for x in (all_dot, xml)):
            return "Joern Failed to Parse the Code"
        if not pdg_list:
            return "Joern Failed to Parse the Code"
        all_edges = []
        for pdg in pdg_list:
            try:
                all_edges.extend(construct_pdg(pdg, all_dot, xml))
            except Exception:
                continue
        edges_in_code = construct_edge_with_code(code, all_edges)
        return {
            "pdg_in_num":      all_edges,
            "pdg_in_code":     edges_in_code,
            "joern_parse_log": joern_parse,
            "joern_pdg_log":   joern_pdg,
        }
    except Exception as exc:
        return f"Joern Failed: {exc}"


# ---------------------------------------------------------------------------
# Joern cache — keyed by MD5 of approximated_code
# ---------------------------------------------------------------------------
def load_joern_cache(letter: str) -> dict:
    path = joern_cache_path(letter)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_joern_cache(cache: dict, letter: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    joern_cache_path(letter).write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_or_run_joern(code: str, cache: dict, letter: str) -> dict | str:
    key = hashlib.md5(code.encode()).hexdigest()
    if key in cache:
        return cache[key]
    result = run_joern(code)
    cache[key] = result
    save_joern_cache(cache, letter)
    return result


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
    # Fall back to per-entry files: outputs/*_{letter}.jsonl
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
def evaluate_entry(output_entry: dict, dataset_data: dict, joern_cache: dict, letter: str) -> dict:
    """
    Evaluate one LLM output entry.

    Returns a dict with:
      entry_name, variant, joern_failed, parse_failed,
      our:   {tp, fp, fn, precision, recall, f1},
      prepa: {tp, fp, fn, precision, recall, f1}
    """
    entry_name   = output_entry["entry_name"]
    variant      = output_entry["variant"]
    partial_code = output_entry.get("partial_code", "")
    approx_code  = output_entry.get("approximated_code") or ""
    parse_failed = output_entry.get("parse_failed", not bool(approx_code))

    result = {
        "entry_name":   entry_name,
        "variant":      variant,
        "parse_failed": parse_failed,
        "joern_failed": False,
    }

    # Ground truth PDG
    entry_data = dataset_data.get(entry_name, {})
    gt_res     = entry_data.get("ground_truth", {}).get("ground_truth_res", {})
    if not gt_res or isinstance(gt_res, str):
        result["our"]   = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        result["prepa"] = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        result["note"]  = "no_ground_truth"
        return result

    gt_pdg = gt_res.get("pdg_in_code", [])
    valid_edges = [
        e for e in gt_pdg
        if e["node_out"].strip() in partial_code.strip()
        and e["node_in"].strip()  in partial_code.strip()
        and e["edge_type"] == "DDG"
    ]

    # No applicable GT edges → skip Joern entirely; exclude from aggregate
    if not valid_edges:
        result["note"] = "no_valid_edges"
        result["valid_edge_count"]     = 0
        result["our_joern_edge_count"] = 0
        result["our_joern_edges"]      = []
        result["our"]   = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        result["prepa"] = {"tp": 0, "fp": 0, "fn": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
        return result

    # ── Our pipeline ────────────────────────────────────────────────────────
    our_joern_edges = []
    if parse_failed or not approx_code:
        our_tp, our_fp, our_fn = 0, 0, len(valid_edges)
        result["joern_failed"] = False
    else:
        code_res = get_or_run_joern(approx_code, joern_cache, letter)
        if isinstance(code_res, str):
            our_tp, our_fp, our_fn = 0, 0, len(valid_edges)
            result["joern_failed"] = True
        else:
            pdg = code_res.get("pdg_in_code", [])
            our_joern_edges = [e for e in pdg if e.get("edge_type") == "DDG"]
            if not pdg:
                our_tp, our_fp, our_fn = 0, 0, len(valid_edges)
            else:
                our_tp, our_fp, our_fn = calculate_fp_tp_fn(pdg, valid_edges, partial_code)

    our_p, our_r, our_f = prf(our_tp, our_fp, our_fn)
    result["our"] = {"tp": our_tp, "fp": our_fp, "fn": our_fn,
                     "precision": our_p, "recall": our_r, "f1": our_f}
    result["valid_edge_count"]     = len(valid_edges)
    result["our_joern_edge_count"] = len(our_joern_edges)
    result["our_joern_edges"]      = our_joern_edges

    # ── Original PrePA (paper's pipeline, pre-stored) ────────────────────────
    variant_data   = entry_data.get(variant, {})
    prepa_code_res = variant_data.get("PrePA_code_res") if isinstance(variant_data, dict) else None

    if isinstance(prepa_code_res, dict):
        prepa_pdg = prepa_code_res.get("pdg_in_code", [])
        if prepa_pdg:
            prepa_tp, prepa_fp, prepa_fn = calculate_fp_tp_fn(prepa_pdg, valid_edges, partial_code)
        else:
            prepa_tp, prepa_fp, prepa_fn = 0, 0, len(valid_edges)
    else:
        prepa_tp, prepa_fp, prepa_fn = 0, 0, len(valid_edges)

    prepa_p, prepa_r, prepa_f = prf(prepa_tp, prepa_fp, prepa_fn)
    result["prepa"] = {"tp": prepa_tp, "fp": prepa_fp, "fn": prepa_fn,
                       "precision": prepa_p, "recall": prepa_r, "f1": prepa_f}

    return result


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
def aggregate_results(per_entry: list) -> dict:
    """Aggregate TP/FP/FN across all evaluated entries (same logic as paper)."""
    our_tp = our_fp = our_fn = 0
    pre_tp = pre_fp = pre_fn = 0
    n_joern_failed = n_parse_failed = n_no_gt = 0

    n_no_valid_edges = 0
    for r in per_entry:
        if r.get("note") in ("no_ground_truth", "no_valid_edges"):
            if r.get("note") == "no_ground_truth":
                n_no_gt += 1
            else:
                n_no_valid_edges += 1
            continue
        if r.get("parse_failed"):
            n_parse_failed += 1
        if r.get("joern_failed"):
            n_joern_failed += 1
        our_tp += r["our"]["tp"]
        our_fp += r["our"]["fp"]
        our_fn += r["our"]["fn"]
        pre_tp += r["prepa"]["tp"]
        pre_fp += r["prepa"]["fp"]
        pre_fn += r["prepa"]["fn"]

    our_p, our_r, our_f     = prf(our_tp, our_fp, our_fn)
    prepa_p, prepa_r, prepa_f = prf(pre_tp, pre_fp, pre_fn)

    n_evaluated = len(per_entry) - n_no_gt - n_no_valid_edges

    return {
        "type":               "aggregate",
        "n_evaluated":        n_evaluated,
        "n_joern_failed":     n_joern_failed,
        "n_parse_failed":     n_parse_failed,
        "n_no_gt":            n_no_gt,
        "n_no_valid_edges":   n_no_valid_edges,
        "metric_note":     "DDG edges only (Data column in paper Table 1, not Data+Control)",
        "our_metrics": {
            "precision": our_p, "recall": our_r, "f1": our_f,
            "tp": our_tp, "fp": our_fp, "fn": our_fn,
        },
        "prepa_metrics": {
            "precision": prepa_p, "recall": prepa_r, "f1": prepa_f,
            "tp": pre_tp, "fp": pre_fp, "fn": pre_fn,
            "note": "Original PrePA pipeline (paper authors) — pre-stored PDGs from dataset JSON",
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

        joern_cache = load_joern_cache(letter)
        print(f"\n[*] Prompt {letter}: {len(output_entries)} entries  "
              f"(cache: {len(joern_cache)} entries in joern_cache_{letter}.json)")

        per_entry_results = []
        for i, out_entry in enumerate(output_entries, 1):
            en = out_entry.get("entry_name", "?")
            vk = out_entry.get("variant", "?")
            print(f"  [{i}/{len(output_entries)}] {en}/{vk} ...", end=" ", flush=True)
            r = evaluate_entry(out_entry, dataset_data, joern_cache, letter)
            per_entry_results.append(r)
            status = "JOERN_FAIL"     if r.get("joern_failed") else \
                     "PARSE_FAIL"     if r.get("parse_failed") else \
                     "NO_GT"          if r.get("note") == "no_ground_truth" else \
                     "NO_VALID_EDGES" if r.get("note") == "no_valid_edges" else \
                     f"P={r['our']['precision']}% R={r['our']['recall']}% F1={r['our']['f1']}%"
            print(status)

            # Print Joern-discovered DDG edges and GT valid edges
            if not r.get("joern_failed") and not r.get("parse_failed") \
                    and r.get("note") != "no_ground_truth":
                n_found = r.get("our_joern_edge_count", 0)
                n_valid = r.get("valid_edge_count", 0)
                print(f"      Joern DDG edges found: {n_found}  |  GT valid DDG edges: {n_valid}  |  "
                      f"TP={r['our']['tp']} FP={r['our']['fp']} FN={r['our']['fn']}")
                for e in r.get("our_joern_edges", []):
                    out_line = e["node_out"].rstrip()[:80]
                    in_line  = e["node_in"].rstrip()[:80]
                    print(f"        DDG  {out_line!r}  →  {in_line!r}")

        agg = aggregate_results(per_entry_results)
        agg["prompt"]  = letter
        agg["dataset"] = dataset_name

        results_path = RESULTS_DIR / f"results_{letter}.jsonl"
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(agg) + "\n")
            for r in per_entry_results:
                f.write(json.dumps(r) + "\n")

        print(f"\n  === Prompt {letter} Aggregate ({dataset_name.upper()}) ===")
        print(f"  Our pipeline:    "
              f"P={agg['our_metrics']['precision']}%  "
              f"R={agg['our_metrics']['recall']}%  "
              f"F1={agg['our_metrics']['f1']}%  "
              f"(n={agg['n_evaluated']}, joern_failed={agg['n_joern_failed']}, "
              f"parse_failed={agg['n_parse_failed']}, "
              f"skipped_no_valid_edges={agg['n_no_valid_edges']})")
        print(f"  Original PrePA:  "
              f"P={agg['prepa_metrics']['precision']}%  "
              f"R={agg['prepa_metrics']['recall']}%  "
              f"F1={agg['prepa_metrics']['f1']}%")
        print(f"  Saved → {results_path}")
        print(f"  Note: {agg['metric_note']}")

    print()


if __name__ == "__main__":
    main()
