import os
import sys
import json
import re
import random
import argparse
import anthropic
from datasets import load_dataset

# API client
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError(
        "ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first."
    )
client = anthropic.Anthropic(api_key=api_key)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


DATASET_CONFIGS = {
    "humanevalplus": {
        "hf_path":  "evalplus/humanevalplus",
        "split":    "test",
        "task_id":  "task_id",
        "prompt":   "prompt",
        "test":     "test",
        "style":    "humaneval",
    },
    "humaneval": {
        "hf_path":  "openai/openai_humaneval",
        "split":    "test",
        "task_id":  "task_id",
        "prompt":   "prompt",
        "test":     "test",
        "style":    "humaneval",
    },
    "bigcodebench": {
        "hf_path":  "bigcode/bigcodebench",
        "split":    "v0.1.2",
        "task_id":  "task_id",
        "prompt":   "instruct_prompt",
        "test":     "test",
        "style":    "bigcodebench",
    },
    "classeval": {
        "hf_path":  "FudanSELab/ClassEval",
        "split":    "test",
        "task_id":  "task_id",
        "prompt":   "class_description",
        "test":     "test",
        "style":    "classeval",
        "skeleton": "skeleton",
    },
}



def parse_humaneval_prompt(raw_prompt: str):
    for quote in ('"""', "'''"):
        idx = raw_prompt.find(quote)
        if idx != -1:
            function_signature = raw_prompt[:idx].rstrip()
            end_idx = raw_prompt.find(quote, idx + 3)
            problem_description = raw_prompt[idx + 3:end_idx].strip()
            return function_signature, problem_description
    return raw_prompt.rstrip(), ""


def parse_bigcodebench_prompt(raw_prompt: str):
    return "", raw_prompt.strip()


def parse_classeval_prompt(raw_prompt: str, skeleton: str):
    return skeleton.strip(), raw_prompt.strip()


def build_instance(cfg: dict, row: dict) -> dict:
    style      = cfg["style"]
    raw_prompt = row[cfg["prompt"]]
    test_suite = row[cfg["test"]]

    if style == "humaneval":
        function_signature, problem_description = parse_humaneval_prompt(raw_prompt)
    elif style == "bigcodebench":
        function_signature, problem_description = parse_bigcodebench_prompt(raw_prompt)
    elif style == "classeval":
        skeleton = row.get(cfg.get("skeleton", "skeleton"), "")
        function_signature, problem_description = parse_classeval_prompt(raw_prompt, skeleton)
    else:
        function_signature, problem_description = raw_prompt, ""

    return {
        "function_signature":  function_signature,
        "problem_description": problem_description,
        "test_suite":          test_suite,
    }


def build_prompt(template: str, instance: dict) -> str:
    instance_json = json.dumps(instance, indent=2)
    return (
        template
        + "\n\n---\n\n"
        + instance_json
    )


def extract_code(response_text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1))
            if "completed_function" in obj:
                return obj["completed_function"]
        except json.JSONDecodeError:
            pass

    try:
        obj = json.loads(response_text.strip())
        if "completed_function" in obj:
            return obj["completed_function"]
    except json.JSONDecodeError:
        pass

    match = re.search(r"```python\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    match = re.search(r"```\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return response_text.strip()



def load_prompt_template(template_path: str) -> str:
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    with open(template_path, "r") as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(
        description="Run single-LLM code completion experiment across benchmarks."
    )
    parser.add_argument(
        "prompt_variant",
        choices=["A", "B"],
        help="Which prompt template to use: A (black-box) or B (informed).",
    )
    parser.add_argument(
        "dataset",
        choices=list(DATASET_CONFIGS.keys()),
        help="Which benchmark dataset to run on.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for 10%% sampling. Default: 42.",
    )
    args = parser.parse_args()

    

    # Prompt template
    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{args.prompt_variant.upper()}.txt")
    template = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from: {prompt_file}")

    # Dataset
    cfg = DATASET_CONFIGS[args.dataset]
    print(f"Loading dataset: {cfg['hf_path']} (split={cfg['split']}) ...")
    dataset = load_dataset(cfg["hf_path"], split=cfg["split"])
    total_size = len(dataset)
    print(f"Total problems: {total_size}")

    # Random 10% sample
    sample_size = max(1, int(0.10 * total_size))
    random.seed(args.seed)
    sampled_indices = sorted(random.sample(range(total_size), sample_size))
    subset = list(dataset.select(sampled_indices))
    print(f"Sampled {sample_size} problems (10%, seed={args.seed}).\n")
    

    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    output_path = os.path.join(outputs_dir, f"outputs_{args.prompt_variant.upper()}_{args.dataset}.jsonl")
    token_path  = os.path.join(outputs_dir, f"tokens_{args.prompt_variant.upper()}_{args.dataset}.txt")

    results          = []
    total            = len(subset)
    total_input_tok  = 0
    total_output_tok = 0

    for i, row in enumerate(subset):
        task_id = row[cfg["task_id"]]
        print(f"[{i+1}/{total}] Processing {task_id} ...")

        instance      = build_instance(cfg, row)
        filled_prompt = build_prompt(template, instance)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8096,
                messages=[{"role": "user", "content": filled_prompt}],
            )
            raw_output        = response.content[0].text
            completion        = extract_code(raw_output)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens

        except Exception as e:
            print(f"  ERROR on {task_id}: {e}")
            completion = ""
            raw_output = ""

        results.append({
            "task_id":    task_id,
            "completion": completion,
            "raw_output": raw_output,
        })

    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    with open(token_path, "w") as f:
        f.write(f"Prompt          : {args.prompt_variant.upper()}\n")
        f.write(f"Dataset         : {args.dataset}\n")
        f.write(f"Instances run   : {total} (10% random sample, seed={args.seed})\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    print(f"\nDone. {len(results)} results saved to: {output_path}")
    print(f"Tokens saved to : {token_path}")
    print(f"Total input tokens : {total_input_tok}")
    print(f"Total output tokens: {total_output_tok}")


if __name__ == "__main__":
    main()
