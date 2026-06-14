import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def _count_meaningful_lines(code: str) -> list:
    lines = code.split("\n")
    line_numbers = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        if stripped.startswith("@"):
            continue
        if stripped == "pass":
            continue
        if stripped == "return" or stripped == "return None":
            continue
        if stripped in ["{", "}", "[", "]", "(", ")"]:
            continue
        current_indent = len(line) - len(line.lstrip())
        is_continuation = False
        if i > 0:
            prev_line = lines[i - 1].strip()
            prev_indent = len(lines[i - 1]) - len(lines[i - 1].lstrip())
            if (prev_line.endswith((",", "(", "[", "{", "\\"))
                    and current_indent > prev_indent):
                is_continuation = True
        if not is_continuation:
            line_numbers.append(i + 1)
    return line_numbers


def measure_coverage(tests: list, source_file_abs: Path, package_root: Optional[Path],
                     timeout: int = 30) -> dict:
    env = os.environ.copy()
    if package_root:
        env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")

    lines_covered = 0
    total_lines = 0
    branches_covered = 0
    branches_total = 0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            sc_json = tmp / "slipcover.json"
            for j, test_str in enumerate(tests):
                (tmp / f"test_{j}.py").write_text(test_str, encoding="utf-8")
            run_cwd = package_root if package_root else tmp
            try:
                subprocess.run(
                    [sys.executable, "-m", "slipcover",
                     "--branch", "--json", f"--out={sc_json}",
                     f"--source={source_file_abs.parent}",
                     "-m", "pytest", str(tmp),
                     "-q", "--tb=no", "--no-header"],
                    capture_output=True, text=True, timeout=timeout * max(len(tests), 1),
                    env=env, cwd=str(run_cwd),
                )
            except (subprocess.TimeoutExpired, Exception):
                pass
            if sc_json.exists():
                data = json.loads(sc_json.read_text())
                for fname, fdata in data.get("files", {}).items():
                    if (run_cwd / fname).resolve() == source_file_abs.resolve():
                        executed_lines = set(fdata.get("executed_lines", []))
                        missing_lines = set(fdata.get("missing_lines", []))
                        lines_covered = len(executed_lines)
                        total_lines = len(executed_lines | missing_lines)
                        s = fdata.get("summary", {})
                        branches_covered = s.get("covered_branches", 0)
                        missing_b = s.get("missing_branches", 0)
                        branches_total = branches_covered + missing_b
                        break
    except Exception:
        pass

    line_rate   = lines_covered / total_lines if total_lines > 0 else 0.0
    branch_rate = branches_covered / branches_total if branches_total > 0 else 0.0

    return {
        "line_rate":        round(line_rate,   4),
        "branch_rate":      round(branch_rate, 4),
        "lines_covered":    lines_covered,
        "lines_total":      total_lines,
        "branches_covered": branches_covered,
        "branches_total":   branches_total,
    }


def evaluate_prompt(prompt_label: str, n: Optional[int], timeout: int):
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

    if n is not None:
        records = records[:n]

    print(f"Measuring coverage for {len(records)} modules (prompt {prompt_label})...")
    results = []
    for i, rec in enumerate(records):
        print(f"\n[{i+1}/{len(records)}] {rec['id']}")
        source_file_abs = Path(rec["source_file_abs"])
        source_file_rel = Path(rec["source_file"])
        repo_dir = source_file_abs.parents[len(source_file_rel.parts) - 1]
        package_root = repo_dir / "codamosa" / "replication" / rec["d"]
        tests = rec.get("tests", [])

        cov = measure_coverage(tests, source_file_abs, package_root, timeout)
        print(f"  Line coverage  : {cov['line_rate']:.1%}  ({cov.get('lines_covered','?')}/{cov.get('lines_total','?')})")
        print(f"  Branch coverage: {cov['branch_rate']:.1%}  ({cov.get('branches_covered','?')}/{cov.get('branches_total','?')})")
        results.append({**rec, "coverage": cov})

    total = len(results)
    valid = [r for r in results if "error" not in r["coverage"]]

    def _micro(records):
        tot_lines    = sum(r["coverage"].get("lines_total",      0) for r in records)
        cov_lines    = sum(r["coverage"].get("lines_covered",    0) for r in records)
        tot_branches = sum(r["coverage"].get("branches_total",   0) for r in records)
        cov_branches = sum(r["coverage"].get("branches_covered", 0) for r in records)
        line_rate   = cov_lines    / tot_lines    if tot_lines    > 0 else 0.0
        branch_rate = cov_branches / tot_branches if tot_branches > 0 else 0.0
        lb_rate     = (cov_lines + cov_branches) / (tot_lines + tot_branches) \
                      if (tot_lines + tot_branches) > 0 else 0.0
        return round(line_rate, 4), round(branch_rate, 4), round(lb_rate, 4)

    avg_line, avg_branch, avg_line_branch = _micro(valid)

    SIZE_BANDS = [
        ("low",  0,    150),
        ("mid",  151,  500),
        ("high", 501, 1100),
    ]

    def _band_stats(records, lo, hi):
        grp = [r for r in records if lo <= r["coverage"].get("lines_total", 0) <= hi]
        if not grp:
            return {"line": 0.0, "branch": 0.0, "line_branch": 0.0, "n": 0}
        line_r, branch_r, lb_r = _micro(grp)
        return {"line": line_r, "branch": branch_r, "line_branch": lb_r, "n": len(grp)}

    stratified = {
        name: _band_stats(valid, lo, hi)
        for name, lo, hi in SIZE_BANDS
    }

    print(f"\n{'='*55}")
    print(f"SUMMARY — Prompt {prompt_label} — {total} modules")
    print(f"  Line coverage        : {avg_line:.1%}")
    print(f"  Branch coverage      : {avg_branch:.1%}")
    print(f"  Line+Branch coverage : {avg_line_branch:.1%}")
    print(f"  Paper reports (TestWeaver best): 68% line, 62% branch, 66% line+branch")
    print(f"\n  Stratified by file size (lines):")
    print(f"  {'Band':<6}  {'N':>4}  {'Line':>6}  {'Branch':>8}  {'L+B':>6}")
    for name, lo, hi in SIZE_BANDS:
        s = stratified[name]
        print(f"  {name:<6}  {s['n']:>4}  {s['line']:>6.1%}  {s['branch']:>8.1%}  {s['line_branch']:>6.1%}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {
        "line_coverage":        avg_line,
        "branch_coverage":      avg_branch,
        "line_branch_coverage": avg_line_branch,
        "total":                total,
        "total_llm_time":       round(sum(r.get("llm_response_time", 0.0) for r in results), 3),
        "stratified_by_size":   stratified,
    }
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"Full results saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt",  choices=["A", "B", "both"], default="both")
    parser.add_argument("--n",       type=int, default=None)
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n, args.timeout)


if __name__ == "__main__":
    main()
