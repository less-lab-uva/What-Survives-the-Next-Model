import os
import sys
import json
import requests
from pathlib import Path
from collections import defaultdict

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
XCODEEVAL_DIR  = Path(BASE_DIR) / "xCodeEval"
UNITTEST_FILE  = XCODEEVAL_DIR / "unittest_db.json"

EXECEVAL_URL   = "http://localhost:5000/api/execute_code"
TIMEOUT        = 30
PASS_K         = 5


LANG_MAP = {
    "GNU C":              "GNU C",
    "GNU C11":            "GNU C11",
    "GNU C++":            "GNU C++",
    "GNU C++0x":          "GNU C++0x",
    "GNU C++11":          "GNU C++11",
    "GNU C++14":          "GNU C++14",
    "GNU C++17":          "GNU C++17",
    "GNU C++17 (64)":     "GNU C++17 (64)",
    "GNU C++20 (64)":     "GNU C++20 (64)",
    "GNU C++20":          "GNU C++20",
    "GNU C++17 Diagnostics": "GNU C++17 Diagnostics",
    "Clang++17 Diagnostics": "Clang++17 Diagnostics",
    "Clang++17":          "Clang++17",
    "Clang++20 Diagnostics": "Clang++20 Diagnostics",
    "Clang++20":          "Clang++20",
    "Clang++14":          "Clang++14",
    "Clang++11":          "Clang++11",
    "MS C++":             "MS C++",
    "MS C++ 2017":        "MS C++ 2017",
    "MS C#":              "MS C#",
    "C# 10":              "C# 10",
    "C# 8":               "C# 8",
    "Mono C#":            "Mono C#",
    ".NET Core C#":       ".NET Core C#",
    "Python 2":           "Python 2",
    "PyPy 2":             "PyPy 2",
    "Python 3":           "Python 3",
    "PyPy 3":             "PyPy 3",
    "PyPy 3-64":          "PyPy 3-64",
    "Python 3 + libs":    "Python 3 + libs",
    "JavaScript":         "JavaScript",
    "Node js":            "Node js",
    "Node.js":            "Node.js",
    "Rust":               "Rust",
    "Rust 2021":          "Rust 2021",
    "Rust 2018":          "Rust 2018",
    "Rust 2015":          "Rust 2015",
    "Java 6":             "Java 6",
    "Java 7":             "Java 7",
    "Java 1.5":           "Java 1.5",
    "Java 8":             "Java 8",
    "Java 11":            "Java 11",
    "Java 17":            "Java 17",
    "PHP":                "PHP",
    "PHP 8.1":            "PHP 8.1",
    "Go":                 "Go",
    "Ruby":               "Ruby",
    "Ruby 3":             "Ruby 3",
    "Kotlin":             "Kotlin",
    "Kotlin 1.4":         "Kotlin 1.4",
    "Kotlin 1.5":         "Kotlin 1.5",
    "Kotlin 1.6":         "Kotlin 1.6",
    "Kotlin 1.7":         "Kotlin 1.7",
}


if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
    print("Usage: python evaluator_pass5.py <A|B>")
    sys.exit(1)

variant     = sys.argv[1].upper()
inputs_path = os.path.join(BASE_DIR, "outputs", f"outputs_{variant}_pass5.jsonl")
results_dir = os.path.join(BASE_DIR, "results")
output_path = os.path.join(results_dir, f"results_{variant}_pass5.jsonl")
failed_path = os.path.join(results_dir, f"failed_{variant}_pass5.json")
os.makedirs(results_dir, exist_ok=True)


print("Checking ExecEval is running...")
try:
    r = requests.get("http://localhost:5000/api/all_runtimes", timeout=5)
    runtimes = {rt["runtime_name"] for rt in r.json()}
    print(f"  ExecEval is up. {len(runtimes)} runtimes available.\n")
except Exception as e:
    print(f"  ERROR: Cannot reach ExecEval at {EXECEVAL_URL}")
    print(f"  Start it with: docker run -it -p 5000:5000 -e NUM_WORKERS=5 exec-eval:1.0")
    print(f"  Details: {e}")
    sys.exit(1)


unittest_db = {}
if UNITTEST_FILE.exists():
    print("Loading unittest_db.json ...")
    with open(UNITTEST_FILE, "r", encoding="utf-8") as f:
        unittest_db = json.load(f)
    print(f"  Loaded {len(unittest_db)} entries.\n")
