import os
import sys
import json
import re
import typing
from datasets import load_dataset

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_CONFIGS = {
    "humaneval": {
        "dataset_name": "openai_humaneval",
        "split": "test",
        "task_id_field": "task_id",
        "test_field": "test",
        "entry_point_field": "entry_point",
    },
    "mbpp": {
        "dataset_name": "mbpp",
        "split": "test",
        "task_id_field": "task_id",
        "test_field": "test_list",
        "entry_point_field": None,
    },
}

if len(sys.argv) != 3 or sys.argv[1].upper() not in ("A", "B") or sys.argv[2].lower() not in DATASET_CONFIGS:
    print("Usage: python evaluator.py <A|B> <dataset>")
    print(f"Available datasets: {', '.join(DATASET_CONFIGS.keys())}")
    sys.exit(1)

variant     = sys.argv[1].upper()
dataset_key = sys.argv[2].lower()
config      = DATASET_CONFIGS[dataset_key]

inputs_path = os.path.join(BASE_DIR, "outputs", f"outputs_{variant}_{dataset_key}.jsonl")
output_path = os.path.join(BASE_DIR, "results", f"results_{variant}_{dataset_key}.jsonl")

config_name = config.get("config_name")
if config_name:
    dataset = load_dataset(config["dataset_name"], config_name, split=config["split"])
else:
    dataset = load_dataset(config["dataset_name"], split=config["split"])

task_lookup = {str(row[config["task_id_field"]]): row for row in dataset}


def extract_completion(raw: str) -> str:
    raw = raw.strip()

    # 1. ```json block containing {"completion": "..."}
    match = re.search(r"```json\n(.*?)```", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            completion = parsed.get("completion", "")
            if isinstance(completion, str) and completion.strip().startswith("{"):
                try:
                    inner = json.loads(completion)
                    completion = inner.get("completion", completion)
                except json.JSONDecodeError:
                    pass
            return completion.strip()
        except json.JSONDecodeError:
            pass

    # 2. ```python block
    match = re.search(r"```python\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. generic ``` block
    match = re.search(r"```\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 4. whole raw is JSON (possibly fenced)
    stripped = re.sub(r"^```[a-z]*\n?", "", raw)
    stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
        completion = parsed.get("completion", "")
        if isinstance(completion, str) and completion.strip().startswith("{"):
            try:
                inner = json.loads(completion)
                completion = inner.get("completion", completion)
            except json.JSONDecodeError:
                pass
        return completion.strip()
    except json.JSONDecodeError:
        pass

    return stripped


results = []
with open(inputs_path, "r") as f:
    for line in f:
        line = line.strip()
        if line:
            results.append(json.loads(line))

print(f"Loaded {len(results)} instances from {inputs_path}.")

per_instance = []

for result in results:
    task_id     = str(result["task_id"])
    completion  = extract_completion(result.get("raw_output", result.get("completion", "")))
    row         = task_lookup.get(task_id)

    if row is None:
        print(f"  WARNING: task_id {task_id} not found in dataset, skipping.")
        continue

    test_field       = config["test_field"]
    entry_point_field = config["entry_point_field"]
    test_code        = row[test_field]
    entry_point      = row[entry_point_field] if entry_point_field else None

    if isinstance(test_code, list):
        test_code = "\n".join(test_code)

    if entry_point:
        full_code = completion + "\n\n" + test_code + f"\n\ncheck({entry_point})"
    else:
        full_code = completion + "\n\n" + test_code

    base_namespace = {k: v for k, v in vars(typing).items()}
    try:
        exec(full_code, base_namespace)
        passed = True
        print(f"[PASS] {task_id}")
    except Exception as e:
        passed = False
        print(f"[FAIL] {task_id} — {type(e).__name__}: {e}")

    per_instance.append({
        "task_id":    task_id,
        "passed":     passed,
        "score":      1 if passed else 0,
        "completion": completion,
        "raw_output": result.get("raw_output", "")
    })

total    = len(per_instance)
n_pass   = sum(r["score"] for r in per_instance)
n_fail   = total - n_pass
accuracy = round(n_pass / total, 4) if total > 0 else 0.0

print(f"\n{'='*40}")
print(f"Total : {total}")
print(f"Passed: {n_pass} ({100 * accuracy:.1f}%)")
print(f"Failed: {n_fail} ({100 * (1 - accuracy):.1f}%)")

os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)
with open(output_path, "w") as f:
    aggregate = {
        "aggregate": {
            "accuracy": accuracy,
            "passed":   n_pass,
            "failed":   n_fail,
            "total":    total
        }
    }
    f.write(json.dumps(aggregate) + "\n")
    for r in per_instance:
        f.write(json.dumps(r) + "\n")

print(f"\nResults saved to {output_path}")
