"""Pass@1 / AvgPassRatio for the code-generation oracle (RQ1).

For each prediction in outputs/output_<variant>.jsonl ({dataset, problem_id, code}), run the program
against that problem's `all_test_cases` (stdin -> stdout, compared per test), joined by
(dataset, problem_id). Per problem:
    pass_ratio = (tests passed) / (total tests)
Aggregated per (variant, dataset) and overall:
    Pass@1       = fraction of problems whose program passes ALL tests (pass_ratio == 1.0)
    AvgPassRatio = mean pass_ratio over problems
Writes results/results_<variant>.json.

Test cases come from the input files (inputs/*.jsonl — verbatim records keep `all_test_cases`).
Output entries may be a string or a list of lines; both are normalized before comparison.

⚠️ This EXECUTES untrusted, LLM-generated code as subprocesses (with a per-test timeout). Run it
inside a container/sandbox. Static otherwise — no third-party deps.

Run from the analysis directory:  python3 evaluator.py
"""

import os
import sys
import json
import glob
import subprocess
from collections import defaultdict

TIMEOUT = 10            # seconds per test case
RESULTS_DIR = "results"


def expected_str(o) -> str:
    return ("\n".join(o) if isinstance(o, list) else str(o)).strip()


def run_program(code: str, stdin: str) -> str:
    """Run code with stdin; return stdout, or None on timeout/crash."""
    try:
        r = subprocess.run([sys.executable, "-c", code], input=stdin,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.stdout
    except (subprocess.TimeoutExpired, Exception):
        return None


def pass_ratio(code: str, all_test_cases: dict) -> float:
    ins = all_test_cases.get("inputs", [])
    outs = all_test_cases.get("outputs", [])
    if not ins:
        return 0.0
    passed = 0
    for stdin, exp in zip(ins, outs):
        got = run_program(code, stdin)
        if got is not None and got.strip() == expected_str(exp):
            passed += 1
    return passed / len(ins)


# Index test cases by (dataset, problem_id) from every input file.
tests = {}
for f in glob.glob("inputs/*.jsonl"):
    ds = os.path.basename(f).split(".")[0]
    for line in open(f, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            tests[(ds, r["problem_id"])] = r["all_test_cases"]

out_files = sorted(glob.glob("outputs/output_*.jsonl"))
if not out_files:
    sys.exit("ABORT: no outputs/output_*.jsonl (run main.py first)")
os.makedirs(RESULTS_DIR, exist_ok=True)

for out_path in out_files:
    variant = os.path.basename(out_path)[len("output_"):-len(".jsonl")]
    by_dataset = defaultdict(list)        # dataset -> [pass_ratio, ...]
    missing = 0
    preds = [json.loads(l) for l in open(out_path, encoding="utf-8") if l.strip()]
    print(f"\n=== scoring {out_path} ({len(preds)} predictions) ===")
    for p in preds:
        key = (p["dataset"], p["problem_id"])
        tc = tests.get(key)
        if tc is None:
            missing += 1
            continue
        pr = pass_ratio(p["code"], tc)
        by_dataset[p["dataset"]].append(pr)
        print(f"  {p['dataset']} {p['problem_id']}: pass_ratio={pr:.3f}{'  ✓' if pr == 1.0 else ''}")

    per_dataset, all_pr = {}, []
    for ds, prs in sorted(by_dataset.items()):
        per_dataset[ds] = {"n": len(prs),
                           "pass_at_1": round(sum(1 for x in prs if x == 1.0) / len(prs), 4),
                           "avg_pass_ratio": round(sum(prs) / len(prs), 4)}
        all_pr.extend(prs)
    overall = {"n": len(all_pr),
               "pass_at_1": round(sum(1 for x in all_pr if x == 1.0) / len(all_pr), 4) if all_pr else 0.0,
               "avg_pass_ratio": round(sum(all_pr) / len(all_pr), 4) if all_pr else 0.0}

    print(f"  [{variant}] per-dataset: " + "  ".join(
        f"{ds}: P@1={d['pass_at_1']} APR={d['avg_pass_ratio']} (n={d['n']})" for ds, d in per_dataset.items()))
    print(f"  [{variant}] OVERALL: Pass@1={overall['pass_at_1']}  AvgPassRatio={overall['avg_pass_ratio']}"
          + (f"  (⚠ {missing} predictions had no test case)" if missing else ""))

    out = os.path.join(RESULTS_DIR, f"results_{variant}.json")
    json.dump({"metric": "Pass@1 / AvgPassRatio (run generated program vs all_test_cases, stdin->stdout)",
               "prompt_variant": variant, "per_dataset": per_dataset, "overall": overall,
               "predictions_without_tests": missing}, open(out, "w"), indent=2)
    print(f"  saved {out}")