else:
    print(f"  WARNING: {UNITTEST_FILE} not found.\n")


records = []
with open(inputs_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"Loaded {len(records)} candidate rows from {inputs_path}.")
print(f"Running Pass@{PASS_K} evaluation via ExecEval...\n")


def run_via_execeval(source_code, lang, test_cases):
    if not test_cases:
        return 0, 0, {"reason": "NO_TESTS_AVAILABLE"}

    runtime = LANG_MAP.get(lang)
    if runtime is None:
        return 0, len(test_cases), {"reason": f"UNKNOWN_LANG: {lang}"}

    unittests = [
        {"input": t.get("input", ""), "output": t.get("output", [])}
        for t in test_cases
    ]

    payload = {
        "language":           runtime,
        "source_code":        source_code,
        "unittests":          unittests,
        "stop_on_first_fail": False,
        "block_network":      True,
    }

    try:
        response = requests.post(EXECEVAL_URL, json=payload, timeout=TIMEOUT)
        results  = response.json()
    except requests.Timeout:
        return 0, len(test_cases), {"reason": "EXECEVAL_TIMEOUT"}
    except Exception as e:
        return 0, len(test_cases), {"reason": f"EXECEVAL_ERROR: {str(e)}"}

    if isinstance(results, dict) and "data" in results:
        results = results["data"]

    if not isinstance(results, list):
        return 0, len(test_cases), {"reason": f"UNEXPECTED_RESPONSE: {str(results)[:200]}"}

    passed = 0
    first_failure = None
    for i, r in enumerate(results):
        outcome = r.get("exec_outcome", "UNKNOWN")
        if outcome == "PASSED":
            passed += 1
        elif first_failure is None:
            first_failure = {
                "test":     i + 1,
                "reason":   outcome,
                "input":    r.get("input", "")[:200],
                "expected": str(r.get("output", ""))[:200],
                "result":   str(r.get("result", ""))[:200],
            }

    return passed, len(results), first_failure


candidate_results = []
failed_candidates = []
by_bug = defaultdict(list)

for i, record in enumerate(records):
    task_id      = record.get("task_id", f"candidate_{i}")
    sample_id    = record.get("sample_id", record.get("apr_id", ""))
    apr_id       = record.get("apr_id", "")
    src_uid      = record.get("src_uid", "")
    candidate_id = record.get("candidate_id", 0)
    lang_cluster = record.get("lang_cluster", "")
    lang         = record.get("lang", "")
    fixed_code   = record.get("fixed_source_code", "")
    bug_outcome  = record.get("bug_exec_outcome", "")

    test_cases = record.get("hidden_unit_tests", [])
    if isinstance(test_cases, str):
        try:
            test_cases = json.loads(test_cases)
        except Exception:
            test_cases = []
    if not test_cases and src_uid in unittest_db:
        test_cases = unittest_db[src_uid]

    print(
        f"[{i+1}/{len(records)}] {apr_id} cand={candidate_id} "
        f"lang={lang} orig_outcome={bug_outcome} tests={len(test_cases)}",
        end=" ... ",
    )

    if not fixed_code.strip():
        result = "EMPTY"
        passed, total_tests, failure = 0, len(test_cases), {"reason": "EMPTY_OUTPUT"}
    elif not test_cases:
        result = "NO_TESTS"
        passed, total_tests, failure = 0, 0, {"reason": "NO_TESTS_AVAILABLE"}
    else:
        passed, total_tests, failure = run_via_execeval(fixed_code, lang, test_cases)
        result = "PASS" if passed == total_tests and total_tests > 0 else "FAIL"

    print(f"{result} ({passed}/{total_tests})")

    candidate_row = {
        "task_id":          task_id,
        "sample_id":        sample_id,
        "apr_id":           apr_id,
        "candidate_id":     candidate_id,
        "lang_cluster":     lang_cluster,
        "lang":             lang,
        "result":           result,
        "tests_passed":     passed,
        "tests_total":      total_tests,
        "bug_exec_outcome": bug_outcome,
        "difficulty":       record.get("difficulty", ""),
        "tags":             record.get("tags", []),
    }
    candidate_results.append(candidate_row)
    by_bug[sample_id].append(candidate_row)

    if result != "PASS" and failure:
        failed_candidates.append({
            "task_id":            task_id,
            "sample_id":          sample_id,
            "apr_id":             apr_id,
            "candidate_id":       candidate_id,
            "lang_cluster":       lang_cluster,
            "lang":               lang,
            "result":             result,
            "bug_exec_outcome":   bug_outcome,
            "failure":            failure,
            "fixed_code_preview": fixed_code[:300],
        })


