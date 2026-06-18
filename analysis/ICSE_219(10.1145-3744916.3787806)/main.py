import os
import sys
import json
import re
import random
import anthropic
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts"
DATASETS_DIR = BASE_DIR / "dataset"
OUTPUTS_DIR = BASE_DIR / "outputs"

DATASET_NAMES = ["bp", "fsd", "lmc", "pure", "rac", "us"]

    

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)


def load_jsonl_dataset(dataset_name: str) -> List[Dict[str, Any]]:

    path = DATASETS_DIR / f"{dataset_name}.jsonl"

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {path}. Expected local datasets under {DATASETS_DIR}."
        )

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {path}: {exc}"
                ) from exc

            if "content" not in row or "plantuml" not in row:
                raise ValueError(
                    f"Row {line_number} of {path} does not contain both "
                    "'content' and 'plantuml' fields."
                )

            rows.append(row)

    if not rows:
        raise ValueError(f"No rows loaded from dataset file: {path}")

    print(f"Loaded {len(rows)} rows from: {path}")
    return rows



def load_prompt_template(prompt_type: str, dataset_name: str) -> str:

    prompt_type = prompt_type.upper()
    prompt_path = PROMPTS_DIR / f"prompt_{prompt_type}_{dataset_name}.txt"

    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {prompt_path}. "
            "Create dataset-specific prompt files such as "
            "ICSE_R219/prompts/prompt_A_bp.txt and "
            "ICSE_R219/prompts/prompt_B_bp.txt first."
        )

    print(f"Loaded prompt file: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def build_instance(row: Dict[str, Any]) -> Dict[str, str]:

    return {
        "content": row["content"]
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


def extract_plantuml(raw_output: str) -> str:

    output = raw_output.strip()

    # Preferred case: exact JSON object.
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict) and isinstance(parsed.get("plantuml"), str):
            return parsed["plantuml"]
    except json.JSONDecodeError:
        pass

    # Common violation: JSON wrapped in a markdown fence.
    fenced_json_match = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        output,
        flags=re.DOTALL,
    )
    if fenced_json_match:
        try:
            parsed = json.loads(fenced_json_match.group(1))
            if isinstance(parsed, dict) and isinstance(parsed.get("plantuml"), str):
                return parsed["plantuml"]
        except json.JSONDecodeError:
            pass

    # Common violation: raw PlantUML wrapped in a code fence.
    fenced_code_match = re.search(
        r"```(?:plantuml)?\s*(.*?)\s*```",
        output,
        flags=re.DOTALL,
    )
    if fenced_code_match:
        return fenced_code_match.group(1).strip()

    # Final fallback: retain the raw text exactly as the model generated it.
    return output



def sample_rows(rows,fraction, seed, limit):

    if not 0 < fraction <= 1.0:
        raise ValueError("SAMPLE_FRACTION must be greater than 0 and at most 1.0.")

    total_size = len(rows)

    if fraction == 1.0:
        selected_indices = list(range(total_size))
    else:
        sample_size = max(1, round(total_size * fraction))
        random.seed(seed)
        selected_indices = sorted(random.sample(range(total_size), sample_size))

    if limit is not None:
        selected_indices = selected_indices[:limit]

    selected = []
    for index in selected_indices:
        row = dict(rows[index])
        row["_dataset_index"] = index
        selected.append(row)

    return selected



