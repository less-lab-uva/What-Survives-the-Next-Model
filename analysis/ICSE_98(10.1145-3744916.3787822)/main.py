import os
import sys
import json
import re
import anthropic
from datasets import load_dataset

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_SPLIT_FILE = os.path.join(BASE_DIR, "dataset", "id_split.json")

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


def load_paper_test_ids() -> dict:
    if not os.path.exists(ID_SPLIT_FILE):
        raise FileNotFoundError(f"Paper split file not found: {ID_SPLIT_FILE}")

    with open(ID_SPLIT_FILE) as f:
        split = json.load(f)

    test_ids = split.get("Test Ids")
    if not isinstance(test_ids, list):
        raise ValueError(f"'Test Ids' list not found in {ID_SPLIT_FILE}")

    selected = {
        "humaneval": {
            task_id for task_id in test_ids if task_id.startswith("HumanEval")
        },
        "mbpp": {
            task_id for task_id in test_ids if task_id.startswith("mbpp")
        },
    }
    expected_counts = {"humaneval": 40, "mbpp": 64}
    for dataset_name, expected_count in expected_counts.items():
        if len(selected[dataset_name]) == expected_count:
            continue
        raise ValueError(
            f"Expected {expected_count} {dataset_name} test IDs, "
            f"found {len(selected[dataset_name])}."
        )

    return selected


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
    response_text = response_text.strip()

    # Strategy 1: exact JSON object
    try:
        parsed = json.loads(response_text)
        code = parsed.get("generated_code", "") if isinstance(parsed, dict) else ""
        if code:
            return code.strip()
    except json.JSONDecodeError:
        pass

    # Strategy 2: ```java ... ```
    java_block = re.search(r"```java\s*(.*?)\s*```", response_text, re.DOTALL)
    if java_block:
        return java_block.group(1).strip()

    # Strategy 3: ```json {"generated_code": "..."} ```
    json_block = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_block:
        try:
            parsed = json.loads(json_block.group(1).strip())
            code = parsed.get("generated_code", "")
            if code:
                return code.strip()
        except json.JSONDecodeError:
            pass

    # Strategy 4: recover the JSON string value if the outer object is malformed.
    code_value = re.search(
        r'"generated_code"\s*:\s*("(?:\\.|[^"\\])*")',
        response_text,
        re.DOTALL,
    )
    if code_value:
        try:
            return json.loads(code_value.group(1)).strip()
        except json.JSONDecodeError:
            pass

    # Strategy 5: ``` ... ``` (generic, skip json blocks)
    plain_block = re.search(r"```(?!json)(?:[a-z]*)?\s*(.*?)\s*```", response_text, re.DOTALL)
    if plain_block:
        return plain_block.group(1).strip()

    # Strategy 6: return raw response
    return response_text.strip()


def strip_closing_braces(code: str) -> str:
    """
    The tests field in MultiPL-E already closes both the function and the class.
    Strip only the method and class braces requested from the model.
    """
    lines = code.rstrip().splitlines()
    for _ in range(2):
        if not lines or lines[-1].strip() != "}":
            break
        lines.pop()
    return "\n".join(lines)


def assemble_evaluation(instance: dict, generated_code: str) -> dict:
    body = strip_closing_braces(generated_code)
    full_source = instance["prompt"] + body + "\n" + instance["tests"]

    return {
        "full_source": full_source,
        "pass@1"     : None,   # requires external Java execution
    }


def load_cached_results(prompt_label: str) -> dict:
    """Load previous generated outputs so repeated runs can skip LLM calls."""

    cache_lookup = {}
    cache_files = [
        os.path.join(BASE_DIR, "outputs", f"outputs_{prompt_label}.json"),
        os.path.join(BASE_DIR, "outputs", f"outputs_{prompt_label}_humaneval.json"),
        os.path.join(BASE_DIR, "outputs", f"outputs_{prompt_label}_mbpp.json"),
    ]
    for cache_file in cache_files:
        if not os.path.exists(cache_file):
            continue

        with open(cache_file) as f:
            cached_results = json.load(f)

        loaded = 0
        for result in cached_results:
            instance_name = result.get("instance_name")
            if instance_name and instance_name not in cache_lookup:
                cache_lookup[instance_name] = result
                loaded += 1

        print(f"Loaded {loaded} cached results from {cache_file}.")

    return cache_lookup


