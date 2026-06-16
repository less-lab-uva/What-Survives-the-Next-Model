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
SWEBENCH_DATASET = "princeton-nlp/SWE-bench_Verified"
LOCAL_SWEBENCH_DATASET = BASE_DIR / "PatchDiff" / "data" / "dataset" / "swebench_verified"

TOOL_NAMES = ["openhands", "codestory", "learnbyinteract"]

# SWE-bench harness runs tests inside Docker
# Make sure swebench is installed: pip install swebench
if importlib.util.find_spec("swebench.harness.run_evaluation") is None:
    print("ERROR: swebench not installed. Run: pip install swebench")
    sys.exit(1)

from swebench.harness.utils import load_swebench_dataset
from datasets import load_from_disk


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


def extract_test_paths_from_patch(test_patch: str) -> list:
    paths = re.findall(r"^diff --git a/(?:.*?) b/(.*?)$", test_patch or "", flags=re.MULTILINE)
    return [
        path
        for path in paths
        if path.endswith(".py") and ("test" in path.lower() or "tests/" in path.lower())
    ]


def choose_generated_test_path(original_test_patch: str, repo: str) -> str:
    test_paths = extract_test_paths_from_patch(original_test_patch)
    if test_paths:
        parent = str(Path(test_paths[0]).parent)
        return str(Path(parent) / "test_patchdiff_generated.py")

    repo_short = repo.split("/")[-1]
    return str(Path(repo_short) / "tests" / "test_patchdiff_generated.py")


def generated_test_directives(test_file_path: str, generated_test: str, repo: str) -> list:
    function_names = re.findall(r"^def\s+(test_[A-Za-z0-9_]+)\s*\(", generated_test or "", flags=re.MULTILINE)

    if repo == "sympy/sympy" and function_names:
        return function_names

    if repo == "django/django":
        module = test_file_path
        if module.endswith(".py"):
            module = module[:-3]
        if module.startswith("tests/"):
            module = module[len("tests/"):]
        module = module.replace("/", ".")
        if function_names:
            return [f"{name} ({module}.PatchDiffGeneratedTest)" for name in function_names]
        return [module]

    if function_names:
        return [f"{test_file_path}::{name}" for name in function_names]
    return [test_file_path]


