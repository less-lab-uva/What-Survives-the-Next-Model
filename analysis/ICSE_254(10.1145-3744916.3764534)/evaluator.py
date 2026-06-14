import argparse
import ast
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR / "dataset"
SF_DATASET_FILE = DATASET_DIR / "defects4j-sf.json"
MF_DATASET_FILE = DATASET_DIR / "defects4j-mf.json"
BUG_LIST_FILE = DATASET_DIR / "bug_list_d4j.txt"
VALIDATION_DIR = BASE_DIR / "evaluator_utils" / "validation"


def parse_bug_list():
    text = BUG_LIST_FILE.read_text(encoding="utf-8")
    raw_lists = re.findall(r"\[[^\]]*\]", text)
    if len(raw_lists) < 4:
        raise ValueError(f"Expected four bug ID lists in {BUG_LIST_FILE}")
    parsed = [ast.literal_eval(raw) for raw in raw_lists[:4]]
    return {
        ("v1.2", "sf"): set(parsed[0]),
        ("v1.2", "mf"): set(parsed[1]),
        ("v2.0", "sf"): set(parsed[2]),
        ("v2.0", "mf"): set(parsed[3]),
    }


def load_datasets():
    with open(SF_DATASET_FILE) as f:
        sf_data = json.load(f)
    with open(MF_DATASET_FILE) as f:
        mf_data = json.load(f)
    return sf_data, mf_data


def infer_record_split(record: dict, bug_lists: dict, sf_data: dict, mf_data: dict):
    bug_id = record["bug_id"]
    benchmark = record.get("version") or record.get("benchmark")
    scenario = record.get("scenario")

    if not scenario:
        scenario = "sf" if bug_id in sf_data else "mf" if bug_id in mf_data else None
    if not benchmark and scenario:
        for bench in ("v1.2", "v2.0"):
            if bug_id in bug_lists.get((bench, scenario), set()):
                benchmark = bench
                break
    return benchmark, scenario


def _d4j_command(cmd, timeout=90):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return "TIMEOUT", "TIMEOUT"
    return out, err


