import os
import sys
import json
import importlib.util
import re
import subprocess
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
RESULTS_DIR = BASE_DIR / "results"

TOOL_NAMES = ["openhands", "codestory", "learnbyinteract"]

# SWE-bench harness runs tests inside Docker
# Make sure swebench is installed: pip install swebench
if importlib.util.find_spec("swebench.harness.run_evaluation") is None:
    print("ERROR: swebench not installed. Run: pip install swebench")
    sys.exit(1)


def parse_args():
    if len(sys.argv) != 3:
        print("Usage: python evaluator.py <A|B> <tool>")
        print(f"Tools: {', '.join(TOOL_NAMES)}")
        sys.exit(1)

    variant = sys.argv[1].upper()
    tool_name = sys.argv[2].lower()

    if variant not in ("A", "B"):
        print("ERROR: first argument must be A or B")
        sys.exit(1)

    if tool_name not in TOOL_NAMES:
        print(f"ERROR: tool must be one of: {', '.join(TOOL_NAMES)}")
        sys.exit(1)

    return variant, tool_name


def load_predictions(variant: str, tool_name: str) -> list:
    inputs_path = OUTPUTS_DIR / f"outputs_{variant}_{tool_name}.jsonl"

    if not inputs_path.exists():
        print(f"ERROR: predictions file not found: {inputs_path}")
        print("Run main.py first to generate predictions.")
        sys.exit(1)

    results = []
    with inputs_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    print(f"Loaded {len(results)} predictions from {inputs_path}")
    return results


def convert_test_to_patch(instance_id: str, generated_test: str, repo: str) -> str:

    # Derive a test file path from the repo name
    # e.g. astropy/astropy -> astropy/tests/test_patchdiff.py
    repo_short = repo.split("/")[-1]  # e.g. astropy
    test_file_path = f"{repo_short}/tests/test_patchdiff_generated.py"

    # Full test file content
    test_file_content = (
        "# Auto-generated differentiating test\n"
        "import pytest\n\n"
        + generated_test
        + "\n"
    )

    # Build a unified diff that creates this new file
    lines = test_file_content.splitlines(keepends=True)
    diff_lines = [
        f"diff --git a/{test_file_path} b/{test_file_path}\n",
        "new file mode 100644\n",
        "--- /dev/null\n",
        f"+++ b/{test_file_path}\n",
        f"@@ -0,0 +1,{len(lines)} @@\n",
    ]
    for line in lines:
        diff_lines.append(f"+{line}")

    return "".join(diff_lines)


def run_swebench_evaluation(
    predictions_path: Path,
    run_id: str,
    max_workers: int = 4,
) -> dict:

    results_dir = RESULTS_DIR / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", "princeton-nlp/SWE-bench_Verified",
        "--split", "test",
        "--predictions_path", str(predictions_path),
        "--max_workers", str(max_workers),
        "--run_id", run_id,
        "--report_dir", str(results_dir),
    ]

    print(f"\nRunning SWE-bench harness: {' '.join(cmd)}\n")
    t_start = time.time()

    proc = subprocess.run(cmd, cwd=results_dir, capture_output=False, text=True)

    t_end = time.time()
    elapsed = round(t_end - t_start, 2)
    print(f"\nHarness finished in {elapsed}s (exit code: {proc.returncode})")

    if proc.returncode != 0:
        raise RuntimeError(
            f"SWE-bench harness failed for run_id={run_id} "
            f"with exit code {proc.returncode}."
        )

    # Parse results from output directory
    for f in results_dir.glob("*.json"):
        with f.open() as fp:
            return json.load(fp), elapsed

    raise FileNotFoundError(
        f"SWE-bench harness finished but no JSON result file was found under {results_dir}."
    )


def build_predictions_file(
    predictions: list,
    patch_key: str,  # "suspicious_patch" or "oracle_patch"
    generated_test: bool,
    tmp_dir: Path,
    run_label: str,
) -> Path:

    output_file = tmp_dir / f"preds_{run_label}.jsonl"

    with output_file.open("w", encoding="utf-8") as f:
        for pred in predictions:
            instance_id = pred["instance_id"]
            base_patch = pred["input"][patch_key]
            generated = pred["prediction"]["differentiating_test"]
            repo = pred["repo"]

            if generated_test and generated and generated.strip():
                # Convert generated test to a patch and combine with the code patch
                test_patch = convert_test_to_patch(instance_id, generated, repo)
                combined_patch = base_patch + "\n" + test_patch
            else:
                combined_patch = base_patch

            line = {
                "instance_id": instance_id,
                "model_patch": combined_patch,
                "model_name_or_path": run_label,
            }
            f.write(json.dumps(line) + "\n")

    return output_file


