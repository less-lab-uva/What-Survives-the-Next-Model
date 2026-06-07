import os
import sys
import json
import random

import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
DATASET_FILE    = os.path.join(BASE_DIR, "dataset", "eval_instances_with_text.jsonl")


def load_eval_instances(path):
    instances = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    return instances


def load_dataset():
    print("Loading eval instances with license text...")
    instances = load_eval_instances(DATASET_FILE)

    missing_text = [
        inst.get("project_name", "")
        for inst in instances
        if not inst.get("license_text")
    ]
    if missing_text:
        raise ValueError(
            f"{len(missing_text)} instance(s) are missing license_text: {missing_text}"
        )

    print(f"  {len(instances)} instances ready from {DATASET_FILE}\n")
    return instances



def load_prompt_template(template_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    with open(template_path, encoding="utf-8") as f:
        return f.read()


def build_prompt(template, instance):
    task_input = {"license_text": instance["license_text"]}
    instance_block = json.dumps(task_input, indent=2)
    return (
        template
        + "\n\n---\n\n"
        + instance_block
    )



INT_FIELDS = [
    "copyright", "copyleft", "modification", "patent", "trademark",
    "interaction", "retain_attr", "acceptance", "enhance_attr", "patent_term",
]

def extract_pred_term(response_text):

    text = response_text.strip()

    # strip fences
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)

    # find first { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1:
        return {}

    try:
        raw = json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return {}

    pred = {}
    for field in INT_FIELDS:
        if field in raw:
            pred[field] = str(raw[field])

    # Usage Limitation: accept list or dict
    if "Usage Limitation" in raw:
        ul = raw["Usage Limitation"]
        if isinstance(ul, list):
            pred["Usage Limitation"] = ul
        elif isinstance(ul, dict):
            pred["Usage Limitation"] = list(ul.keys())

    def normalize_optional_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.keys())
        if isinstance(value, str):
            if value.strip().lower() in ("", "0", "null", "none", "[]"):
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    # pass through optional list fields (evaluator ignores if not in gt)
    for field in ("exception", "compatible_version", "secondary_license", "gpl_combine"):
        if field in raw:
            pred[field] = normalize_optional_list(raw[field])

    return pred



def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python main.py <A|B>")
        sys.exit(1)

    variant = sys.argv[1].upper()

    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{variant}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from {prompt_file}.")

    all_instances = load_dataset()
    total_size = len(all_instances)
    
    SEED = 42
    random.seed(SEED)
   
    n = total_size
    subset = random.sample(all_instances, n)
    
    print(f"Running on {len(subset)} instances (full eval set, seed={SEED}).\n")

    # --- load cache ---
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    output_path = os.path.join(outputs_dir, f"outputs_{variant}.jsonl")
    token_path  = os.path.join(outputs_dir, f"tokens_{variant}.txt")

    cache_lookup = {}
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    key = (r.get("project_name", ""), r.get("license_name", ""))
                    cache_lookup[key] = r
        print(f"Loaded {len(cache_lookup)} cached results from {output_path}.")

    results          = []
    total_input_tok  = 0
    total_output_tok = 0
    cached_count     = 0

    for i, inst in enumerate(subset):
        proj         = inst["project_name"]
        lic_name     = inst["license_name"]
        cache_key    = (proj, lic_name)

        print(f"[{i+1}/{len(subset)}] project={proj}  license={lic_name}", end=" ... ")

        if cache_key in cache_lookup:
            print("CACHED")
            results.append(cache_lookup[cache_key])
            cached_count += 1
            continue

        filled_prompt = build_prompt(template, inst)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": filled_prompt}]
            )
            raw_output        = response.content[0].text
            pred_term         = extract_pred_term(raw_output)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens
            print("OK")

        except Exception as e:
            print(f"ERROR: {e}")
            raw_output = ""
            pred_term  = {}

        results.append({
            "project_name":  proj,
            "license_name":  lic_name,
            "license_file":  inst.get("license_file", ""),
            "pred_term":     pred_term,
            "gt_term":       inst["term"],
            "raw_output":    raw_output,
        })

    # --- write outputs ---
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(f"Prompt variant  : {variant}\n")
        f.write(f"Instances run   : {len(subset)}\n")
        f.write(f"From cache      : {cached_count}\n")
        f.write(f"New LLM calls   : {len(subset) - cached_count}\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    print(f"\nDone.")
    print(f"Results saved to : {output_path}")
    print(f"Tokens saved to  : {token_path}")
    print(f"From cache       : {cached_count}")
    print(f"New LLM calls    : {len(subset) - cached_count}")
    print(f"Total input tok  : {total_input_tok}")
    print(f"Total output tok : {total_output_tok}")


if __name__ == "__main__":
    main()