def main():

    if len(sys.argv) != 3:
        print("Usage: python main.py <A|B> <dataset>")
        print("Datasets: bp, fsd, lmc, pure, rac, us")
        sys.exit(1)

    prompt_type = sys.argv[1].upper()
    dataset_name = sys.argv[2].lower()

    if prompt_type not in ("A", "B"):
        print("ERROR: first argument must be A or B")
        sys.exit(1)

    if dataset_name not in DATASET_NAMES:
        print("ERROR: dataset must be one of: bp, fsd, lmc, pure, rac, us")
        sys.exit(1)

    # Load the dataset-specific prompt template.
    prompt_path = PROMPTS_DIR / f"prompt_{prompt_type}_{dataset_name}.txt"
    template = load_prompt_template(prompt_type, dataset_name)
    print(f"Loaded prompt type: {prompt_type}")

    # Load dataset and choose evaluation subset.
    SAMPLE_FRACTION = 1
    SEED = 42
    rows = load_jsonl_dataset(dataset_name)
    subset = sample_rows(
        rows=rows,
        fraction=SAMPLE_FRACTION,
        seed=SEED,
        limit=None,
    )

    print(
        f"Running {len(subset)} of {len(rows)} rows "
        f"(fraction={SAMPLE_FRACTION}, seed={SEED}).\n"
    )

    # Output paths.
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = (
        OUTPUTS_DIR
        / f"outputs_{prompt_type}_{dataset_name}.jsonl"
    )
    token_path = (
        OUTPUTS_DIR
        / f"tokens_{prompt_type}_{dataset_name}.txt"
    )

    # Load cached predictions from a previous run of this prompt/dataset.
    cache_lookup: Dict[str, Dict[str, Any]] = {}
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    cached_result = json.loads(line)
                except json.JSONDecodeError:
                    print(f"WARNING: skipping invalid cached JSON on line {line_number}")
                    continue

                task_id = cached_result.get("task_id")
                if not task_id and "dataset_index" in cached_result:
                    task_id = f"{dataset_name}_{int(cached_result['dataset_index']):04d}"

                if task_id:
                    cache_lookup[task_id] = cached_result

        print(f"Loaded {len(cache_lookup)} cached results from {output_path}.\n")

    results: List[Dict[str, Any]] = []
    cached_count = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for index, row in enumerate(subset):
        dataset_index = row.get("_dataset_index", index)
        task_id = f"{dataset_name}_{dataset_index:04d}"
        print(f"[{index + 1}/{len(subset)}] Processing {task_id} ...", end=" ", flush=True)

        if task_id in cache_lookup:
            print("CACHED")
            results.append(cache_lookup[task_id])
            cached_count += 1
            continue

        print("LLM")

        # Only raw input is sent to the model.
        instance = build_instance(row)
        filled_prompt = build_prompt(template, instance)

        raw_output = ""
        predicted_plantuml = ""
        error_message = None
        input_tokens = 0
        output_tokens = 0

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[
                    {
                        "role": "user",
                        "content": filled_prompt,
                    }
                ],
            )

            raw_output = extract_text_from_response(response)
            predicted_plantuml = extract_plantuml(raw_output)

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
                "dataset": dataset_name,
                "prompt_type": prompt_type,
                "model": "claude-sonnet-4-6",
                "dataset_index": dataset_index,
                "input": {
                    "content": row["content"],
                },
                "prediction": {
                    "plantuml": predicted_plantuml,
                },
                "reference": {
                    "plantuml": row["plantuml"],
                },
                "raw_output": raw_output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error": error_message,
            }
        )

    # Save one JSON object per line for later evaluation.
    with output_path.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")

    with token_path.open("w", encoding="utf-8") as file:
        file.write(f"Prompt type      : {prompt_type}\n")
        file.write(f"Dataset          : {dataset_name}\n")
        file.write("Model             : claude-sonnet-4-6\n")
        file.write(f"Prompt file      : {prompt_path}\n")
        file.write(f"Dataset rows     : {len(rows)}\n")
        file.write(f"Instances run    : {len(subset)}\n")
        file.write(f"Cached instances : {cached_count}\n")
        file.write(f"New LLM calls    : {len(subset) - cached_count}\n")
        file.write(f"Sampling fraction: {SAMPLE_FRACTION}\n")
        file.write(f"Random seed      : {SEED}\n")
        file.write(f"Total input tok  : {total_input_tokens}\n")
        file.write(f"Total output tok : {total_output_tokens}\n")

    print("\nDone.")
    print(f"Predictions saved to: {output_path}")
    print(f"Token report saved to: {token_path}")
    print(f"Cached instances : {cached_count}")
    print(f"New LLM calls    : {len(subset) - cached_count}")
    print(f"Total input tokens : {total_input_tokens}")
    print(f"Total output tokens: {total_output_tokens}")


if __name__ == "__main__":
    main()
