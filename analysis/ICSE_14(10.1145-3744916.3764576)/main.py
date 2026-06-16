import os
import sys
import json
import re
import random
import time
import anthropic
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts"
OUTPUTS_DIR = BASE_DIR / "outputs"

COMBINED_DATASET_PATH = BASE_DIR / "combined_dataset.json"

TOOL_NAMES = ["openhands", "codestory", "learnbyinteract"]

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)


def load_dataset(tool_name: str) -> List[Dict[str, Any]]:
    with COMBINED_DATASET_PATH.open("r", encoding="utf-8") as f:
        all_instances = json.load(f)

    rows = [x for x in all_instances if x["tool"] == tool_name]

    if not rows:
        raise ValueError(f"No instances found for tool: {tool_name}")

    print(f"Loaded {len(rows)} instances for tool: {tool_name}")
    return rows


def load_prompt_template(prompt_type: str) -> str:
    prompt_type = prompt_type.upper()
    prompt_path = PROMPTS_DIR / f"prompt_{prompt_type}.txt"

    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {prompt_path}. "
            "Create prompts/prompt_A.txt and prompts/prompt_B.txt first."
        )

    return prompt_path.read_text(encoding="utf-8").strip()


def build_instance(row: Dict[str, Any]) -> Dict[str, str]:
    return {
        "issue_statement": row["problem_statement"],
        "plausible_patch": row["plausible_patch"],
        "oracle_patch": row["oracle_patch"],
    }


def build_prompt(template: str, instance: Dict[str, str]) -> str:
    instance_json = json.dumps(instance, indent=2, ensure_ascii=False)

    return (
        template
        + "\n\n---\n\n"
        + instance_json
    )


def extract_text_from_response(response: Any) -> str:
    text_blocks = []
    for block in response.content:
        block_text = getattr(block, "text", None)
        if block_text is not None:
            text_blocks.append(block_text)
    return "\n".join(text_blocks).strip()


def extract_differentiating_test(raw_output: str) -> str:
    output = raw_output.strip()

    
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict) and isinstance(parsed.get("differentiating_test"), str):
            return parsed["differentiating_test"]
    except json.JSONDecodeError:
        pass

    
    fenced_json_match = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        output,
        flags=re.DOTALL,
    )
    if fenced_json_match:
        try:
            parsed = json.loads(fenced_json_match.group(1))
            if isinstance(parsed, dict) and isinstance(parsed.get("differentiating_test"), str):
                return parsed["differentiating_test"]
        except json.JSONDecodeError:
            pass

    
    fenced_code_match = re.search(
        r"```(?:python)?\s*(def test_.*?)\s*```",
        output,
        flags=re.DOTALL,
    )
    if fenced_code_match:
        return fenced_code_match.group(1).strip()

    
    return output