def run_instance(
    index: int,
    instance: dict,
    template: str,
    prompt_label: str,
    dataset_name: str,
) -> dict:
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
        "dataset"        : dataset_name,
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
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python main.py <A|B>")
        print("  A|B : which prompt template to use (prompt_A.txt or prompt_B.txt)")
        sys.exit(1)

    prompt_label = sys.argv[1].upper()

    # -- Load prompt template --
    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{prompt_label}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from : {prompt_file}")

    # -- Load and combine the paper's held-out MultiPL-E tasks --
    paper_test_ids = load_paper_test_ids()
    datasets = {
        "humaneval": load_humaneval_java(),
        "mbpp": load_mbpp_java(),
    }
    selected_instances = []
    for dataset_name, ds in datasets.items():
        found_ids = set()
        for index, row in enumerate(ds):
            instance_name = row.get("name")
            if instance_name not in paper_test_ids[dataset_name]:
                continue
            selected_instances.append(
                (dataset_name, index, get_instance(ds, index))
            )
            found_ids.add(instance_name)

        missing_ids = sorted(paper_test_ids[dataset_name] - found_ids)
        if missing_ids:
            raise ValueError(
                f"{len(missing_ids)} {dataset_name} paper test IDs were not found: "
                + ", ".join(missing_ids)
            )

    print(f"HumanEval test instances     : {len(paper_test_ids['humaneval'])}")
    print(f"MBPP test instances          : {len(paper_test_ids['mbpp'])}")
    print(f"Combined MultiPL-E instances : {len(selected_instances)}")
    print(f"Paper split file            : {ID_SPLIT_FILE}")

    # -- Load cached results from previous runs --
    cache_lookup = load_cached_results(prompt_label)

    # -- Loop over instances --
    all_results     = []
    n_success       = 0
    n_api_error     = 0
    n_parse_fail    = 0
    n_cached        = 0
    total_input_tok = 0
    total_output_tok= 0

    for dataset_name, index, instance in selected_instances:
        cache_key = instance["name"]
        if cache_key in cache_lookup:
            print(f"\n[{dataset_name}:{index}] {instance['name']}")
            print(f"  Cache         : HIT")
            result = dict(cache_lookup[cache_key])
            result["dataset"] = dataset_name
            if not result.get("api_error") and result.get("raw_output"):
                generated_code = extract_generated_code(result["raw_output"])
                result["generated_code"] = generated_code
                result["parse_failure"] = not bool(generated_code)
                result["evaluation"] = (
                    assemble_evaluation(instance, generated_code)
                    if generated_code
                    else {}
                )
            n_cached += 1
        else:
            result = run_instance(
                index, instance, template, prompt_label, dataset_name
            )

        all_results.append(result)

        if cache_key not in cache_lookup:
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
    combined_path = os.path.join(outputs_dir, f"outputs_{prompt_label}.json")
    
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2)

    # -- Save token usage --
    token_path = os.path.join(outputs_dir, f"tokens_{prompt_label}.txt")
    with open(token_path, "w") as f:
        f.write(f"Prompt          : {prompt_label}\n")
        f.write("Dataset         : MultiPL-E Java held-out test subset\n")
        f.write(f"Instances run   : {len(selected_instances)}\n")
        f.write(f"HumanEval       : {len(paper_test_ids['humaneval'])}\n")
        f.write(f"MBPP            : {len(paper_test_ids['mbpp'])}\n")
        f.write(f"Split file      : {ID_SPLIT_FILE}\n")
        f.write(f"Cached results  : {n_cached}\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    # -- Summary --
    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"{'='*60}")
    print(f"  Prompt          : {prompt_label}")
    print(f"  Dataset         : MultiPL-E Java held-out test subset")
    print(f"  Instances run   : {len(selected_instances)}")
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
