"""
Panta — evaluator: run Maven + JaCoCo coverage on generated JUnit tests.
Usage: python evaluator.py --variant <A|B|both>
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl

Requires Maven and Java on PATH:
  module load maven/3.9.0 java/8
  python evaluator.py --variant both
"""

import argparse
import csv
import glob
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

HERE     = Path(__file__).parent
SUBJ_DIR = HERE / "data" / "defects4j-subjects"

JUNIT4_IMPORTS = (
    "import org.junit.Before;\n"
    "import org.junit.After;\n"
    "import org.junit.Test;\n"
    "import static org.junit.Assert.*;\n"
    "import java.io.*;\n"
    "import java.util.*;\n"
    "import java.nio.charset.Charset;\n"
    "import java.nio.file.*;\n"
)


def extract_source_header(src_path):
    lines = Path(src_path).read_text(errors="replace").splitlines()
    header = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("package ") or stripped.startswith("import "):
            header.append(line)
        elif header:
            break
    return "\n".join(header)


def wrap_in_class(src_header, class_name, methods):
    return (
        f"{src_header}\n\n"
        f"{JUNIT4_IMPORTS}\n"
        f"public class {class_name}Test {{\n\n"
        f"{methods}\n\n"
        "}\n"
    )


def strip_fences(text):
    text = text.strip()
    # If model returned prose before a code block, extract the code block first
    m = re.search(r"```(?:java)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    else:
        text = re.sub(r"^```(?:java)?\s*\n?", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    if re.search(r"^\s*(package\s+\S+;|public\s+class\s+)", text, re.MULTILINE):
        first_brace = text.find("{")
        last_brace  = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            text = text[first_brace + 1:last_brace].strip()
    else:
        last = text.rfind("\n}")
        if last != -1:
            text = text[:last + 2]
    return text


def find_test_dir(src_path):
    p = Path(src_path)
    parts = list(p.parts)
    try:
        main_idx = parts.index("main")
        parts[main_idx] = "test"
        return Path(*parts).parent
    except ValueError:
        return p.parent


def run_maven(project_dir, test_class_name, clean=True):
    phases = ["clean", "test"] if clean else ["test"]
    cmd = ["mvn"] + phases + [f"-Dtest={test_class_name}",
                               "-Dmaven.test.failure.ignore=true", "-q"]
    try:
        result = subprocess.run(cmd, cwd=project_dir,
                                capture_output=True, text=True, timeout=300)
        stderr = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0:
            if "COMPILATION ERROR" in stderr or "cannot find symbol" in stderr:
                return False, f"compilation failed: {stderr[-300:]}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "mvn not found — run: module load maven/3.9.0 java/8"
    except Exception as e:
        return False, str(e)


def parse_jacoco_csv(project_dir, class_name):
    csv_path = Path(project_dir) / "target" / "jacoco" / "jacoco.csv"
    if not csv_path.exists():
        return None, None, "jacoco.csv not found"
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if row["CLASS"] == class_name:
                lm = int(row["LINE_MISSED"])
                lc = int(row["LINE_COVERED"])
                bm = int(row["BRANCH_MISSED"])
                bc = int(row["BRANCH_COVERED"])
                line_cov   = round(100 * lc / (lm + lc), 1) if (lm + lc) > 0 else 0.0
                branch_cov = round(100 * bc / (bm + bc), 1) if (bm + bc) > 0 else None
                return line_cov, branch_cov, None
    return None, None, f"{class_name} not found in jacoco.csv"


def parse_surefire_xml(project_dir, test_class_name):
    """Return (tests_run, tests_passed) from Surefire XML report."""
    pattern = str(Path(project_dir) / "target" / "surefire-reports" / f"TEST-*{test_class_name}.xml")
    matches = glob.glob(pattern)
    if not matches:
        return None, None
    try:
        root = ET.parse(matches[0]).getroot()
        total    = int(root.get("tests",    0))
        failures = int(root.get("failures", 0))
        errors   = int(root.get("errors",   0))
        skipped  = int(root.get("skipped",  0))
        passed   = max(0, total - failures - errors - skipped)
        return total, passed
    except Exception:
        return None, None


def load_done_results(path):
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "project" in r and "class" in r:
            done.add((r["project"], r["class"]))
    return done


def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def print_project_table(per_instance):
    by_proj = defaultdict(list)
    for r in per_instance:
        by_proj[r["project"]].append(r)

    print(f"\n{'Project':<25} {'#Cls':>4}  {'Line%':>6}  {'Branch%':>8}  {'Pass%':>6}")
    print("-" * 58)
    for proj in sorted(by_proj):
        rows = by_proj[proj]
        lc = avg([r.get("line_coverage")   for r in rows])
        bc = avg([r.get("branch_coverage") for r in rows])
        tr = sum(r.get("tests_run",    0) or 0 for r in rows)
        tp = sum(r.get("tests_passed", 0) or 0 for r in rows)
        pr = round(100 * tp / tr, 1) if tr > 0 else None
        lc_s = f"{lc}%" if lc is not None else "N/A"
        bc_s = f"{bc}%" if bc is not None else "N/A"
        pr_s = f"{pr}%" if pr is not None else "N/A"
        print(f"{proj:<25} {len(rows):>4}  {lc_s:>6}  {bc_s:>8}  {pr_s:>6}")
    print("-" * 58)
    lc_all = avg([r.get("line_coverage")   for r in per_instance])
    bc_all = avg([r.get("branch_coverage") for r in per_instance])
    tr_all = sum(r.get("tests_run",    0) or 0 for r in per_instance)
    tp_all = sum(r.get("tests_passed", 0) or 0 for r in per_instance)
    pr_all = round(100 * tp_all / tr_all, 1) if tr_all > 0 else None
    print(f"{'Total/Ave':<25} {len(per_instance):>4}  "
          f"{str(lc_all)+'%' if lc_all is not None else 'N/A':>6}  "
          f"{str(bc_all)+'%' if bc_all is not None else 'N/A':>8}  "
          f"{str(pr_all)+'%' if pr_all is not None else 'N/A':>6}")


def resolve_src_path(src_path, project, project_dir):
    marker = f"{project}/"
    idx = src_path.find(marker)
    if idx != -1:
        return project_dir / src_path[idx + len(marker):]
    return Path(src_path)


def eval_one(r, project_dir, out_f, per_instance, done, total_records, idx, clean=True):
    """Evaluate a single record. Returns the result row."""
    project    = r["project"]
    class_name = r["class"]
    tests_raw  = r.get("generated_tests", "")
    src_path   = str(resolve_src_path(r.get("src_path", ""), project, project_dir)) if r.get("src_path") else ""

    print(f"[{idx}/{total_records}] {project}/{class_name} ...", end=" ", flush=True)

    src_header = extract_source_header(src_path) if src_path else ""
    methods    = strip_fences(tests_raw)
    java       = wrap_in_class(src_header, class_name, methods)
    test_dir   = find_test_dir(src_path) if src_path else project_dir / "src" / "test" / "java"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file  = test_dir / f"{class_name}Test.java"
    test_file.write_text(java)

    try:
        ok, err = run_maven(project_dir, f"{class_name}Test", clean=clean)
        if not ok:
            print(f"maven FAILED: {err}")
            row = {"project": project, "class": class_name,
                   "line_coverage": None, "branch_coverage": None,
                   "tests_run": None, "tests_passed": None, "error": err}
        else:
            line_cov, branch_cov, jacoco_err = parse_jacoco_csv(project_dir, class_name)
            tests_run, tests_passed = parse_surefire_xml(project_dir, f"{class_name}Test")
            if jacoco_err:
                print(f"jacoco ERROR: {jacoco_err}")
                row = {"project": project, "class": class_name,
                       "line_coverage": None, "branch_coverage": None,
                       "tests_run": tests_run, "tests_passed": tests_passed,
                       "error": jacoco_err}
            else:
                row = {"project": project, "class": class_name,
                       "line_coverage": line_cov, "branch_coverage": branch_cov,
                       "tests_run": tests_run, "tests_passed": tests_passed,
                       "error": None}
                valid_l = [x for x in per_instance + [row] if x.get("line_coverage")   is not None]
                valid_b = [x for x in per_instance + [row] if x.get("branch_coverage") is not None]
                al = round(sum(x["line_coverage"]   for x in valid_l) / len(valid_l), 1) if valid_l else 0
                ab = round(sum(x["branch_coverage"] for x in valid_b) / len(valid_b), 1) if valid_b else 0
                tr_so_far = sum(x.get("tests_run",    0) or 0 for x in per_instance + [row])
                tp_so_far = sum(x.get("tests_passed", 0) or 0 for x in per_instance + [row])
                pr_so_far = round(100 * tp_so_far / tr_so_far, 1) if tr_so_far > 0 else 0
                bc_str = f"{branch_cov}%" if branch_cov is not None else "N/A"
                pr_str = f"{tests_passed}/{tests_run}" if tests_run is not None else "N/A"
                print(f"line={line_cov}%  branch={bc_str}  pass={pr_str}"
                      f"  |  avg_line={al}%  avg_branch={ab}%  avg_pass={pr_so_far}%  (n={len(valid_l)})")
        per_instance.append(row)
        out_f.write(json.dumps(row) + "\n")
        out_f.flush()
        return row
    finally:
        test_file.unlink(missing_ok=True)


def write_results(out_path, per_instance, in_path):
    valid_l = [r for r in per_instance if r.get("line_coverage")   is not None]
    valid_b = [r for r in per_instance if r.get("branch_coverage") is not None]
    avg_line   = round(sum(r["line_coverage"]   for r in valid_l) / len(valid_l), 1) if valid_l else None
    avg_branch = round(sum(r["branch_coverage"] for r in valid_b) / len(valid_b), 1) if valid_b else None
    tr_all = sum(r.get("tests_run",    0) or 0 for r in per_instance)
    tp_all = sum(r.get("tests_passed", 0) or 0 for r in per_instance)
    pass_rate = round(100 * tp_all / tr_all, 1) if tr_all > 0 else None

    times = [json.loads(l)["response_time"] for l in in_path.read_text().splitlines()
             if l.strip() and "response_time" in json.loads(l)]
    avg_response_time = round(sum(times) / len(times), 3) if times else None

    by_proj = defaultdict(list)
    for r in per_instance:
        by_proj[r["project"]].append(r)
    proj_agg = {}
    for proj, rows in sorted(by_proj.items()):
        lc = avg([r.get("line_coverage")   for r in rows])
        bc = avg([r.get("branch_coverage") for r in rows])
        tr = sum(r.get("tests_run",    0) or 0 for r in rows)
        tp = sum(r.get("tests_passed", 0) or 0 for r in rows)
        pr = round(100 * tp / tr, 1) if tr > 0 else None
        proj_agg[proj] = {"classes": len(rows), "avg_line": lc, "avg_branch": bc, "pass_rate": pr}

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {
            "avg_line_coverage":   avg_line,
            "avg_branch_coverage": avg_branch,
            "pass_rate":           pass_rate,
            "evaluated":           len(per_instance),
            "successful":          len(valid_l),
            "avg_response_time":   avg_response_time,
            "by_project":          proj_agg,
        }}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to evaluate (default: both)")
    args = parser.parse_args()
    variant = args.variant.upper()
    out_path_a = HERE / "results" / "results_A.jsonl"
    out_path_b = HERE / "results" / "results_B.jsonl"
    out_path_a.parent.mkdir(exist_ok=True)

    for v in ("A", "B"):
        p = HERE / "outputs" / f"outputs_{v}.jsonl"
        if p.exists():
            times = [json.loads(l)["response_time"] for l in p.read_text().splitlines()
                     if l.strip() and "response_time" in json.loads(l)]
            avg_t = sum(times) / len(times) if times else 0
            print(f"Avg response time — Prompt {v}: {avg_t:.2f}s  (n={len(times)})")
    print()

    if variant == "BOTH":
        in_a = HERE / "outputs" / "outputs_A.jsonl"
        in_b = HERE / "outputs" / "outputs_B.jsonl"
        rec_a = {(r["project"], r["class"]): r
                 for r in [json.loads(l) for l in in_a.read_text().splitlines() if l.strip()]}
        rec_b = {(r["project"], r["class"]): r
                 for r in [json.loads(l) for l in in_b.read_text().splitlines() if l.strip()]}

        done_a = load_done_results(out_path_a)
        done_b = load_done_results(out_path_b)
        all_keys = sorted(set(rec_a) | set(rec_b), key=lambda k: k[0])
        remaining = [k for k in all_keys if k not in done_a or k not in done_b]
        total = len(all_keys)
        print(f"Classes: {total}  |  Already done — A: {len(done_a)}  B: {len(done_b)}  |  To run: {len(remaining)}\n")

        existing_a = [json.loads(l) for l in (out_path_a.read_text().splitlines() if out_path_a.exists() else [])
                      if l.strip() and "project" in json.loads(l) and json.loads(l).get("line_coverage") is not None]
        existing_b = [json.loads(l) for l in (out_path_b.read_text().splitlines() if out_path_b.exists() else [])
                      if l.strip() and "project" in json.loads(l) and json.loads(l).get("line_coverage") is not None]
        per_a, per_b = list(existing_a), list(existing_b)

        with open(out_path_a, "a") as fa, open(out_path_b, "a") as fb:
            for i, key in enumerate(remaining):
                project, class_name = key
                project_dir = SUBJ_DIR / project
                if not project_dir.exists():
                    print(f"[{i+1}/{len(remaining)}] ERROR: {project} dir not found")
                    continue
                idx = len(done_a) + i + 1
                if key not in done_a and key in rec_a:
                    print(f"  [A {idx}/{total}]", end=" ")
                    eval_one(rec_a[key], project_dir, fa, per_a, done_a, total, idx, clean=True)
                if key not in done_b and key in rec_b:
                    print(f"  [B {idx}/{total}]", end=" ")
                    eval_one(rec_b[key], project_dir, fb, per_b, done_b, total, idx, clean=False)

        print("\n=== Prompt A ===")
        print_project_table(per_a)
        write_results(out_path_a, per_a, in_a)
        print("\n=== Prompt B ===")
        print_project_table(per_b)
        write_results(out_path_b, per_b, in_b)
        print(f"\nResults saved to {out_path_a} and {out_path_b}")
        return

    # Single variant
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = out_path_a if variant == "A" else out_path_b

    records   = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    done      = load_done_results(out_path)
    remaining = sorted(
        [r for r in records if (r["project"], r["class"]) not in done],
        key=lambda r: r["project"]
    )
    print(f"Loaded {len(records)} outputs  |  Already evaluated: {len(done)}  |  To run: {len(remaining)}")

    existing = [json.loads(l) for l in (out_path.read_text().splitlines() if out_path.exists() else [])
                if l.strip() and "project" in json.loads(l) and json.loads(l).get("line_coverage") is not None]
    per_instance  = list(existing)
    total_records = len(done) + len(remaining)

    with open(out_path, "a") as out_f:
        for i, r in enumerate(remaining):
            project_dir = SUBJ_DIR / r["project"]
            idx = len(done) + i + 1
            if not project_dir.exists():
                print(f"[{idx}/{total_records}] {r['project']}/{r['class']} ERROR: project dir not found")
                row = {"project": r["project"], "class": r["class"],
                       "line_coverage": None, "branch_coverage": None,
                       "tests_run": None, "tests_passed": None,
                       "error": f"project dir not found: {project_dir}"}
                per_instance.append(row)
                out_f.write(json.dumps(row) + "\n"); out_f.flush()
                continue
            eval_one(r, project_dir, out_f, per_instance, done, total_records, idx, clean=True)

    print_project_table(per_instance)
    write_results(out_path, per_instance, in_path)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
