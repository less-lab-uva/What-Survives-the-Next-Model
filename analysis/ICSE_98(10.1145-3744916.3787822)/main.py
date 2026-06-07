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

def load_mbpp_java():
    print("Loading dataset...")
    ds = load_dataset("nuprl/MultiPL-E", "mbpp-java", split="test")
    print(f"Loaded {len(ds)} instances.")
    return ds

def load_humaneval_java():
    
    print("Loading dataset...")
    ds = load_dataset("nuprl/MultiPL-E", "humaneval-java", split="test")
    print(f"Loaded {len(ds)} instances.")
    return ds


def get_instance(ds, index: int) -> dict:
    
    instance = ds[index]
    return {
        "name"  : instance.get("name", f"instance_{index}"),
        "prompt": instance["prompt"],   # description + signature (raw LLM input)
        "tests" : instance["tests"],    # retained for external pass@1 evaluation only
    }


def load_prompt_template(template_path: str) -> str:
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    with open(template_path) as f:
        return f.read()


def build_prompt(prompt_text: str, instance: dict) -> str:
    
    input_block = json.dumps({
        "prompt": instance["prompt"]
    }, indent=2)

    return (
        prompt_text
        + f"\n\n---\n\n"
        + input_block
    )


def extract_generated_code(response_text: str) -> str:
    # Strategy 1: ```java ... ```
    java_block = re.search(r"```java\s*(.*?)\s*```", response_text, re.DOTALL)
    if java_block:
        return java_block.group(1).strip()

    # Strategy 2: ```json {"generated_code": "..."} ```
    json_block = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_block:
        try:
            parsed = json.loads(json_block.group(1).strip())
            code = parsed.get("generated_code", "")
            if code:
                return code.strip()
        except json.JSONDecodeError:
            pass

    # Strategy 3: ``` ... ``` (generic, skip json blocks)
    plain_block = re.search(r"```(?!json)(?:[a-z]*)?\s*(.*?)\s*```", response_text, re.DOTALL)
    if plain_block:
        return plain_block.group(1).strip()

    # Strategy 4: return raw response
    return response_text.strip()


def strip_closing_braces(code: str) -> str:
    """
    The tests field in MultiPL-E already closes both the function and the class.
    Strip the trailing } lines the model added to avoid double-closing.
    """
    lines = code.rstrip().splitlines()
    while lines and lines[-1].strip() == "}":
        lines.pop()
    return "\n".join(lines)


def assemble_evaluation(instance: dict, generated_code: str) -> dict:
    body = strip_closing_braces(generated_code)
    full_source = instance["prompt"] + body + "\n" + instance["tests"]

    return {
        "full_source": full_source,
        "pass@1"     : None,   # requires external Java execution
    }


def load_cached_results(prompt_label: str, dataset_name: str) -> dict:
    """Load previous results so repeated random samples can skip LLM calls."""

    cache_lookup = {}
    candidate_cache_files = [
        os.path.join(BASE_DIR, "outputs", f"outputs_{prompt_label}_{dataset_name}.json"),
        os.path.join(BASE_DIR, "results", f"results_{prompt_label}_{dataset_name}.json"),
    ]

    for cache_file in candidate_cache_files:
        if not os.path.exists(cache_file):
            continue

        with open(cache_file) as f:
            cached_results = json.load(f)

        for result in cached_results:
            if "instance_index" in result:
                cache_lookup[result["instance_index"]] = result

        print(f"Loaded {len(cache_lookup)} cached results from {cache_file}.")
        break

    return cache_lookup