def extract_test_function(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            value = parsed.get("differentiating_test")
            if isinstance(value, str):
                extracted = extract_test_function(value)
                if extracted:
                    return extracted
    except json.JSONDecodeError:
        pass

    for json_string_match in re.finditer(
        r'"differentiating_test"\s*:\s*"((?:\\.|[^"\\])*)',
        text,
        flags=re.DOTALL,
    ):
        encoded = json_string_match.group(1)
        while encoded.endswith("\\"):
            encoded = encoded[:-1]
        try:
            decoded = json.loads('"' + encoded + '"')
        except json.JSONDecodeError:
            decoded = bytes(encoded, "utf-8").decode("unicode_escape", errors="ignore")
        extracted = extract_test_function(decoded)
        if extracted:
            return extracted

    for fence_match in re.finditer(r"```(?:json|python)?\s*(.*?)\s*```", text, flags=re.DOTALL):
        fenced = fence_match.group(1).strip()
        extracted = extract_test_function(fenced)
        if extracted:
            return extracted

    if text.startswith("def test_"):
        return text if is_syntax_valid(text) else ""

    def_match = re.search(r"(^def\s+test_[A-Za-z0-9_]+\s*\(.*)", text, flags=re.DOTALL | re.MULTILINE)
    if def_match:
        extracted = def_match.group(1).strip()
        return extracted if is_syntax_valid(extracted) else ""

    return ""


def is_syntax_valid(test_code: str) -> bool:
    try:
        compile(test_code, "<generated_test>", "exec")
        return True
    except SyntaxError:
        return False


def get_generated_test(pred: dict) -> str:
    candidates = [
        pred.get("prediction", {}).get("differentiating_test", ""),
        pred.get("raw_output", ""),
    ]

    for candidate in candidates:
        extracted = extract_test_function(candidate)
        if extracted:
            return extracted

    return ""


def prepare_generated_test_for_repo(generated_test: str, repo: str) -> str:
    generated_test = generated_test.strip()
    if not generated_test:
        generated_test = "def test_patchdiff_no_valid_generated_test():\n    pass\n"

    if repo != "django/django":
        return generated_test

    if re.search(r"^\s*class\s+\w+.*Test", generated_test, flags=re.MULTILINE):
        return generated_test

    lines = generated_test.splitlines()
    converted = []
    for line in lines:
        match = re.match(r"^def\s+(test_[A-Za-z0-9_]+)\s*\(\s*\)\s*:", line)
        if match:
            converted.append(f"    def {match.group(1)}(self):")
        else:
            converted.append("    " + line if line.strip() else line)

    return (
        "from django.test import SimpleTestCase\n\n\n"
        "class PatchDiffGeneratedTest(SimpleTestCase):\n"
        + "\n".join(converted)
        + "\n"
    )


def convert_test_to_patch(
    instance_id: str,
    generated_test: str,
    repo: str,
    original_test_patch: str,
) -> tuple:
    test_file_path = choose_generated_test_path(original_test_patch, repo)
    if not generated_test.strip():
        generated_test = "def test_patchdiff_no_valid_generated_test():\n    pass\n"
    directives = generated_test_directives(test_file_path, generated_test, repo)
    generated_test = prepare_generated_test_for_repo(generated_test, repo)

    # Full test file content
    test_file_content = (
        "# Auto-generated differentiating test\n"
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

    return "".join(diff_lines), test_file_path, directives


def build_generated_test_dataset(predictions: list, tmp_dir: Path) -> Path:
    instance_ids = [pred["instance_id"] for pred in predictions]
    if LOCAL_SWEBENCH_DATASET.exists():
        original_dataset = load_from_disk(str(LOCAL_SWEBENCH_DATASET))
        wanted = set(instance_ids)
        original_by_id = {
            row["instance_id"]: dict(row)
            for row in original_dataset
            if row["instance_id"] in wanted
        }
    else:
        original_dataset = load_swebench_dataset(SWEBENCH_DATASET, "test", instance_ids)
        original_by_id = {row["instance_id"]: dict(row) for row in original_dataset}

    dataset_path = tmp_dir / "generated_test_dataset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as f:
        for pred in predictions:
            instance_id = pred["instance_id"]
            if instance_id not in original_by_id:
                raise KeyError(f"Instance not found in SWE-bench dataset: {instance_id}")

            row = dict(original_by_id[instance_id])
            generated = get_generated_test(pred)
            test_patch, test_file_path, directives = convert_test_to_patch(
                instance_id=instance_id,
                generated_test=generated,
                repo=pred["repo"],
                original_test_patch=row.get("test_patch", ""),
            )

            row["test_patch"] = test_patch
            row["FAIL_TO_PASS"] = directives
            row["PASS_TO_PASS"] = []
            row["generated_test_file"] = test_file_path
            f.write(json.dumps(row) + "\n")

    return dataset_path


def run_swebench_evaluation(
    predictions_path: Path,
    dataset_path: Path,
    run_id: str,
    max_workers: int = 4,
) -> dict:

    results_dir = RESULTS_DIR / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", str(dataset_path),
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
    patch_key: str,  # "plausible_patch" or "oracle_patch"
    tmp_dir: Path,
    run_label: str,
) -> Path:

    output_file = tmp_dir / f"preds_{run_label}.jsonl"

    with output_file.open("w", encoding="utf-8") as f:
        for pred in predictions:
            instance_id = pred["instance_id"]
            base_patch = pred["input"][patch_key]

            line = {
                "instance_id": instance_id,
                "model_patch": base_patch,
                "model_name_or_path": run_label,
            }
            f.write(json.dumps(line) + "\n")

    return output_file


def compute_differentiating_rate(
    results_plausible: dict,
    results_oracle: dict,
    predictions: list,
) -> list:

    per_instance = []

    for pred in predictions:
        instance_id = pred["instance_id"]
        generated = get_generated_test(pred)

        resolved_plausible = is_resolved(results_plausible, instance_id)
        resolved_oracle = is_resolved(results_oracle, instance_id)

        # Differentiating = test FAILS on plausible patch, PASSES on oracle
        # In SWE-bench terms: not resolved on plausible, resolved on oracle
        is_differentiating = (not resolved_plausible) and resolved_oracle

        per_instance.append({
            "instance_id": instance_id,
            "tool": pred["tool"],
            "prompt_type": pred["prompt_type"],
            "has_generated_test": bool(generated and generated.strip()),
            "resolved_plausible": resolved_plausible,
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
        generated_test_dataset = build_generated_test_dataset(predictions, tmp_path)
        print(f"Generated-test SWE-bench dataset saved to temporary file: {generated_test_dataset}")

        # ── Run 1: plausible patch + generated test ──────────────────────
        print("\n" + "="*60)
        print("RUN 1: Applying PLAUSIBLE patch, running generated test")
        print("="*60)
        run_id_plausible = f"plausible_generated_{variant}_{tool_name}"
        preds_plausible = build_predictions_file(
            predictions=predictions,
            patch_key="plausible_patch",
            tmp_dir=tmp_path,
            run_label=run_id_plausible,
        )
        results_plausible, time_plausible = run_swebench_evaluation(
            predictions_path=preds_plausible,
            dataset_path=generated_test_dataset,
            run_id=run_id_plausible,
        )

        # ── Run 2: oracle patch + generated test ──────────────────────────
        print("\n" + "="*60)
        print("RUN 2: Applying ORACLE patch, running generated test")
        print("="*60)
        run_id_oracle = f"oracle_generated_{variant}_{tool_name}"
        preds_oracle = build_predictions_file(
            predictions=predictions,
            patch_key="oracle_patch",
            tmp_dir=tmp_path,
            run_label=run_id_oracle,
        )
        results_oracle, time_oracle = run_swebench_evaluation(
            predictions_path=preds_oracle,
            dataset_path=generated_test_dataset,
            run_id=run_id_oracle,
        )

    # ── Compute differentiating rate ──────────────────────────────────────
    per_instance = compute_differentiating_rate(
        results_plausible=results_plausible,
        results_oracle=results_oracle,
        predictions=predictions,
    )

    total = len(per_instance)
    n_differentiating = sum(r["score"] for r in per_instance)
    n_not = total - n_differentiating
    diff_rate = round(n_differentiating / total, 4) if total > 0 else 0.0
    total_time = round(time_plausible + time_oracle, 2)

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
                "eval_time_plausible_s": round(time_plausible, 2),
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
