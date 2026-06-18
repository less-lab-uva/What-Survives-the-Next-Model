import os
import sys
import json
import subprocess
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

JAVATUPLES_JAR = os.path.join(BASE_DIR, "javatuples-1.2.jar")
if not os.path.exists(JAVATUPLES_JAR):
    raise FileNotFoundError(
        f"javatuples jar not found: {JAVATUPLES_JAR}\n"
        f"Run: wget https://repo1.maven.org/maven2/org/javatuples/javatuples/1.2/javatuples-1.2.jar -P {BASE_DIR}"
    )


# ── Java execution ────────────────────────────────────────────────────────────

def run_java(full_source: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        java_path = os.path.join(tmpdir, "Problem.java")
        classpath = f"{tmpdir}:{JAVATUPLES_JAR}"

        with open(java_path, "w") as f:
            f.write(full_source)

        # -- Compile --
        compile_result = subprocess.run(
            ["javac", "-cp", classpath, java_path],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        if compile_result.returncode != 0:
            return {
                "pass@1": 0,
                "stage" : "compile",
                "error" : compile_result.stderr.strip(),
            }

        # -- Run --
        run_result = subprocess.run(
            ["java", "-ea", "-cp", classpath, "Problem"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
            timeout=10,
        )
        if run_result.returncode != 0:
            return {
                "pass@1": 0,
                "stage" : "run",
                "error" : run_result.stderr.strip(),
            }

        return {
            "pass@1": 1,
            "stage" : None,
            "error" : "",
        }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python evaluator.py <A|B>")
        sys.exit(1)

    variant = sys.argv[1].upper()
    results_path = os.path.join(BASE_DIR, "outputs", f"outputs_{variant}.json")

    if not os.path.exists(results_path):
        print(f"ERROR: results file not found: {results_path}")
        sys.exit(1)

    with open(results_path) as f:
        all_results = json.load(f)

    total        = len(all_results)
    n_passed     = 0
    n_failed     = 0
    n_skipped    = 0   # api_error or parse_failure — no code to evaluate
    n_timeout    = 0

    print(f"Evaluating {total} instances from: {results_path}")
    print(f"{'='*60}")

    eval_records = []

    for r in all_results:
        index = r["instance_index"]
        name  = r["instance_name"]

        # -- Skip instances where LLM failed --
        if r["api_error"] or r["parse_failure"]:
            print(f"[{index:3d}] {name}")
            print(f"       SKIPPED — {'api_error' if r['api_error'] else 'parse_failure'}")
            n_skipped += 1
            eval_records.append({
                "instance_index": index,
                "instance_name" : name,
                "dataset"       : r.get("dataset", ""),
                "pass@1"        : None,
                "stage"         : None,
                "error"         : "skipped — no generated code",
            })
            continue

        full_source = r.get("evaluation", {}).get("full_source", "")
        if not full_source:
            print(f"[{index:3d}] {name}")
            print(f"       SKIPPED — no full_source in evaluation field")
            n_skipped += 1
            eval_records.append({
                "instance_index": index,
                "instance_name" : name,
                "dataset"       : r.get("dataset", ""),
                "pass@1"        : None,
                "stage"         : None,
                "error"         : "skipped — full_source missing",
            })
            continue

        # -- Compile and run --
        try:
            result = run_java(full_source)
        except subprocess.TimeoutExpired:
            print(f"[{index:3d}] {name}")
            print(f"       TIMEOUT")
            n_timeout += 1
            n_failed += 1
            eval_records.append({
                "instance_index": index,
                "instance_name" : name,
                "dataset"       : r.get("dataset", ""),
                "pass@1"        : 0,
                "stage"         : "run",
                "error"         : "timeout — execution exceeded 10 seconds",
            })
            continue

        # -- Report --
        status = "PASS" if result["pass@1"] == 1 else f"FAIL ({result['stage']})"
        print(f"[{index:3d}] {name}")
        print(f"       {status}")
        if result["error"]:
            # Print first line of error only to keep output readable
            first_line = result["error"].splitlines()[0]
            print(f"       {first_line}")

        if result["pass@1"] == 1:
            n_passed += 1
        else:
            n_failed += 1

        eval_records.append({
            "instance_index": index,
            "instance_name" : name,
            "dataset"       : r.get("dataset", ""),
            "pass@1"        : result["pass@1"],
            "stage"         : result["stage"],
            "error"         : result["error"],
        })

    # -- Compute average pass@1 --
    # A timeout is an evaluated attempt and counts as a failed solution.
    evaluated = n_passed + n_failed
    avg_pass1 = n_passed / evaluated if evaluated > 0 else 0.0

    # -- Save evaluation output --
    eval_output = {
        "results_file"  : results_path,
        "total"         : total,
        "evaluated"     : evaluated,
        "passed"        : n_passed,
        "failed"        : n_failed,
        "skipped"       : n_skipped,
        "timeout"       : n_timeout,
        "pass@1"        : round(avg_pass1, 4),
        "instances"     : eval_records,
    }

    results_dir = os.path.join(BASE_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)
    eval_path = os.path.join(results_dir, f"results_{variant}.json")
    with open(eval_path, "w") as f:
        json.dump(eval_output, f, indent=2)

    # -- Summary --
    print(f"\n{'='*60}")
    print(f"  EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Input file      : {results_path}")
    print(f"  Total instances : {total}")
    print(f"  Evaluated       : {evaluated}")
    print(f"  Passed          : {n_passed}")
    print(f"  Failed          : {n_failed}")
    print(f"  Skipped         : {n_skipped}")
    print(f"  Timeout         : {n_timeout}")
    print(f"")
    print(f"  pass@1          : {avg_pass1:.4f}  ({n_passed}/{evaluated})")
    print(f"")
    print(f"  Evaluation saved: {eval_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
