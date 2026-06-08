"""
ReduceFix evaluator.
Reads outputs JSONL from main.py, compiles each fixed_code, runs it against the
full test suite in lftbench/tests/, and reports pass@1.

Usage:
  python evaluator.py [--prompt A|B|both] [--n N]

Input:  outputs/outputs_{P}.jsonl
Output: results/results_{P}.jsonl
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

LFTBENCH = Path(__file__).parent / "dataset" / "lftbench"


def problem_test_dir(problem_id: str) -> Optional[Path]:
    """Map e.g. 'abc367d' -> lftbench/tests/abc367/D/"""
    contest = problem_id[:-1]   # abc367
    letter  = problem_id[-1].upper()  # D
    d = LFTBENCH / "tests" / contest / letter
    return d if d.is_dir() else None


def load_test_suite(problem_id: str) -> list:
    """Return list of (input_text, expected_output_text) from the full test suite."""
    test_dir = problem_test_dir(problem_id)
    if test_dir is None:
        return []
    list_file = test_dir / "list.txt"
    if not list_file.exists():
        return []
    cases = []
    for line in list_file.read_text().splitlines():
        name = line.split(",")[0].strip()
        if not name:
            continue
        in_path  = test_dir / "in"  / name
        out_path = test_dir / "out" / name
        if in_path.exists() and out_path.exists():
            cases.append((in_path.read_text(), out_path.read_text().strip()))
    return cases


def compile_cpp(code: str, timeout: int = 15) -> Optional[Path]:
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", encoding="utf-8", delete=False) as f:
        f.write(code)
        src = Path(f.name)
    binary = src.with_suffix("")
    try:
        result = subprocess.run(
            ["g++", "-O2", "-o", str(binary), str(src)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0 and binary.exists():
            return binary
    except subprocess.TimeoutExpired:
        pass
    finally:
        src.unlink(missing_ok=True)
    return None


def run_binary(binary: Path, stdin_text: str, timeout: int = 10) -> Optional[str]:
    proc = subprocess.Popen(
        [str(binary)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        stdout, _ = proc.communicate(input=stdin_text.encode(), timeout=timeout)
        return stdout.decode(errors="replace").strip()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return None
    except Exception:
        proc.kill()
        try:
            proc.communicate()
        except Exception:
            pass
        return None


def _normalize(output: str) -> str:
    return "\n".join(line.rstrip() for line in output.splitlines()).strip()


def evaluate_fixed_code(fixed_code: str, test_cases: list) -> dict:
    """test_cases: list of (input_text, expected_output_text). Stops on first failure."""
    binary = compile_cpp(fixed_code)
    if binary is None:
        return {"compiled": False, "passed": 0, "total": len(test_cases)}
    try:
        for i, (inp, expected) in enumerate(test_cases):
            actual = run_binary(binary, inp)
            if actual is None or _normalize(actual) != _normalize(expected):
                return {"compiled": True, "passed": i, "total": len(test_cases)}
        return {"compiled": True, "passed": len(test_cases), "total": len(test_cases)}
    finally:
        binary.unlink(missing_ok=True)


def evaluate_prompt(prompt_label: str, n: int):
    outputs_path = Path(__file__).parent / "outputs" / f"outputs_{prompt_label}.jsonl"
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
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    print(f"Evaluating {len(records)} submissions (prompt {prompt_label})...")
    results = []
    for i, rec in enumerate(records):
        pid = rec["problem_id"]
        print(f"[{i+1}/{len(records)}] {pid} / {rec['submission_id']}", end="", flush=True)
        fixed_code = rec.get("fixed_code", "")
        test_cases = load_test_suite(pid)
        if not test_cases:
            print(f"  WARNING: no test suite found for {pid}")
        if fixed_code and test_cases:
            eval_result = evaluate_fixed_code(fixed_code, test_cases)
        else:
            eval_result = {"compiled": False, "passed": 0, "total": len(test_cases)}
        print(f"  compiled={eval_result['compiled']} | {eval_result['passed']}/{eval_result['total']} passed")
        results.append({**rec, "eval": eval_result})

    total        = len(results)
    fully_passed = sum(1 for r in results if r["eval"]["passed"] == r["eval"]["total"] > 0)
    pass_at_1    = round(fully_passed / total, 4) if total else 0.0
    total_time   = round(sum(r.get("llm_response_time", 0.0) for r in results), 3)

    print(f"\n{'='*50}")
    print(f"SUMMARY — Prompt {prompt_label} — {total} submissions")
    print(f"  pass@1            : {pass_at_1:.4f} ({pass_at_1*100:.1f}%)")
    print(f"  Total LLM time    : {total_time:.1f}s")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {
        "pass_at_1":      pass_at_1,
        "total":          total,
        "total_llm_time": total_time,
    }
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"Results saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n",      type=int, default=5)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
