import os
import sys
import json
import re
from typing import Optional
from datasets import load_dataset

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_CONFIGS = {
    "humanevalplus": {
        "hf_path":       "evalplus/humanevalplus",
        "split":         "test",
        "task_id":       "task_id",
        "prompt":        "prompt",
        "test":          "test",
        "entry_point":   "entry_point",
    },
    "humaneval": {
        "hf_path":       "openai/openai_humaneval",
        "split":         "test",
        "task_id":       "task_id",
        "prompt":        "prompt",
        "test":          "test",
        "entry_point":   "entry_point",
    },
    "bigcodebench": {
        "hf_path":       "bigcode/bigcodebench",
        "split":         "v0.1.2",
        "task_id":       "task_id",
        "prompt":        "instruct_prompt",
        "test":          "test",
        "entry_point":   None,
    },
    "classeval": {
        "hf_path":       "FudanSELab/ClassEval",
        "split":         "test",
        "task_id":       "task_id",
        "prompt":        "class_description",
        "test":          "test",
        "entry_point":   None,
    },
}

if len(sys.argv) != 3 or sys.argv[1].upper() not in ("A", "B") or sys.argv[2].lower() not in DATASET_CONFIGS:
    print("Usage: python evaluator.py <A|B> <dataset>")
    print(f"Available datasets: {', '.join(DATASET_CONFIGS.keys())}")
    sys.exit(1)

variant     = sys.argv[1].upper()
dataset_key = sys.argv[2].lower()
cfg         = DATASET_CONFIGS[dataset_key]

inputs_path = os.path.join(BASE_DIR, "outputs", f"outputs_{variant}_{dataset_key}.jsonl")
results_dir = os.path.join(BASE_DIR, "results")
output_path = os.path.join(results_dir, f"results_{variant}_{dataset_key}.jsonl")
os.makedirs(results_dir, exist_ok=True)

print(f"Loading dataset: {cfg['hf_path']} ...")
raw_dataset = load_dataset(cfg["hf_path"], split=cfg["split"])
dataset     = {str(row[cfg["task_id"]]): row for row in raw_dataset}


def extract_completed_function(raw: str) -> Optional[str]:
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if "completed_function" in obj:
                return obj["completed_function"]
        except json.JSONDecodeError:
            pass

    try:
        obj = json.loads(raw.strip())
        if "completed_function" in obj:
            return obj["completed_function"]
    except json.JSONDecodeError:
        pass

    py_match = re.search(r"(def\s+\w+\s*\(.*)", raw, re.DOTALL)
    if py_match:
        return py_match.group(1)

    return None


def run_test(prompt: str, completed_function: str, test_code: str, entry_point: str) -> bool:
    import_lines = []
    for line in prompt.split("\n"):
        if line.startswith("def "):
            break
        import_lines.append(line)
    imports   = "\n".join(import_lines)
    full_code = imports + "\n" + completed_function + "\n\n" + test_code + f"\n\ncheck({entry_point})\n"
    namespace = {}
    try:
        exec(compile(full_code, "<string>", "exec"), namespace)
        return True
    except Exception:
        return False


def wrap_classeval(completion: str, skeleton: str) -> str:
    # If completion is already a full class/module, use as-is
    stripped = completion.lstrip()
    if stripped.startswith("class ") or stripped.startswith("import ") or stripped.startswith("from "):
        return completion
    # Completion is method bodies meant for inside the class.
    # Fix any `def` lines sitting at column 0 — they need 4-space indentation.
    fixed_lines = []
    for line in completion.split("\n"):
        if re.match(r"^def ", line):
            fixed_lines.append("    " + line)
        else:
            fixed_lines.append(line)
    completion = "\n".join(fixed_lines)
    # Extract class header from skeleton (everything before the first stub method)
    match = re.search(r"\n    def ", skeleton)
    class_header = skeleton[:match.start()] if match else skeleton
    return class_header + "\n" + completion


def run_unittest_test(completed_function: str, test_code: str) -> bool:
    import unittest, io
    full_code = completed_function + "\n\n" + test_code
    namespace = {}
    try:
        exec(compile(full_code, "<string>", "exec"), namespace)
    except Exception:
        return False
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for obj in namespace.values():
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj is not unittest.TestCase:
            suite.addTests(loader.loadTestsFromTestCase(obj))
    if suite.countTestCases() == 0:
        return False
    runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
    result = runner.run(suite)
    return result.wasSuccessful()


results = []
with open(inputs_path, "r") as f:
    for line in f:
        line = line.strip()
        if line:
            results.append(json.loads(line))

print(f"Loaded {len(results)} instances from {inputs_path}.")

per_instance  = []
total         = 0
passed        = 0
skipped       = 0

for result in results:
    task_id = str(result.get("task_id", ""))
    raw     = result.get("completion", "")

    if task_id not in dataset:
        print(f"[SKIP] {task_id} not found in dataset.")
        skipped += 1
        continue

    task        = dataset[task_id]
    entry_point = cfg["entry_point"]
    test_code   = task[cfg["test"]]

    completed_fn = extract_completed_function(raw)
    if completed_fn is None:
        print(f"[SKIP] {task_id}: could not extract completed_function.")
        skipped += 1
        continue

    total += 1
    if entry_point is None:
        # classeval / bigcodebench — use unittest runner
        if dataset_key == "classeval":
            completed_fn = wrap_classeval(completed_fn, task.get("skeleton", ""))
        ok = run_unittest_test(completed_fn, test_code)
    else:
        prompt   = task[cfg["prompt"]]
        ep_value = task[entry_point]
        ok = run_test(prompt, completed_fn, test_code, ep_value)
    if ok:
        passed += 1
        print(f"[PASS] {task_id}")
    else:
        print(f"[FAIL] {task_id}")

    per_instance.append({
        "task_id":    task_id,
        "passed":     ok,
        "score":      1 if ok else 0,
        "completion": completed_fn,
        "raw_output": result.get("raw_output", ""),
    })

accuracy = round(passed / total, 4) if total > 0 else 0.0

print(f"\n{'='*50}")
print(f"Total evaluated : {total}")
print(f"Passed          : {passed} ({100 * accuracy:.1f}%)")
print(f"Failed          : {total - passed}")
print(f"Skipped         : {skipped}")
print(f"Pass@1          : {100 * accuracy:.2f}%")
print(f"{'='*50}")

with open(output_path, "w") as f:
    aggregate = {
        "aggregate": {
            "pass_at_1": accuracy,
            "passed":    passed,
            "failed":    total - passed,
            "total":     total,
            "skipped":   skipped,
        }
    }
    f.write(json.dumps(aggregate) + "\n")
    for r in per_instance:
        f.write(json.dumps(r) + "\n")

print(f"\nResults saved to {output_path}")
