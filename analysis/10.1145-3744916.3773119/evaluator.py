#!/usr/bin/env python3
"""
Runs Joern on Opus pipeline output files, stores PDG results, then computes
Precision / Recall / F1 comparable to the paper.

Usage:
    python3 eval_joern.py <dataset_name>

Dataset names: stattype, coster
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

import pydot
from bs4 import BeautifulSoup

PREPA_ROOT     = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER  = os.path.join(PREPA_ROOT, "output")
RESULTS_FOLDER = os.path.join(PREPA_ROOT, "results")
JOERN_PATH    = "/project/lesslab/nm8tm/joern-cli/joern-cli/bin"

ORIGINAL_FILES = {
    "stattype": os.path.join(PREPA_ROOT, "Stattype_res.json"),
    "coster":   os.path.join(PREPA_ROOT, "Coster_res.json"),
}


# ── Joern (copied from joern.py, no module-level side effects) ────────────────

def generate_prolog(code):
    if not code.strip():
        return ("Joern Failed to parse the code",) * 3 + ("Empty file",) * 2
    tmp_dir = tempfile.TemporaryDirectory()
    md5_v = hashlib.md5(code.encode()).hexdigest()
    fname = "func_" + md5_v + ".java"
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
        out_dir = os.path.join(tmp_dir.name, "output")
        pdg_list = [
            open(os.path.join(out_dir, f)).read()
            for f in sorted(os.listdir(out_dir))
            if f.endswith("-pdg.dot")
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
    dot_file   = parsed_pdg[0]  # each call receives exactly one PDG graph
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
        soup = BeautifulSoup(label_html, "html.parser")
        label_text = soup.get_text()
        if "METHOD" in label_text or "METHOD_RETURN" in label_text:
            continue
        label_html = dot_file.get_node(edge.get_source())[0].get_label()
        soup = BeautifulSoup(label_html, "html.parser")
        label_text = soup.get_text()
        if "METHOD" in label_text or "METHOD_RETURN" in label_text:
            continue
        try:
            line_in  = line_in_label[node_in]
            line_out = line_in_label[node_out]
        except Exception:
            continue
        edge_type = edge.get_label().split(":")[0].split('"')[1]
        identifier = (line_in, line_out, edge_type)
        if identifier not in nodes_in_dot:
            if int(line_in) > int(line_out):
                nodes_in_dot.add(identifier)
                unique_edges.append(
                    {"node_out": line_out, "node_in": line_in, "edge_type": edge_type}
                )
    return unique_edges


def construct_edge_with_code(code, edges):
    lines = code.splitlines(keepends=True)
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


def run_joern(code):
    """Return code_res dict or failure string."""
    try:
        pdg_list, all_dot, xml, joern_parse, joern_pdg = generate_prolog(code)
        if any("Joern Failed" in x for x in (all_dot, xml)):
            return "Joern Failed to Parse the Code"
        if not pdg_list:
            return "Joern Failed to Parse the Code"
        all_edges = []
        for pdg in pdg_list:
            try:
                block_edges = construct_pdg(pdg, all_dot, xml)
                all_edges.extend(block_edges)
            except Exception:
                continue
        edges_in_code = construct_edge_with_code(code, all_edges)
        return {
            "pdg_in_num":      all_edges,
            "pdg_in_code":     edges_in_code,
            "joern_parse_log": joern_parse,
            "joern_pdg_log":   joern_pdg,
        }
    except Exception as e:
        return f"Joern Failed: {e}"


# ── Joern processing ──────────────────────────────────────────────────────────

def process_output_file(prompt_letter, dataset_name):
    path = os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{prompt_letter}.json")
    if not os.path.exists(path):
        print(f"[!] File not found: {path}")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    processed = skipped = failed = 0
    for entry_name, entry_data in data.items():
        for variant, variant_data in entry_data.items():
            if variant == "ground_truth" or not isinstance(variant_data, dict):
                continue
            if variant_data.get("code_res") is not None:
                skipped += 1
                continue
            code = variant_data.get("approximated_code", "")
            print(f"  [{entry_name}/{variant}] ...", end=" ", flush=True)
            result = run_joern(code)
            variant_data["code_res"] = result
            if isinstance(result, str):
                print("FAILED")
                failed += 1
            else:
                print(f"OK  ({len(result.get('pdg_in_code', []))} edges)")
                processed += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  → processed={processed}  failed={failed}  skipped={skipped}")


# ── Evaluation (calculate_fp_tp_fn copied verbatim from RQ3_eval.py) ──────────

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


def compute_metrics_from_data(data, code_res_key="code_res"):
    total_tp = total_fp = total_fn = 0
    evaluated = joern_failed = 0

    for entry_name, entry_data in data.items():
        gt_res = entry_data.get("ground_truth", {}).get("ground_truth_res", {})
        if not gt_res or isinstance(gt_res, str):
            continue
        gt_pdg = gt_res.get("pdg_in_code", [])

        for variant, variant_data in entry_data.items():
            if variant == "ground_truth" or not isinstance(variant_data, dict):
                continue
            partial_code = variant_data.get("partial_code", "")
            code_res     = variant_data.get(code_res_key)

            valid_edges = [
                e for e in gt_pdg
                if e["node_out"].strip() in partial_code.strip()
                and e["node_in"].strip() in partial_code.strip()
                and e["edge_type"] == "DDG"
            ]
            if isinstance(code_res, str) or not code_res:
                joern_failed += 1
                total_fn += len(valid_edges)
                continue

            pdg_in_code = code_res.get("pdg_in_code", [])
            if not pdg_in_code:
                total_fn += len(valid_edges)
                continue

            tp, fp, fn = calculate_fp_tp_fn(pdg_in_code, valid_edges, partial_code)
            total_tp += tp
            total_fp += fp
            total_fn += fn
            evaluated += 1

    denom_p = total_tp + total_fp
    denom_r = total_tp + total_fn
    precision = total_tp / denom_p if denom_p > 0 else 0.0
    recall    = total_tp / denom_r if denom_r > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return {
        "precision":    round(precision * 100, 1),
        "recall":       round(recall    * 100, 1),
        "f1":           round(f1        * 100, 1),
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "evaluated":    evaluated,
        "joern_failed": joern_failed,
    }


def print_row(label, m):
    extra = ""
    if "evaluated" in m:
        extra = f"  (n={m['evaluated']}, joern_failed={m['joern_failed']})"
    print(f"  {label:<22}  P={m['precision']:5.1f}%  R={m['recall']:5.1f}%  F1={m['f1']:5.1f}%{extra}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 eval_joern.py <dataset_name>")
        print("Dataset names: stattype, coster")
        sys.exit(1)

    dataset_name = sys.argv[1].lower()

    # Step 1 — run Joern on prompt outputs
    for letter in ["A", "B"]:
        path = os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{letter}.json")
        if not os.path.exists(path):
            print(f"[!] Skipping Prompt {letter}: {path} not found")
            continue
        print(f"\n[*] Running Joern — Prompt {letter} ...")
        process_output_file(letter, dataset_name)

    # Step 2 — compute, print, and save results
    print("\n" + "=" * 65)
    print(f"  RESULTS — {dataset_name.upper()}")
    print("=" * 65)

    os.makedirs(RESULTS_FOLDER, exist_ok=True)

    for letter in ["A", "B"]:
        path = os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{letter}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        m = compute_metrics_from_data(data, code_res_key="code_res")
        print_row(f"Prompt {letter}", m)

        # Build per-entry rows
        per_entry = []
        for entry_name, entry_data in data.items():
            gt_res = entry_data.get("ground_truth", {}).get("ground_truth_res", {})
            if not gt_res or isinstance(gt_res, str):
                continue
            gt_pdg = gt_res.get("pdg_in_code", [])
            for variant, vdata in entry_data.items():
                if variant == "ground_truth" or not isinstance(vdata, dict):
                    continue
                partial_code = vdata.get("partial_code", "")
                code_res     = vdata.get("code_res")
                valid_edges  = [e for e in gt_pdg
                                if e["node_out"].strip() in partial_code.strip()
                                and e["node_in"].strip() in partial_code.strip()
                                and e["edge_type"] == "DDG"]
                if isinstance(code_res, str) or not code_res:
                    per_entry.append({"entry_name": entry_name, "variant": variant,
                                      "joern_failed": True, "tp": 0, "fp": 0,
                                      "fn": len(valid_edges), "precision": 0.0,
                                      "recall": 0.0, "f1": 0.0})
                    continue
                pdg = code_res.get("pdg_in_code", [])
                if not pdg:
                    per_entry.append({"entry_name": entry_name, "variant": variant,
                                      "joern_failed": False, "tp": 0, "fp": 0,
                                      "fn": len(valid_edges), "precision": 0.0,
                                      "recall": 0.0, "f1": 0.0})
                    continue
                tp, fp, fn = calculate_fp_tp_fn(pdg, valid_edges, partial_code)
                p = tp/(tp+fp) if (tp+fp) > 0 else 0.0
                r = tp/(tp+fn) if (tp+fn) > 0 else 0.0
                f = 2*p*r/(p+r) if (p+r) > 0 else 0.0
                per_entry.append({"entry_name": entry_name, "variant": variant,
                                  "joern_failed": False, "tp": tp, "fp": fp, "fn": fn,
                                  "precision": round(p*100, 1),
                                  "recall":    round(r*100, 1),
                                  "f1":        round(f*100, 1)})

        aggregate = {"prompt": letter, "dataset": dataset_name,
                     "evaluated": m["evaluated"], "joern_failed": m["joern_failed"],
                     "metrics": {"precision": m["precision"],
                                 "recall":    m["recall"],
                                 "f1":        m["f1"]},
                     "tp": m["tp"], "fp": m["fp"], "fn": m["fn"]}
        out_path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(aggregate) + "\n")
            for row in per_entry:
                f.write(json.dumps(row) + "\n")
        print(f"  [+] Saved → {out_path}")

    # Original PrePA for comparison
    orig_path = ORIGINAL_FILES.get(dataset_name)
    if orig_path and os.path.exists(orig_path):
        with open(orig_path, encoding="utf-8") as f:
            orig_data = json.load(f)
        m = compute_metrics_from_data(orig_data, code_res_key="PrePA_code_res")
        print_row("Original PrePA", m)

    print("=" * 65)


if __name__ == "__main__":
    main()