per_bug = []
lang_stats = defaultdict(lambda: {"pass": 0, "total": 0})
outcome_stats = defaultdict(lambda: {"pass": 0, "total": 0})

for sample_id, candidates in sorted(by_bug.items()):
    candidates = sorted(candidates, key=lambda r: r.get("candidate_id", 0))
    first = candidates[0]
    apr_id = first["apr_id"]
    passed_candidates = [r for r in candidates if r["result"] == "PASS"]
    is_pass = bool(passed_candidates)
    best_candidate = passed_candidates[0]["candidate_id"] if passed_candidates else None

    lang_cluster = first["lang_cluster"]
    bug_outcome = first["bug_exec_outcome"]

    lang_stats[lang_cluster]["total"] += 1
    outcome_stats[bug_outcome]["total"] += 1
    if is_pass:
        lang_stats[lang_cluster]["pass"] += 1
        outcome_stats[bug_outcome]["pass"] += 1

    per_bug.append({
        "sample_id":           sample_id,
        "apr_id":              apr_id,
        "lang_cluster":        lang_cluster,
        "lang":                first["lang"],
        "bug_exec_outcome":    bug_outcome,
        "pass_at_5":           is_pass,
        "score":               1 if is_pass else 0,
        "passing_candidates":  [r["candidate_id"] for r in passed_candidates],
        "best_candidate_id":   best_candidate,
        "num_candidates":      len(candidates),
        "candidate_results":   [
            {
                "candidate_id": r["candidate_id"],
                "result":       r["result"],
                "tests_passed": r["tests_passed"],
                "tests_total":  r["tests_total"],
            }
            for r in candidates
        ],
    })


total_bugs = len(per_bug)
passed_bugs = sum(r["score"] for r in per_bug)
pass_at_5 = round(passed_bugs / total_bugs, 4) if total_bugs else 0.0

print(f"\n{'='*60}")
print(f"Prompt variant         : {variant}")
print(f"Total bugs             : {total_bugs}")
print(f"Candidate rows         : {len(candidate_results)}")
print(f"Bugs passed @5         : {passed_bugs}")
print(f"Pass@5                 : {pass_at_5:.4f} ({pass_at_5*100:.2f}%)")

print(f"\nPer-language breakdown:")
print(f"  {'Language':<15} {'Pass':>5} {'Total':>6} {'Pass@5':>8}")
print(f"  {'-'*40}")
for lang, stats in sorted(lang_stats.items()):
    p5 = stats["pass"] / stats["total"] if stats["total"] > 0 else 0.0
    print(f"  {lang:<15} {stats['pass']:>5} {stats['total']:>6} {p5*100:>7.2f}%")
print(f"{'='*60}")


aggregate = {
    "aggregate": {
        "prompt_variant":       variant,
        "metric":               f"Pass@{PASS_K}",
        "pass_at_5":            pass_at_5,
        "total_passed":         passed_bugs,
        "total_bugs":           total_bugs,
        "candidate_rows":       len(candidate_results),
        "candidates_per_bug":   PASS_K,
        "per_language": {
            lang: {
                "pass":      s["pass"],
                "total":     s["total"],
                "pass_at_5": round(s["pass"] / s["total"], 4) if s["total"] > 0 else 0.0,
            }
            for lang, s in sorted(lang_stats.items())
        },
        "per_bug_outcome": {
            outcome: {
                "pass":      s["pass"],
                "total":     s["total"],
                "pass_at_5": round(s["pass"] / s["total"], 4) if s["total"] > 0 else 0.0,
            }
            for outcome, s in sorted(outcome_stats.items())
        },
    }
}

with open(output_path, "w") as f:
    f.write(json.dumps(aggregate) + "\n")
    for r in per_bug:
        f.write(json.dumps(r) + "\n")

with open(failed_path, "w") as f:
    json.dump(failed_candidates, f, indent=2)

print(f"\nResults saved to  : {output_path}")
print(f"Failed candidates : {failed_path}")
