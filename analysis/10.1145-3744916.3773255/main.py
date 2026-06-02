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


def load_prompt_template(template_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template file not found: {template_path}")
    with open(template_path, "r") as f:
        return f.read()


def build_prompt(template, prompt, test, entry_point):
    instance = json.dumps({"prompt": prompt, "test": test, "entry_point": entry_point}, indent=2)
    return template + f"\n\n---\n\n## YOUR TASK — DO NOT solve the example above. Solve only the following instance and generate the output in the specified format:\n\n{instance}"


def extract_code(response_text):
    match = re.search(r"```python\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response_text.strip()


def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python single_llm.py <A|B>")
        sys.exit(1)

    prompt_file = os.path.join("prompts", f"prompt_{sys.argv[1].upper()}.txt")
    template = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from {prompt_file}.")

    dataset = load_dataset("openai_humaneval", split="test")
    print(f"Loaded {len(dataset)} problems.")

    # SEED = 42
    # sample_size = max(1, int(0.1 * len(dataset)))
    # random.seed(SEED)
    # sampled_indices = sorted(random.sample(range(len(dataset)), sample_size))
    # print(f"Randomly sampled {sample_size} instances (10%, seed={SEED}): indices {sampled_indices}")

    results          = []
    total_input_tok  = 0
    total_output_tok = 0

    for i, row in enumerate(dataset):
        task_id = row["task_id"]
        prompt = row["prompt"]
        test = row["test"]
        entry_point = row["entry_point"]

        print(f"[{i+1}/{len(dataset)}] Processing {task_id} ...")

        filled_prompt = build_prompt(template, prompt, test, entry_point)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": filled_prompt}]
            )
            raw_output = response.content[0].text
            corrected_code = extract_code(raw_output)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens

        except Exception as e:
            print(f"  ERROR on {task_id}: {e}")
            corrected_code = ""
            raw_output = ""

        results.append({
            "task_id": task_id,
            "completion": corrected_code,
            "raw_output": raw_output
        })

    output_path = os.path.join("outputs", f"outputs_{sys.argv[1].upper()}.jsonl")
    os.makedirs("outputs", exist_ok=True)
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"\nDone. Results saved to {output_path}")
    print(f"Total input tok : {total_input_tok}")
    print(f"Total output tok: {total_output_tok}")


if __name__ == "__main__":
    main()