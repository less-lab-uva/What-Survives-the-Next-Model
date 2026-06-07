"""
GuideSyn — evaluator: check synthesized functions against Trio correctness checker.
Usage: python evaluator.py [--variant {A,B,both}]
Input:  outputs/outputs_{A|B}.jsonl
Output: results/results_{A|B}.jsonl
"""

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

HERE    = Path(__file__).parent
BENCH   = HERE / "data"
TRIO    = HERE / "trio"
TIMEOUT = 30


def check_with_trio(function_str, mls_path):
    if not function_str:
        return False, "no function"
    mls_content = Path(mls_path).read_text()
    synth_match = re.search(r"(synth\s+.+?satisfying)", mls_content, re.DOTALL)
    synth_header = synth_match.group(1).strip() if synth_match else ""
    sol_content = f"{synth_header}\n{function_str.strip()}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sol", delete=False) as f:
        f.write(sol_content)
        sol_path = f.name
    try:
        result = subprocess.run(
            [str(TRIO), "-convert", "-ai_guide", sol_path, str(mls_path)],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        output = result.stdout + result.stderr
        solved = "AI solution is correct" in output
        return solved, output[:200].strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)
    finally:
        Path(sol_path).unlink(missing_ok=True)


def run_variant(variant):
    in_path  = HERE / "outputs" / f"outputs_{variant}.jsonl"
    out_path = HERE / "results" / f"results_{variant}.jsonl"
    out_path.parent.mkdir(exist_ok=True)

    records = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    mls_map = {b.stem: b for b in BENCH.glob("*.mls")}
    times = [r["response_time"] for r in records if "response_time" in r]
    avg_rt = round(sum(times) / len(times), 3) if times else None
    print(f"\n--- Variant {variant} ---")
    print(f"Loaded {len(records)} outputs  |  {len(mls_map)} .mls benchmarks available  |  avg_response_time={avg_rt}s")

    per_instance = []
    for r in records:
        prob = r["prob"]
        func = r.get("synthesized_function") or ""
        mls_path = mls_map.get(prob)
        if mls_path:
            solved, detail = check_with_trio(func, mls_path)
        else:
            solved, detail = False, "mls file not found"
        row = {"prob": prob, "solved": solved, "detail": detail[:120], "score": 1 if solved else 0}
        per_instance.append(row)
        print(f"  [{prob}] {'SOLVED' if solved else f'FAIL — {detail[:60]}'}")

    total    = len(per_instance)
    n_solved = sum(r["score"] for r in per_instance)
    pct      = round(100 * n_solved / total, 2) if total else 0.0

    print(f"\n{'='*40}")
    print(f"Solved: {n_solved}/{total} ({pct}%)")

    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": {
            "solved_pct": pct, "solved": n_solved,
            "failed": total - n_solved, "total": total,
            "avg_response_time": avg_rt,
        }}) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"Results saved to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to evaluate (default: both)")
    args = parser.parse_args()

    variants = ["A", "B"] if args.variant == "both" else [args.variant]
    for v in variants:
        run_variant(v)


if __name__ == "__main__":
    main()
