import os
import sys
import json
import re
import random
import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
INSTANCES_FILE = os.path.join(BASE_DIR, "instances.json")


def load_prompt_template(template_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template file not found: {template_path}")
    with open(template_path) as f:
        return f.read()


def build_prompt(template, preceding_code, call_line):
    instance = json.dumps({
        "preceding_code": preceding_code,
        "call_line":      call_line,
    }, indent=2)
    return (
        template
        + f"\n\n---\n\n"
        + f"{instance}"
    )


def extract_predictions(response_text: str) -> list[dict]:


    json_block = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_block:
        result = _parse_json_str(json_block.group(1))
        if result is not None:
            return result

    plain_block = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if plain_block:
        result = _parse_json_str(plain_block.group(1))
        if result is not None:
            return result

    obj_match = re.search(
        r'\{[^{}]*"arguments"\s*:\s*\[.*?\]\s*\}',
        response_text,
        re.DOTALL
    )
    if obj_match:
        result = _parse_json_str(obj_match.group(0))
        if result is not None:
            return result

    all_objects = list(re.finditer(r'\{.*?\}', response_text, re.DOTALL))
    for match in reversed(all_objects):
        result = _parse_json_str(match.group(0))
        if result is not None:
            return result

    array_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
    if array_match:
        result = _parse_json_str(array_match.group(0))
        if result is not None:
            return result

    return [{"position": 0, "value": response_text.strip()}]


def _parse_json_str(text: str) -> list[dict] | None:

    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and "arguments" in data:
        args = data["arguments"]
        if isinstance(args, list):
            return _normalise_args(args)

    if isinstance(data, dict) and "completions" in data:
        completions = data["completions"]
        result = []
        for comp in completions:
            pos = comp.get("position", len(result))
            suggestions = comp.get("ranked_suggestions", [])
            value = suggestions[0] if suggestions else ""
            result.append({"position": pos, "value": str(value)})
        return sorted(result, key=lambda x: x["position"]) if result else None

    
    if isinstance(data, list):
        return _normalise_args(data)

    return None


def _normalise_args(args: list) -> list[dict] | None:

    if not args:
        return None

    result = []

    for i, item in enumerate(args):
        if isinstance(item, dict):
            
            if "value" in item:
                pos = item.get("position", i)
                result.append({"position": int(pos), "value": str(item["value"])})
            
            elif "ranked_suggestions" in item:
                pos = item.get("position", i)
                suggestions = item["ranked_suggestions"]
                value = suggestions[0] if suggestions else ""
                result.append({"position": int(pos), "value": str(value)})
            else:
                
                continue
        else:
            
            result.append({"position": i, "value": str(item)})

    if not result:
        return None

    return sorted(result, key=lambda x: x["position"])



def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python main.py <A|B>")
        sys.exit(1)

    prompt_label = sys.argv[1].upper()
    prompt_file  = os.path.join(BASE_DIR, "prompts", f"prompt_{prompt_label}.txt")
    template     = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from: {prompt_file}")

    with open(INSTANCES_FILE) as f:
        instances = json.load(f)
    total_instances = len(instances)
    print(f"Loaded {total_instances} instances from {INSTANCES_FILE}.")

    SEED        = 42
    sample_size = 400
    random.seed(SEED)
    sampled_indices = sorted(random.sample(range(total_instances), sample_size))
    subset = [instances[i] for i in sampled_indices]
    print(f"Randomly sampled {sample_size} instances (seed={SEED}).")

    # ── Load cached results from any previous run 
    
    cache_lookup = {}
    candidate_cache_files = [
        os.path.join(BASE_DIR, "outputs", f"outputs_{prompt_label}.jsonl"),
        os.path.join(BASE_DIR, f"outputs_prompt_{prompt_label.lower()}.jsonl"),
    ]
    for cache_file in candidate_cache_files:
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        r = json.loads(line)
                        key = (r["filepath"], r["call_line"])
                        cache_lookup[key] = r
            print(f"Loaded {len(cache_lookup)} cached results from {cache_file}.")
            break

    results          = []
    parse_failures   = 0
    api_errors       = 0
    cached_count     = 0
    total_input_tok  = 0
    total_output_tok = 0

    for i, inst in enumerate(subset):
        preceding_code = inst["preceding_code"]
        call_line      = inst["masked_call"] if "masked_call" in inst else inst["call_line"]
        ground_truth   = inst["ground_truth"]
        cache_key      = (inst["filepath"], call_line)

        print(f"[{i+1}/{sample_size}] {inst['filepath']} ...", end=" ", flush=True)

        if cache_key in cache_lookup:
            print(f"CACHED")
            results.append(cache_lookup[cache_key])
            cached_count += 1
            continue

        filled_prompt = build_prompt(template, preceding_code, call_line)

        try:
            response   = client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = 512,
                messages   = [{"role": "user", "content": filled_prompt}]
            )

            raw_output  = response.content[0].text
            predictions = extract_predictions(raw_output)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens

            num_expected = len(ground_truth)
            predictions  = predictions[:num_expected]

            if (
                len(predictions) == 1
                and predictions[0]["value"] == raw_output.strip()
            ):
                parse_failures += 1
                print(f"WARNING: could not parse JSON from response")
            else:
                print(f"OK — {len(predictions)} arg(s) predicted")

        except Exception as e:
            print(f"ERROR: {e}")
            predictions = []
            raw_output  = ""
            api_errors  += 1

        results.append({
            "filepath":     inst["filepath"],
            "call_line":    call_line,
            "ground_truth": ground_truth,
            "arguments":    predictions,
            "raw_output":   raw_output,
        })


    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    output_path = os.path.join(outputs_dir, f"outputs_{prompt_label}.jsonl")
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    token_path = os.path.join(outputs_dir, f"tokens_{prompt_label}.txt")
    with open(token_path, "w") as f:
        f.write(f"Prompt          : {prompt_label}\n")
        f.write(f"Instances run   : {sample_size} (random sample, seed={SEED})\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")


    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"{'='*60}")
    print(f"  Prompt          : {prompt_label}")
    print(f"  Instances run   : {sample_size} (random sample, seed={SEED})")
    print(f"  From cache      : {cached_count}")
    print(f"  New LLM calls   : {sample_size - cached_count}")
    print(f"  API errors      : {api_errors}")
    print(f"  Parse failures  : {parse_failures}")
    print(f"  Total input tok : {total_input_tok}")
    print(f"  Total output tok: {total_output_tok}")
    print(f"  Results saved to: {output_path}")
    print(f"  Tokens saved to : {token_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