def run_instance(index: int, instance: dict, template: str, prompt_label: str) -> dict:
    """Run the full pipeline for a single dataset instance and return the result dict."""

    print(f"\n[{index}] {instance['name']}")
    print(f"  Prompt length : {len(instance['prompt'])} chars")

    filled_prompt = build_prompt(template, instance)

    # -- LLM call --
    api_error     = False
    raw_output    = ""
    input_tokens  = 0
    output_tokens = 0

    try:
        with client.messages.stream(
            model      = "claude-sonnet-4-6",
            max_tokens = 4096,
            messages   = [{"role": "user", "content": filled_prompt}],
        ) as stream:
            final_msg     = stream.get_final_message()
            raw_output    = final_msg.content[0].text
            input_tokens  = final_msg.usage.input_tokens
            output_tokens = final_msg.usage.output_tokens
        print(f"  LLM call      : OK")
        print(f"  Tokens        : {input_tokens} in / {output_tokens} out")
    except Exception as e:
        print(f"  LLM call      : ERROR — {e}")
        api_error = True

    # -- Parse output --
    generated_code = ""
    parse_failure  = False

    if not api_error:
        generated_code = extract_generated_code(raw_output)
        if not generated_code:
            parse_failure = True
            print(f"  Parse         : WARNING — could not extract generated code")
        else:
            print(f"  Generated     : {len(generated_code)} chars")

    # -- Assemble evaluation artifacts --
    evaluation = {}
    if not api_error and not parse_failure:
        evaluation = assemble_evaluation(instance, generated_code)

    # -- Tally return --
    return {
        "instance_index" : index,
        "instance_name"  : instance["name"],
        "prompt"         : prompt_label,
        "api_error"      : api_error,
        "parse_failure"  : parse_failure,
        "generated_code" : generated_code,
        "evaluation"     : evaluation,
        "raw_output"     : raw_output,
        "input_tokens"   : input_tokens,
        "output_tokens"  : output_tokens,
    }


def main():
    if len(sys.argv) != 3 or sys.argv[1].upper() not in ("A", "B") or sys.argv[2].lower() not in ("humaneval", "mbpp"):
        print("Usage: python main.py <A|B> <humaneval|mbpp>")
        print("  A|B : which prompt template to use (prompt_A.txt or prompt_B.txt)")
        sys.exit(1)

    prompt_label = sys.argv[1].upper()

    SEED = 42

    # -- Load prompt template --
    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{prompt_label}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from : {prompt_file}")

    # -- Load dataset --
    dataset_name = sys.argv[2].lower()
    if dataset_name == "humaneval":
        ds = load_humaneval_java()
    elif dataset_name == "mbpp":
        ds = load_mbpp_java()
    else:
        print("ERROR: dataset must be 'humaneval' or 'mbpp'")
        sys.exit(1)
    
    total = len(ds)

    sample_size = total
    random.seed(SEED)
    indices = sorted(random.sample(range(total), sample_size))

    print(f"Dataset size                : {total} instances")
    print(f"Selected instances          : {sample_size} instances (full dataset, seed={SEED})")
    print(f"Sampled indices             : {indices}")

    # -- Load cached results from previous runs --
    cache_lookup = load_cached_results(prompt_label, dataset_name)

    # -- Loop over instances --
    all_results     = []
    n_success       = 0
    n_api_error     = 0
    n_parse_fail    = 0
    n_cached        = 0
    total_input_tok = 0
    total_output_tok= 0

    for index in indices:
        instance = get_instance(ds, index)

        if index in cache_lookup:
            print(f"\n[{index}] {instance['name']}")
            print(f"  Cache         : HIT")
            result = cache_lookup[index]
            n_cached += 1
        else:
            result = run_instance(index, instance, template, prompt_label)

        all_results.append(result)

        if index not in cache_lookup:
            total_input_tok  += result["input_tokens"]
            total_output_tok += result["output_tokens"]

        if result["api_error"]:
            n_api_error += 1
        elif result["parse_failure"]:
            n_parse_fail += 1
        else:
            n_success += 1

    # -- Save combined results --
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    combined_path = os.path.join(outputs_dir, f"outputs_{prompt_label}_{dataset_name}.json")
    
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2)

    # -- Save token usage --
    token_path    = os.path.join(outputs_dir, f"tokens_{prompt_label}_{dataset_name}.txt")
    with open(token_path, "w") as f:
        f.write(f"Prompt          : {prompt_label}\n")
        f.write(f"Instances run   : {len(indices)} (full dataset, seed={SEED})\n")
        f.write(f"Cached results  : {n_cached}\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    # -- Summary --
    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"{'='*60}")
    print(f"  Prompt          : {prompt_label}")
    print(f"  Instances run   : {len(indices)} (full dataset, seed={SEED})")
    print(f"  Cached results  : {n_cached}")
    print(f"  Succeeded       : {n_success}")
    print(f"  API errors      : {n_api_error}")
    print(f"  Parse failures  : {n_parse_fail}")
    print(f"  Total input tok : {total_input_tok}")
    print(f"  Total output tok: {total_output_tok}")
    print(f"  Results saved to: {combined_path}")
    print(f"  Tokens saved to : {token_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
