import os
import sys
import json
import re
import random
from pathlib import Path
import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise EnvironmentError("ANTHROPIC_API_KEY not found. Run 'source ~/.bashrc' first.")

client = anthropic.Anthropic(api_key=api_key)

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
XCODEEVAL_DIR  = Path(BASE_DIR) / "xCodeEval"
APR_TEST_DIR   = XCODEEVAL_DIR / "apr" / "validation"
PROB_DESC_FILE = XCODEEVAL_DIR / "problem_descriptions.jsonl"
UNITTEST_FILE  = XCODEEVAL_DIR / "unittest_db.json"

LANGUAGES = [
    "C", "C#", "C++", "Go", "Java", "Javascript",
    "Kotlin", "PHP", "Python", "Ruby", "Rust"
]


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_prob_descs(path):
    desc_map = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                desc_map[obj["src_uid"]] = obj
    return desc_map


def load_unittest_db(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_dataset():
    print("Loading instances...")
    all_instances = []
    for lang in LANGUAGES:
        fpath = APR_TEST_DIR / f"{lang}.jsonl"
        if fpath.exists():
            records = load_jsonl(fpath)
            all_instances.extend(records)
            print(f"  {lang:<15} {len(records)} instances")
        else:
            print(f"  {lang:<15} NOT FOUND — skipping")

    print(f"  Total: {len(all_instances)} instances\n")

    print("Joining problem descriptions...")
    desc_map = load_prob_descs(PROB_DESC_FILE)
    for inst in all_instances:
        uid = inst.get("src_uid")
        if uid in desc_map:
            inst.update(desc_map[uid])

    print("Joining unit tests...")
    unittest_db = load_unittest_db(UNITTEST_FILE)
    for inst in all_instances:
        uid = inst.get("src_uid")
        if uid in unittest_db:
            inst["hidden_unit_tests"] = unittest_db[uid]

    print(f"Dataset ready: {len(all_instances)} fully joined instances.\n")
    return all_instances


def load_prompt_template(template_path):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    with open(template_path, "r") as f:
        return f.read()


def build_prompt(template, instance):
    """Inject the instance fields into the prompt template."""
    task_input = {
        "lang_cluster":      instance.get("lang_cluster", ""),
        "lang":              instance.get("lang", ""),
        "bug_exec_outcome":  instance.get("bug_exec_outcome", ""),
        "difficulty":        instance.get("difficulty", ""),
        "tags":              instance.get("tags", []),
        "description":       instance.get("description", ""),
        "time_limit":        instance.get("time_limit", ""),
        "memory_limit":      instance.get("memory_limit", ""),
        "input_spec":        instance.get("input_spec", ""),
        "output_spec":       instance.get("output_spec", ""),
        "sample_inputs":     instance.get("sample_inputs", []),
        "sample_outputs":    instance.get("sample_outputs", []),
        "notes":             instance.get("notes", ""),
        "bug_source_code":   instance.get("bug_source_code", ""),
    }
    instance_block = json.dumps(task_input, indent=2)
    return (
        template
        + "\n\n---\n\n"
        + instance_block
    )


def extract_code(response_text, lang_cluster):

    lang_map = {
        "C":          ["c"],
        "C#":         ["csharp", "cs"],
        "C++":        ["cpp", "c++"],
        "Go":         ["go"],
        "Java":       ["java"],
        "Javascript": ["javascript", "js"],
        "Kotlin":     ["kotlin", "kt"],
        "PHP":        ["php"],
        "Python":     ["python", "py"],
        "Ruby":       ["ruby", "rb"],
        "Rust":       ["rust", "rs"],
    }
    fences = lang_map.get(lang_cluster, [])
    for fence in fences:
        match = re.search(rf"```{fence}\n(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    # generic fenced block
    match = re.search(r"```\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response_text.strip()


def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python main.py <A|B>")
        sys.exit(1)

    variant = sys.argv[1].upper()

    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{variant}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from {prompt_file}.")

    all_instances = load_dataset()

    # Group by language, sample 5% from each language
    from collections import defaultdict
    lang_groups = defaultdict(list)
    for inst in all_instances:
        lang_groups[inst.get("lang_cluster", "unknown")].append(inst)

    SEED = 42
    random.seed(SEED)
    subset = []
    
    for lang in sorted(lang_groups):
        group = lang_groups[lang]
        n = max(1, int(0.05 * len(group)))
        sampled = random.sample(group, n)
        subset.extend(sampled)
        print(f"  {lang:<15} {n}/{len(group)}")
    sample_size = len(subset)
    print(f"Total sampled: {sample_size} instances (5% per language, seed={SEED}).")

    # Load cache from any previous run
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    output_path = os.path.join(outputs_dir, f"outputs_{variant}.jsonl")
    cache_lookup = {}
    if os.path.exists(output_path):
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if "apr_id" in r:
                        cache_lookup[r["apr_id"]] = r
        print(f"Loaded {len(cache_lookup)} cached results from {output_path}.")

    results          = []
    total_input_tok  = 0
    total_output_tok = 0
    cached_count     = 0

    for i, inst in enumerate(subset):
        apr_id       = inst.get("apr_id", f"idx_{i}")
        lang_cluster = inst.get("lang_cluster", "unknown")
        outcome      = inst.get("bug_exec_outcome", "unknown")

        print(f"[{i+1}/{len(subset)}] apr_id={apr_id}  lang={lang_cluster}  outcome={outcome}", end=" ... ")

        if apr_id in cache_lookup:
            print("CACHED")
            results.append(cache_lookup[apr_id])
            cached_count += 1
            continue

        filled_prompt = build_prompt(template, inst)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": filled_prompt}]
            )
            raw_output   = response.content[0].text
            fixed_code   = extract_code(raw_output, lang_cluster)
            total_input_tok  += response.usage.input_tokens
            total_output_tok += response.usage.output_tokens
            print("OK")

        except Exception as e:
            print(f"ERROR: {e}")
            raw_output = ""
            fixed_code = ""

        results.append({
            "apr_id":             apr_id,
            "src_uid":            inst.get("src_uid", ""),
            "lang_cluster":       lang_cluster,
            "lang":               inst.get("lang", ""),
            "bug_exec_outcome":   outcome,
            "difficulty":         inst.get("difficulty", ""),
            "tags":               inst.get("tags", []),
            "bug_source_code":    inst.get("bug_source_code", ""),
            "fixed_source_code":  fixed_code,
            "hidden_unit_tests":  inst.get("hidden_unit_tests", []),
            "raw_output":         raw_output,
        })

    os.makedirs(outputs_dir, exist_ok=True)
    token_path  = os.path.join(outputs_dir, f"tokens_{variant}.txt")

    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    with open(token_path, "w") as f:
        f.write(f"Prompt          : {variant}\n")
        f.write(f"Instances run   : {sample_size} (5% stratified sample, seed={SEED})\n")
        f.write(f"Total input tok : {total_input_tok}\n")
        f.write(f"Total output tok: {total_output_tok}\n")

    print(f"\nDone. Results saved to {output_path}")
    print(f"Tokens saved to     : {token_path}")
    print(f"From cache          : {cached_count}")
    print(f"New LLM calls       : {sample_size - cached_count}")
    print(f"Total input tokens  : {total_input_tok}")
    print(f"Total output tokens : {total_output_tok}")
    print(f"Instances processed : {len(results)}")


if __name__ == "__main__":
    main()