def compute_differentiating_rate(
    results_suspicious: dict,
    results_oracle: dict,
    predictions: list,
) -> list:

    per_instance = []

    for pred in predictions:
        instance_id = pred["instance_id"]
        generated = pred["prediction"]["differentiating_test"]

        resolved_suspicious = is_resolved(results_suspicious, instance_id)
        resolved_oracle = is_resolved(results_oracle, instance_id)

        # Differentiating = test FAILS on suspicious, PASSES on oracle
        # In SWE-bench terms: not resolved on suspicious, resolved on oracle
        is_differentiating = (not resolved_suspicious) and resolved_oracle

        per_instance.append({
            "instance_id": instance_id,
            "tool": pred["tool"],
            "prompt_type": pred["prompt_type"],
            "has_generated_test": bool(generated and generated.strip()),
            "resolved_suspicious": resolved_suspicious,
            "resolved_oracle": resolved_oracle,
            "differentiating": is_differentiating,
            "score": 1 if is_differentiating else 0,
        })

    return per_instance


def is_resolved(results: dict, instance_id: str) -> bool:
    # Newer SWE-bench reports use aggregate lists.
    if "resolved_ids" in results:
        return instance_id in set(results.get("resolved_ids", []))

    # Older or per-instance reports may be keyed by instance_id.
    instance_result = results.get(instance_id, {})
    if isinstance(instance_result, dict):
        return bool(instance_result.get("resolved", False))

    return False


def main():
    variant, tool_name = parse_args()

    # Load LLM predictions
    predictions = load_predictions(variant, tool_name)
    print(f"Evaluating {len(predictions)} instances "
          f"(prompt={variant}, tool={tool_name})")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # ── Run 1: suspicious patch + generated test ──────────────────────
        print("\n" + "="*60)
        print("RUN 1: Applying SUSPICIOUS patch + generated test")
        print("="*60)
        run_id_suspicious = f"suspicious_{variant}_{tool_name}"
        preds_suspicious = build_predictions_file(
            predictions=predictions,
            patch_key="suspicious_patch",
            generated_test=True,
            tmp_dir=tmp_path,
            run_label=run_id_suspicious,
        )
        results_suspicious, time_suspicious = run_swebench_evaluation(
            predictions_path=preds_suspicious,
            run_id=run_id_suspicious,
        )

        # ── Run 2: oracle patch + generated test ──────────────────────────
        print("\n" + "="*60)
        print("RUN 2: Applying ORACLE patch + generated test")
        print("="*60)
        run_id_oracle = f"oracle_{variant}_{tool_name}"
        preds_oracle = build_predictions_file(
            predictions=predictions,
            patch_key="oracle_patch",
            generated_test=True,
            tmp_dir=tmp_path,
            run_label=run_id_oracle,
        )
        results_oracle, time_oracle = run_swebench_evaluation(
            predictions_path=preds_oracle,
            run_id=run_id_oracle,
        )

    # ── Compute differentiating rate ──────────────────────────────────────
    per_instance = compute_differentiating_rate(
        results_suspicious=results_suspicious,
        results_oracle=results_oracle,
        predictions=predictions,
    )

    total = len(per_instance)
    n_differentiating = sum(r["score"] for r in per_instance)
    n_not = total - n_differentiating
    diff_rate = round(n_differentiating / total, 4) if total > 0 else 0.0
    total_time = round(time_suspicious + time_oracle, 2)

    print(f"\n{'='*60}")
    print(f"RESULTS (Prompt={variant}, Tool={tool_name})")
    print(f"{'='*60}")
    print(f"Total instances      : {total}")
    print(f"Differentiating      : {n_differentiating} ({100 * diff_rate:.1f}%)")
    print(f"Not differentiating  : {n_not} ({100 * (1 - diff_rate):.1f}%)")
    print(f"Total eval time (s)  : {total_time}")
    print(f"Paper baseline       : 29.6%")
    print(f"{'='*60}")

    # ── Save results ──────────────────────────────────────────────────────
    output_path = RESULTS_DIR / f"results_{variant}_{tool_name}.jsonl"
    with output_path.open("w", encoding="utf-8") as f:
        aggregate = {
            "aggregate": {
                "prompt_type": variant,
                "tool": tool_name,
                "differentiating_rate": diff_rate,
                "differentiating": n_differentiating,
                "not_differentiating": n_not,
                "total": total,
                "eval_time_suspicious_s": round(time_suspicious, 2),
                "eval_time_oracle_s": round(time_oracle, 2),
                "total_eval_time_s": total_time,
                "paper_baseline": 0.296,
            }
        }
        f.write(json.dumps(aggregate) + "\n")
        for r in per_instance:
            f.write(json.dumps(r) + "\n")

    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