def main():
    if len(sys.argv) != 3:
        print("Usage: python main.py <A|B> <tool>")
        print(f"Tools: {', '.join(TOOL_NAMES)}")
        sys.exit(1)

    prompt_type = sys.argv[1].upper()
    tool_name = sys.argv[2].lower()

    if prompt_type not in ("A", "B"):
        print("ERROR: first argument must be A or B")
        sys.exit(1)

    if tool_name not in TOOL_NAMES:
        print(f"ERROR: tool must be one of: {', '.join(TOOL_NAMES)}")
        sys.exit(1)

    
    template = load_prompt_template(prompt_type)
    print(f"Loaded prompt type: {prompt_type}")

    
    SEED = 42
    
    rows = load_dataset(tool_name)
    total_dataset = len(rows)
    sample_size = max(1, round(total_dataset * 0.10))
    random.seed(SEED)
    sampled_indices = sorted(random.sample(range(total_dataset), sample_size))
    print(f"Randomly sampled {sample_size} instances (seed={SEED}): indices {sampled_indices}")

    subset = []
    for dataset_index in sampled_indices:
        row = dict(rows[dataset_index])
        row["_dataset_index"] = dataset_index
        subset.append(row)

    print(
        f"Running {len(subset)} of {len(rows)} rows "
        f"(sample_size={sample_size}, seed={SEED}).\n"
    )

    # Output paths
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUTS_DIR / f"outputs_{prompt_type}_{tool_name}.jsonl"
    token_path = OUTPUTS_DIR / f"tokens_{prompt_type}_{tool_name}.txt"

    # Load cached predictions from a previous run
    cache_lookup: Dict[str, Dict[str, Any]] = {}
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    cached_result = json.loads(line)
                except json.JSONDecodeError:
                    print(f"WARNING: skipping invalid cached JSON on line {line_number}")
                    continue
                task_id = cached_result.get("task_id")
                if task_id:
                    cache_lookup[task_id] = cached_result

        print(f"Loaded {len(cache_lookup)} cached results from {output_path}.\n")

    results: List[Dict[str, Any]] = []
    cached_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_llm_time_seconds = 0.0

    for index, row in enumerate(subset):
        dataset_index = row.get("_dataset_index", index)
        task_id = f"{tool_name}_{row['instance_id']}"
        print(f"[{index + 1}/{len(subset)}] Processing {task_id} ...", end=" ", flush=True)

        if task_id in cache_lookup:
            print("CACHED")
            results.append(cache_lookup[task_id])
            cached_count += 1
            continue

        print("LLM")

        instance = build_instance(row)
        filled_prompt = build_prompt(template, instance)

        raw_output = ""
        predicted_test = ""
        error_message = None
        input_tokens = 0
        output_tokens = 0
        llm_time_seconds = 0.0

        try:
            t_start = time.time()

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[
                    {
                        "role": "user",
                        "content": filled_prompt,
                    }
                ],
            )

            t_end = time.time()
            llm_time_seconds = round(t_end - t_start, 3)
            total_llm_time_seconds += llm_time_seconds

            raw_output = extract_text_from_response(response)
            predicted_test = extract_differentiating_test(raw_output)

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

        except Exception as exc:
            error_message = str(exc)
            print(f"  ERROR on {task_id}: {error_message}")

        results.append(
            {
                "task_id": task_id,
                "instance_id": row["instance_id"],
                "tool": tool_name,
                "prompt_type": prompt_type,
                "model": "claude-sonnet-4-6",
                "dataset_index": dataset_index,
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "FAIL_TO_PASS": row["FAIL_TO_PASS"],
                "PASS_TO_PASS": row["PASS_TO_PASS"],
                "input": {
                    "issue_statement": row["problem_statement"],
                    "plausible_patch": row["plausible_patch"],
                    "oracle_patch": row["oracle_patch"],
                },
                "prediction": {
                    "differentiating_test": predicted_test,
                },
                "raw_output": raw_output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "llm_time_seconds": llm_time_seconds,
                "error": error_message,
            }
        )

        # Save after each instance so progress is never lost
        with output_path.open("w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Save token and timing report
    with token_path.open("w", encoding="utf-8") as f:
        f.write(f"Prompt type          : {prompt_type}\n")
        f.write(f"Tool                 : {tool_name}\n")
        f.write(f"Model                : claude-sonnet-4-6\n")
        f.write(f"Dataset rows         : {len(rows)}\n")
        f.write(f"Instances run        : {len(subset)}\n")
        f.write(f"Cached instances     : {cached_count}\n")
        f.write(f"New LLM calls        : {len(subset) - cached_count}\n")
        f.write(f"Requested sample size: {sample_size}\n")
        f.write(f"Random seed          : {SEED}\n")
        f.write(f"Total input tokens   : {total_input_tokens}\n")
        f.write(f"Total output tokens  : {total_output_tokens}\n")
        f.write(f"Total LLM time (s)   : {round(total_llm_time_seconds, 3)}\n")
        f.write(f"Avg LLM time/call (s): {round(total_llm_time_seconds / max(1, len(subset) - cached_count), 3)}\n")

    print("\nDone.")
    print(f"Predictions saved to : {output_path}")
    print(f"Token report saved to: {token_path}")
    print(f"Cached instances     : {cached_count}")
    print(f"New LLM calls        : {len(subset) - cached_count}")
    print(f"Total input tokens   : {total_input_tokens}")
    print(f"Total output tokens  : {total_output_tokens}")
    print(f"Total LLM time (s)   : {round(total_llm_time_seconds, 3)}")


if __name__ == "__main__":
    main()