def _d4j_checkout(bug_id: str, proj_dir: str):
    project, num = bug_id.split("-")
    subprocess.run(
        f"defects4j checkout -p {project} -v {num}b -w {proj_dir}",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _d4j_test_suite(proj_dir: str, timeout: int = 1000):
    cwd = os.getcwd()
    os.chdir(proj_dir)
    out, err = _d4j_command(["defects4j", "test", "-r"], timeout)
    os.chdir(cwd)
    return out, err


def _d4j_export(proj_dir: str, prop: str, timeout: int = 90):
    cwd = os.getcwd()
    os.chdir(proj_dir)
    out, err = _d4j_command(["defects4j", "export", "-p", prop], timeout)
    os.chdir(cwd)
    return out, err


def _d4j_test_one(proj_dir: str, test_case: str, timeout: int = 100):
    cwd = os.getcwd()
    os.chdir(proj_dir)
    out, err = _d4j_command(["defects4j", "test", "-t", test_case], timeout)
    os.chdir(cwd)
    return out, err


def _d4j_result(out: str, err: str, stage: str) -> str:
    if "TIMEOUT" in out or "TIMEOUT" in err:
        return f"{stage.upper()}_TIMEOUT"
    if "FAIL" in out or "FAIL" in err or "Compilation failed" in out or "Compilation failed" in err:
        return "UNCOMPILABLE"
    if "Failing tests: 0" in out:
        return "PLAUSIBLE"
    return f"{stage.upper()}_ERROR"


def _read_lines(path: str):
    try:
        encoding = "utf-8"
        with open(path, "r", encoding=encoding) as f:
            return encoding, f.readlines()
    except UnicodeDecodeError:
        encoding = "ISO-8859-1"
        with open(path, "r", encoding=encoding) as f:
            return encoding, f.readlines()


def _remove_class_files(proj_dir: str, touched_files):
    for source_path in touched_files:
        rm_cls = os.path.basename(source_path).replace(".java", ".class")
        for cls_file in Path(proj_dir).rglob(rm_cls):
            cls_file.unlink()
            break


def _apply_sf_patch(proj_dir: str, bug_info: dict, fixed_function: str):
    buggy_file = os.path.join(proj_dir, bug_info["loc"])
    encoding, lines = _read_lines(buggy_file)
    start_loc, end_loc = bug_info["start"], bug_info["end"]
    patched = lines[: start_loc - 1] + [fixed_function.strip() + "\n"] + lines[end_loc:]
    with open(buggy_file, "w", encoding=encoding, errors="ignore") as f:
        f.writelines(patched)
    return [buggy_file]


def _apply_mf_patch(proj_dir: str, bug_info: dict, fixed_functions: dict):
    touched_files = []
    shifts = {}
    for idx, function_edit in enumerate(bug_info["functions"], start=1):
        function_id = str(idx)
        patch = fixed_functions.get(function_id)
        if not isinstance(patch, str) or not patch.strip():
            raise ValueError(f"missing fixed_functions[{function_id}]")

        rel_path = function_edit["path"]
        shifts.setdefault(rel_path, 0)
        start_loc = function_edit["start_loc"] + shifts[rel_path]
        end_loc = function_edit["end_loc"] + shifts[rel_path]
        replacement = patch.strip() + "\n"
        patch_line_cnt = replacement.count("\n")
        shifts[rel_path] += patch_line_cnt - (function_edit["end_loc"] - function_edit["start_loc"] + 1)

        buggy_file = os.path.join(proj_dir, rel_path)
        encoding, lines = _read_lines(buggy_file)
        patched = lines[: start_loc - 1] + [replacement] + lines[end_loc:]
        with open(buggy_file, "w", encoding=encoding, errors="ignore") as f:
            f.writelines(patched)
        touched_files.append(buggy_file)
    return touched_files


def run_d4j_validation(record: dict, sf_data: dict, mf_data: dict) -> Optional[str]:
    if not shutil.which("defects4j"):
        print("  WARNING: defects4j not found in PATH; skipping validation")
        return "NO_D4J"

    bug_id = record["bug_id"]
    scenario = record.get("scenario") or ("sf" if bug_id in sf_data else "mf")
    dataset = sf_data if scenario == "sf" else mf_data
    if bug_id not in dataset:
        print(f"  WARNING: {bug_id} not found in {scenario} dataset")
        return None

    tmp_dir = f"/tmp/llm4apr_validation/{bug_id}"
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    try:
        print(f"  Checking out {bug_id}...")
        _d4j_checkout(bug_id, tmp_dir)

        trigger_out, _ = _d4j_export(tmp_dir, "tests.trigger")
        trigger_tests = [t.strip() for t in trigger_out.strip().split("\n") if t.strip()]
        if not trigger_tests:
            print("  WARNING: no trigger tests found for buggy version")
            return "UNKNOWN"

        try:
            if scenario == "sf":
                fixed = record.get("predicted_fix", "")
                if not fixed:
                    return "BAD_PATCH_FORMAT"
                touched = _apply_sf_patch(tmp_dir, dataset[bug_id], fixed)
            else:
                fixed_functions = record.get("predicted_fixes") or {}
                if isinstance(fixed_functions, list):
                    fixed_functions = {str(idx): value for idx, value in enumerate(fixed_functions, start=1)}
                if not isinstance(fixed_functions, dict) or not fixed_functions:
                    return "BAD_PATCH_FORMAT"
                touched = _apply_mf_patch(tmp_dir, dataset[bug_id], fixed_functions)
            _remove_class_files(tmp_dir, touched)
        except Exception as exc:
            print(f"  WARNING: failed to apply patch for {bug_id}: {exc}")
            return "BAD_PATCH_FORMAT"

        status = "UNVERIFIED"
        for trigger in trigger_tests:
            if status in ("UNVERIFIED", "PLAUSIBLE"):
                out, err = _d4j_test_one(tmp_dir, trigger)
                status = _d4j_result(out, err, "trigger")

        if status == "PLAUSIBLE":
            out, err = _d4j_test_suite(tmp_dir)
            status = _d4j_result(out, err, "relevant")

        if status == "PLAUSIBLE":
            plausible_dir = VALIDATION_DIR / f"{scenario}-plausible"
            plausible_dir.mkdir(parents=True, exist_ok=True)
            patch_code = record.get("predicted_fix") if scenario == "sf" else record.get("predicted_fixes")
            (plausible_dir / f"{bug_id}-plausible.json").write_text(
                json.dumps([{"patch_code": patch_code, "bug_name": bug_id}], indent=2)
            )

        print(f"  [PATCH STATUS] | {bug_id:20} | {status:16} |")
        return status
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _empty_bucket():
    return {
        "total": 0,
        "validated": 0,
        "plausible_count": 0,
        "statuses": {},
    }


def _add_result(bucket: dict, record: dict):
    bucket["total"] += 1
    status = record.get("patch_status")
    if status is not None:
        bucket["validated"] += 1
    if status == "PLAUSIBLE":
        bucket["plausible_count"] += 1
    bucket["statuses"][status] = bucket["statuses"].get(status, 0) + 1


def build_aggregate(results):
    aggregate = {
        "overall": _empty_bucket(),
        "by_version": {},
        "by_project": {},
        "by_scenario": {},
    }
    for result in results:
        benchmark = result.get("version") or result.get("benchmark") or "unknown"
        project = result["bug_id"].split("-")[0]
        scenario = result.get("scenario") or "unknown"
        aggregate["by_version"].setdefault(benchmark, _empty_bucket())
        aggregate["by_project"].setdefault(benchmark, {}).setdefault(project, _empty_bucket())
        aggregate["by_scenario"].setdefault(benchmark, {}).setdefault(scenario, _empty_bucket())

        _add_result(aggregate["overall"], result)
        _add_result(aggregate["by_version"][benchmark], result)
        _add_result(aggregate["by_project"][benchmark][project], result)
        _add_result(aggregate["by_scenario"][benchmark][scenario], result)
    return aggregate


def print_table3_summary(aggregate: dict):
    print("\nTABLE 3-STYLE SUMMARY (plausible)")
    for benchmark in sorted(aggregate["by_project"]):
        print(f"\n#Total (D4J {benchmark}): "
              f"{aggregate['by_version'][benchmark]['plausible_count']}")
        for project in sorted(aggregate["by_project"][benchmark]):
            bucket = aggregate["by_project"][benchmark][project]
            print(f"  {project:16} {bucket['plausible_count']}"
                  f"  total={bucket['total']} validated={bucket['validated']}")


def _load_progress(progress_path: Path) -> dict:
    statuses = {}
    if not progress_path.exists():
        return statuses
    with open(progress_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            bug_id = entry.get("bug_id")
            status = entry.get("patch_status")
            if bug_id is not None and status is not None:
                statuses[bug_id] = status
    return statuses


def _append_progress(progress_path: Path, bug_id: str, status):
    with open(progress_path, "a") as f:
        f.write(json.dumps({"bug_id": bug_id, "patch_status": status}) + "\n")


def evaluate_prompt(args, prompt_label: str, sf_data: dict, mf_data: dict, bug_lists: dict):
    outputs_path = BASE_DIR / "outputs" / f"outputs_{prompt_label}.jsonl"
    if args.outputs_file:
        outputs_path = Path(args.outputs_file)
    if not outputs_path.exists():
        print(f"ERROR: outputs file not found: {outputs_path}")
        return

    records = []
    with open(outputs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            benchmark, scenario = infer_record_split(rec, bug_lists, sf_data, mf_data)
            rec["version"] = benchmark
            rec["benchmark"] = benchmark
            rec["scenario"] = scenario
            records.append(rec)

    results_dir = BASE_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    progress_path = results_dir / f"results_{prompt_label}.progress.jsonl"

    statuses = [None] * len(records)
    pending_indices = list(range(len(records)))

    done_status = _load_progress(progress_path)
    if done_status:
        pending_indices = []
        for i, rec in enumerate(records):
            status = done_status.get(rec["bug_id"])
            if status is not None:
                statuses[i] = status
            else:
                pending_indices.append(i)
        print(f"Resuming from {progress_path}: {len(records) - len(pending_indices)} of "
              f"{len(records)} records already validated, {len(pending_indices)} remaining")

    print(f"Evaluating {len(records)} records from {outputs_path} (prompt {prompt_label}) "
          f"| workers={args.workers}")

    if args.workers <= 1:
        for n, i in enumerate(pending_indices):
            rec = records[i]
            print(f"\n[{n+1}/{len(pending_indices)}] {rec['bug_id']} {rec['benchmark']} {rec['scenario']}")
            statuses[i] = run_d4j_validation(rec, sf_data, mf_data)
            _append_progress(progress_path, rec["bug_id"], statuses[i])
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_idx = {
                executor.submit(run_d4j_validation, records[i], sf_data, mf_data): i
                for i in pending_indices
            }
            done = 0
            for future in as_completed(future_to_idx):
                i = future_to_idx[future]
                rec = records[i]
                done += 1
                try:
                    statuses[i] = future.result()
                except Exception as exc:
                    print(f"  ERROR validating {rec['bug_id']}: {exc}")
                    statuses[i] = "ERROR"
                _append_progress(progress_path, rec["bug_id"], statuses[i])
                print(f"[{done}/{len(pending_indices)}] {rec['bug_id']} {rec['benchmark']} {rec['scenario']} "
                      f"-> {statuses[i]}")

    results = [{**rec, "patch_status": status} for rec, status in zip(records, statuses)]

    aggregate = build_aggregate(results)
    print_table3_summary(aggregate)

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for result in results:
            f.write(json.dumps(result) + "\n")
    print(f"\nFull results saved to: {out_path}")

    if progress_path.exists():
        progress_path.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--outputs-file", type=str, default=None)
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of bugs to validate concurrently (each uses an isolated checkout dir)")
    args = parser.parse_args()

    sf_data, mf_data = load_datasets()
    bug_lists = parse_bug_list()
    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for prompt_label in prompt_labels:
        evaluate_prompt(args, prompt_label, sf_data, mf_data, bug_lists)


if __name__ == "__main__":
    main()
