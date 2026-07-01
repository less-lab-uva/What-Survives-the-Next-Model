import os
import sys
import json
import re
import random
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List

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
OUTPUTS_DIR    = Path(BASE_DIR) / "outputs"

LANGUAGES = [
    "C", "C#", "C++", "Go", "Java", "Javascript",
    "Kotlin", "PHP", "Python", "Ruby", "Rust"
]

# Randomly choose this many languages from LANGUAGES, then sample the
# configured fraction of bugs independently within each selected language.
SEED = 42
NUM_LANGUAGES = 3
SAMPLE_FRACTION = 0.10
PASS_K = 5
MODEL = "claude-sonnet-4-6"


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
            print(f"  {lang:<15} NOT FOUND - skipping")

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
    match = re.search(r"```\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response_text.strip()


def make_sample_id(instance):
    return (
        f"{instance.get('lang_cluster', 'unknown')}:"
        f"{instance.get('_dataset_index', 'unknown')}:"
        f"{instance.get('apr_id', 'unknown')}"
    )


def make_request_hash(template, instance):
    request = {
        "template": template,
        "model": MODEL,
        "task_input": {
            "lang_cluster": instance.get("lang_cluster", ""),
            "lang": instance.get("lang", ""),
            "bug_exec_outcome": instance.get("bug_exec_outcome", ""),
            "difficulty": instance.get("difficulty", ""),
            "tags": instance.get("tags", []),
            "description": instance.get("description", ""),
            "time_limit": instance.get("time_limit", ""),
            "memory_limit": instance.get("memory_limit", ""),
            "input_spec": instance.get("input_spec", ""),
            "output_spec": instance.get("output_spec", ""),
            "sample_inputs": instance.get("sample_inputs", []),
            "sample_outputs": instance.get("sample_outputs", []),
            "notes": instance.get("notes", ""),
            "bug_source_code": instance.get("bug_source_code", ""),
        },
    }
    serialized = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def select_subset(all_instances):
    from collections import defaultdict

    rng = random.Random(SEED)
    lang_groups = defaultdict(list)
    for inst in all_instances:
        lang_groups[inst.get("lang_cluster", "unknown")].append(inst)

    available_languages = sorted(lang for lang in lang_groups if lang in LANGUAGES)
    selected_languages = sorted(rng.sample(available_languages, NUM_LANGUAGES))

    subset = []
    print(f"Randomly selected {NUM_LANGUAGES} languages (seed={SEED}): {selected_languages}")
    print(f"Sampling {int(SAMPLE_FRACTION * 100)}% per selected language:")

    for lang in selected_languages:
        group = lang_groups[lang]
        n = max(1, int(SAMPLE_FRACTION * len(group)))
        sampled_indices = sorted(rng.sample(range(len(group)), n))
        for dataset_index in sampled_indices:
            row = dict(group[dataset_index])
            row["_dataset_index"] = dataset_index
            subset.append(row)
        print(f"  {lang:<15} {n}/{len(group)}")

    return selected_languages, subset

def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python main_pass5.py <A|B>")
        sys.exit(1)

    variant = sys.argv[1].upper()

    prompt_file = os.path.join(BASE_DIR, "prompts", f"prompt_{variant}.txt")
    template    = load_prompt_template(prompt_file)
    print(f"Prompt template loaded from {prompt_file}.")

    all_instances = load_dataset()
    selected_languages, subset = select_subset(all_instances)
    sample_size = len(subset)
    total_candidate_slots = sample_size * PASS_K

    print(
        f"Total sampled bugs: {sample_size} "
        f"({NUM_LANGUAGES} languages, {int(SAMPLE_FRACTION * 100)}% per language, seed={SEED})."
    )
    print(f"Generating {PASS_K} candidates per bug: {total_candidate_slots} candidate slots.\n")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUTS_DIR / f"outputs_{variant}_pass5.jsonl"
    token_path  = OUTPUTS_DIR / f"tokens_{variant}_pass5.txt"

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
                request_hash = cached_result.get("request_hash")
                if task_id and request_hash and cached_result.get("fixed_source_code"):
                    cache_lookup[task_id] = cached_result
        print(f"Loaded {len(cache_lookup)} cached candidate results from {output_path}.\n")

    selected_by_sample_id = {make_sample_id(inst): inst for inst in subset}
    compatible_cache: Dict[str, Dict[str, Any]] = {}
    for task_id, cached in cache_lookup.items():
        sample_id = cached.get("sample_id")
        inst = selected_by_sample_id.get(sample_id)
        if inst and cached.get("request_hash") == make_request_hash(template, inst):
            compatible_cache[task_id] = cached

    print(
        f"Compatible cached candidates for the current prompt/input: "
        f"{len(compatible_cache)}.\n"
    )

    results_by_task_id: Dict[str, Dict[str, Any]] = dict(compatible_cache)
    cached_count = 0
    total_input_tok = 0
    total_output_tok = 0
    total_llm_time_seconds = 0.0

    for bug_index, inst in enumerate(subset, start=1):
        apr_id       = inst.get("apr_id", f"idx_{bug_index}")
        lang_cluster = inst.get("lang_cluster", "unknown")
        outcome      = inst.get("bug_exec_outcome", "unknown")
        sample_id    = make_sample_id(inst)
        request_hash = make_request_hash(template, inst)

        for candidate_id in range(1, PASS_K + 1):
            task_id = f"{sample_id}__candidate_{candidate_id}"
            print(
                f"[{bug_index}/{sample_size} cand {candidate_id}/{PASS_K}] "
                f"apr_id={apr_id}  lang={lang_cluster}  outcome={outcome}",
                end=" ... ",
                flush=True,
            )

            if task_id in compatible_cache:
                print("CACHED")
                results_by_task_id[task_id] = compatible_cache[task_id]
                cached_count += 1
                continue

            filled_prompt = build_prompt(template, inst)

            try:
                t_start = time.time()
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": filled_prompt}],
                )
                t_end = time.time()

                raw_output = response.content[0].text
                fixed_code = extract_code(raw_output, lang_cluster)
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                llm_time_seconds = round(t_end - t_start, 3)

                total_input_tok += input_tokens
                total_output_tok += output_tokens
                total_llm_time_seconds += llm_time_seconds
                print("OK")

            except Exception as e:
                print(f"ERROR: {e}")
                raw_output = ""
                fixed_code = ""
                input_tokens = 0
                output_tokens = 0
                llm_time_seconds = 0.0

            results_by_task_id[task_id] = {
                "task_id":            task_id,
                "sample_id":          sample_id,
                "request_hash":       request_hash,
                "apr_id":             apr_id,
                "candidate_id":       candidate_id,
                "pass_k":             PASS_K,
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
                "input_tokens":       input_tokens,
                "output_tokens":      output_tokens,
                "llm_time_seconds":   llm_time_seconds,
                "selected_languages": selected_languages,
            }

            # Save after each API call so an interrupted run can resume.
            with output_path.open("w", encoding="utf-8") as f:
                for row in results_by_task_id.values():
                    f.write(json.dumps(row) + "\n")

    with output_path.open("w", encoding="utf-8") as f:
        for r in results_by_task_id.values():
            f.write(json.dumps(r) + "\n")

    candidate_rows = len(results_by_task_id)
    new_llm_calls = total_candidate_slots - cached_count

    with token_path.open("w", encoding="utf-8") as f:
        f.write(f"Prompt             : {variant}\n")
        f.write(f"Metric target      : Pass@{PASS_K}\n")
        f.write(f"Selected languages : {', '.join(selected_languages)}\n")
        f.write(f"Bugs sampled       : {sample_size} ({int(SAMPLE_FRACTION * 100)}% per selected language, seed={SEED})\n")
        f.write(f"Candidates per bug : {PASS_K}\n")
        f.write(f"Candidate rows     : {candidate_rows}\n")
        f.write(f"Cached candidates  : {cached_count}\n")
        f.write(f"New LLM calls      : {new_llm_calls}\n")
        f.write(f"Total input tok    : {total_input_tok}\n")
        f.write(f"Total output tok   : {total_output_tok}\n")
        f.write(f"Total LLM time (s) : {round(total_llm_time_seconds, 3)}\n")

    print(f"\nDone. Candidate outputs saved to {output_path}")
    print(f"Tokens saved to            {token_path}")
    print(f"Selected languages         {selected_languages}")
    print(f"Bugs sampled               {sample_size}")
    print(f"Candidate rows             {candidate_rows}")
    print(f"From cache                 {cached_count}")
    print(f"New LLM calls              {new_llm_calls}")
    print(f"Total input tokens         {total_input_tok}")
    print(f"Total output tokens        {total_output_tok}")


if __name__ == "__main__":
    main()
