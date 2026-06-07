import os
import sys
import json
import re
import random
import anthropic
from datasets import load_dataset

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dataset configurations: name, split, and field mappings
DATASET_CONFIGS = {
    "humaneval": {
        "dataset_name": "openai_humaneval",
        "split": "test",
        "prompt_field": "prompt",
        "test_field": "test",
        "entry_point_field": "entry_point",
        "task_id_field": "task_id",
    },
    "mbpp": {
        "dataset_name": "mbpp",
        "split": "test",
        "prompt_field": "text",
        "test_field": "test_list",
        "entry_point_field": None,
        "task_id_field": "task_id",
    },
}


def load_prompt_template(template_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template file not found: {template_path}")
    with open(template_path, "r") as f:
        return f.read()


def build_prompt(template, prompt, test, entry_point):
    # For MBPP, test_list is a list of strings — join them into a single string
    if isinstance(test, list):
        test = "\n".join(test)
    instance = json.dumps({"prompt": prompt, "test": test, "entry_point": entry_point}, indent=2)
    return template + f"\n\n---\n\n{instance}"


def extract_code(raw: str) -> str:
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


def main():
    if len(sys.argv) != 3 or sys.argv[1].upper() not in ("A", "B") or sys.argv[2].lower() not in DATASET_CONFIGS:
        print("Usage: python main.py <A|B> <dataset>")
        print(f"Available datasets: {', '.join(DATASET_CONFIGS.keys())}")
        sys.exit(1)

    prompt_variant = sys.argv[1].upper()
    dataset_key    = sys.argv[2].lower()
    config         = DATASET_CONFIGS[dataset_key]

    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{prompt_variant}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from {prompt_file}.")

    config_name = config.get("config_name")
    if config_name:
        dataset = load_dataset(config["dataset_name"], config_name, split=config["split"])
    else:
        dataset = load_dataset(config["dataset_name"], split=config["split"])
    total_dataset = len(dataset)
    print(f"Loaded {total_dataset} problems from {dataset_key}.")

    SEED        = 42
    sample_size = max(1, int(0.10 * total_dataset))
    random.seed(SEED)
    sampled_indices = sorted(random.sample(range(total_dataset), sample_size))
    print(f"Randomly sampled {sample_size} instances (10%, seed={SEED}): indices {sampled_indices}")

    # Load cache from previous run
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    output_path = os.path.join(outputs_dir, f"outputs_{prompt_variant}_{dataset_key}.jsonl")
    cache_lookup = {}
    if os.path.exists(output_path):
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if "task_id" in r:
                        cache_lookup[str(r["task_id"])] = r
        print(f"Loaded {len(cache_lookup)} cached results from {output_path}.")

    results          = []
    cached_count     = 0
    total_input_tok  = 0
    total_output_tok = 0

    for i, idx in enumerate(sampled_indices):
        row         = dataset[idx]
        task_id     = str(row[config["task_id_field"]])
        prompt      = row[config["prompt_field"]]
        test        = row[config["test_field"]]
        entry_point = row[config["entry_point_field"]] if config["entry_point_field"] else None

        print(f"[{i+1}/{sample_size}] Processing {task_id} ...", end=" ", flush=True)

        if task_id in cache_lookup:
            print("CACHED")
            results.append(cache_lookup[task_id])
            cached_count += 1
            continue

        filled_prompt = build_prompt(template, prompt, test, entry_point)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": filled_prompt}]
            )
            raw_output     = response.content[0].text
            corrected_code = extract_code(raw_output)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens
            print("OK")

        except Exception as e:
            print(f"ERROR: {e}")
            corrected_code = ""
            raw_output     = ""

        results.append({
            "task_id":    task_id,
            "completion": corrected_code,
            "raw_output": raw_output,
        })

    os.makedirs(outputs_dir, exist_ok=True)
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    token_path = os.path.join(outputs_dir, f"tokens_{prompt_variant}_{dataset_key}.txt")
    with open(token_path, "w") as f:
        f.write(f"Prompt          : {prompt_variant}\n")
        f.write(f"Dataset         : {dataset_key}\n")
        f.write(f"Instances run   : {sample_size}\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    print(f"\nDone. Results saved to {output_path}")
    print(f"Tokens saved to    : {token_path}")
    print(f"From cache         : {cached_count}")
    print(f"New LLM calls      : {sample_size - cached_count}")
    print(f"Total input tokens : {total_input_tok}")
    print(f"Total output tokens: {total_output_tok}")


if __name__ == "__main__":
    main()
