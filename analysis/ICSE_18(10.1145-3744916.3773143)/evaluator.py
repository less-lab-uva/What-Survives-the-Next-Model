"""
EnsLLM — evaluator: score code outputs by execution on HumanEval + LiveCodeBench.
Usage: python evaluator.py [--variant {A,B,both}]
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl
Conda:  ensllm_env
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

TIMEOUT = 10
HERE         = Path(__file__).parent
HF_CACHE_DIR = str(HERE / "data" / "hf_cache")
LCB_DIR      = str(HERE / "data" / "lcb")


def _run(code, stdin=""):
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            input=stdin, capture_output=True, text=True, timeout=TIMEOUT,
        )
        return r.returncode == 0, (r.stderr or r.stdout).strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:100]


def load_he_tests():
    from datasets import load_dataset
    ds = load_dataset("openai/openai_humaneval", split="test", cache_dir=HF_CACHE_DIR)
    return {row["task_id"]: {"entry_point": row["entry_point"], "test": row["test"]} for row in ds}


def load_lcb_tests():
    import base64, pickle, zlib
    rows = []
    for fname in ["test.jsonl", "test2.jsonl"]:
        rows += [json.loads(l) for l in open(f"{LCB_DIR}/{fname}")]
    tests = {}
    for r in rows:
        pub = json.loads(r["public_test_cases"]) if isinstance(r["public_test_cases"], str) else r["public_test_cases"]
        try:
            priv = json.loads(pickle.loads(zlib.decompress(base64.b64decode(r.get("private_test_cases", "")))))
        except Exception:
            priv = []
        tests[r["question_id"]] = pub + priv
    return tests


def eval_humaneval(code, task_info):
    if not code:
        return False, "no code"
    full = f"{code}\n\n{task_info['test']}\n\ncheck({task_info['entry_point']})\n"
    return _run(full)


def eval_lcb(code, tests):
    if not code:
        return False, "no code"
    if not tests:
        return False, "no tests"
    passed = 0
    for t in tests:
        try:
            r = subprocess.run(
                [sys.executable, "-c", code],
                input=t.get("input", ""),
                capture_output=True, text=True, timeout=TIMEOUT,
            )
            if r.stdout.rstrip() == t.get("output", "").rstrip():
                passed += 1
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)[:100]
    return passed == len(tests), f"{passed}/{len(tests)}"


def run_variant(variant, he_tests, lcb_tests):
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = HERE / "results" / f"results_{variant}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    print(f"\n--- Prompt {variant}: {len(records)} outputs ---")

    def evaluate(r):
        code  = r.get("code") or ""
        bench = r["bench"]
        if bench == "HumanEval":
            info = he_tests.get(r["id"])
            if info:
                ok, detail = eval_humaneval(code, info)
            else:
                ok, detail = False, "task not found"
        else:
            tests = lcb_tests.get(r["id"], [])
            ok, detail = eval_lcb(code, tests)
        return {"id": r["id"], "bench": bench, "pass": ok, "detail": detail, "score": 1 if ok else 0}

    per_instance = []
    live = defaultdict(lambda: [0, 0])
    for i, r in enumerate(records):
        row = evaluate(r)
        per_instance.append(row)
        live[row["bench"]][0] += row["score"]
        live[row["bench"]][1] += 1
        total_p = sum(v[0] for v in live.values())
        total_n = sum(v[1] for v in live.values())
        parts = "  |  ".join(f"{b}: {p}/{n} ({100*p/n:.1f}%)" for b, (p, n) in sorted(live.items()))
        print(f"  [{i+1}/{len(records)}] {row['id']} ({row['bench']}) -> {'PASS' if row['pass'] else 'FAIL'}"
              f"  |  {parts}  |  Total: {total_p}/{total_n} ({100*total_p/total_n:.1f}%)", flush=True)

    by_bench = defaultdict(list)
    for r in per_instance:
        by_bench[r["bench"]].append(r)

    print(f"\n{'='*50}\nSUMMARY — Prompt {variant}\n{'='*50}")
    agg_by_bench = {}
    for bench, rows in by_bench.items():
        n = len(rows); p = sum(r["score"] for r in rows)
        rate = round(p/n, 4)
        agg_by_bench[bench] = {"pass_rate": rate, "passed": p, "total": n}
        print(f"  {bench}: {p}/{n} ({100*rate:.1f}%)")

    total  = len(per_instance)
    passed = sum(r["score"] for r in per_instance)

    times = [json.loads(l)["response_time"] for l in in_path.read_text().splitlines()
             if l.strip() and "response_time" in json.loads(l)]
    avg_response_time = round(sum(times) / len(times), 3) if times else None

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {"total": total, "passed": passed,
                                          "by_bench": agg_by_bench,
                                          "avg_response_time": avg_response_time}}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"Results saved to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to evaluate (default: both)")
    args = parser.parse_args()
    variants = ["A", "B"] if args.variant == "both" else [args.variant]

    print("Loading test suites...")
    he_tests  = load_he_tests()
    lcb_tests = load_lcb_tests()

    for v in variants:
        run_variant(v, he_tests, lcb_tests)


if __name__ == "__main__":
    main()
