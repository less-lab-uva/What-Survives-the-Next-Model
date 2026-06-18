#!/usr/bin/env python3
"""
Single-call LLM log parsing pipeline.
Usage: python3 main.py <budget_usd> [dataset_name]
"""

import csv
import importlib.util
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic

BASE_DIR     = Path(__file__).parent
DATA_DIR     = BASE_DIR / "data"
PROMPTS_DIR  = BASE_DIR / "prompts"
OUTPUT_DIR   = BASE_DIR / "outputs"

MODEL        = "claude-sonnet-4-6"
INPUT_PRICE  = 3.0    # USD per 1M input tokens
OUTPUT_PRICE = 15.0   # USD per 1M output tokens
CONTEXT_LIMIT = 190_000  # safe threshold below Sonnet 4.6's 200K context window
PROMPTS      = ["A", "B"]


# ── template normalisation (ported from original pipeline's postprocess.py) ──

def correct_single_template(template, user_strings=None):
    boolean         = {'true', 'false'}
    default_strings = {'null', 'root', 'admin'}
    path_delimiters = {
        r'\s', r'\,', r'\!', r'\;', r'\:',
        r'\=', r'\|', r'\"', r'\'',
        r'\[', r'\]', r'\(', r'\)', r'\{', r'\}',
    }
    token_delimiters = path_delimiters.union({
        r'\.', r'\-', r'\+', r'\@', r'\#', r'\$', r'\%', r'\&',
    })
    if user_strings:
        default_strings = default_strings.union(user_strings)

    # DS: normalise whitespace
    template = template.strip()
    template = re.sub(r'\s+', ' ', template)

    # PS: collapse path-like tokens
    p_tokens = re.split('(' + '|'.join(path_delimiters) + ')', template)
    new_p_tokens = []
    for p_token in p_tokens:
        if re.match(r'^(\/[^\/]+)+$', p_token) or all(x in p_token for x in {'<*>', '.', '/'}):
            p_token = '<*>'
        new_p_tokens.append(p_token)
    template = ''.join(new_p_tokens)

    # BL, US, DG, WV
    tokens = re.split('(' + '|'.join(token_delimiters) + ')', template)
    new_tokens = []
    for token in tokens:
        for to_replace in boolean.union(default_strings):
            if token.lower() == to_replace.lower():
                token = '<*>'
        if re.match(r'^\d+$', token) or re.match(r'\b0[xX][0-9a-fA-F]+\b', token):
            token = '<*>'
        if re.match(r'^[^\s\/]*<\*>[^\s\/]*$', token):
            token = '<*>'
        new_tokens.append(token)
    template = ''.join(new_tokens)

    for token in template.split(' '):
        if all(x in token for x in {'<*>', '.', ':'}):
            template = template.replace(token, '<*>')

    # DV: merge dot-separated variables
    while True:
        prev = template
        template = re.sub(r'<\*>\.<\*>', '<*>', template)
        if prev == template:
            break

    # CV: merge consecutive variables
    while True:
        prev = template
        template = re.sub(r'<\*><\*>', '<*>', template)
        if prev == template:
            break

    while '<*>:<*>' in template:
        template = template.replace('<*>:<*>', '<*>')
    while '<*>/<*>' in template:
        template = template.replace('<*>/<*>', '<*>')

    return template


# ── dataset ───────────────────────────────────────────────────────────────────

def load_dataset(dataset_name):
    path = DATA_DIR / f"{dataset_name}_2k.log_structured_corrected.csv"
    if not path.exists():
        print(f"[!] Dataset CSV not found: {path}")
        sys.exit(1)
    entries = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entries.append({"line_id": row["LineId"], "content": row["Content"]})
    return entries


def use_per_dataset_files(entries):
    """Use per-dataset output files when individual log messages can be very long."""
    return max(len(e["content"]) for e in entries) > 2000


# ── output paths ──────────────────────────────────────────────────────────────

def output_path(letter, dataset_name, per_dataset):
    if per_dataset:
        return OUTPUT_DIR / f"{dataset_name}_outputs_{letter}.jsonl"
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


def tokens_path(letter):
    return OUTPUT_DIR / f"tokens_{letter}.jsonl"


# ── resume helpers ────────────────────────────────────────────────────────────

def get_completed(letter, dataset_name, per_dataset):
    """Return set of LineIds already saved for this dataset + prompt letter."""
    path = output_path(letter, dataset_name, per_dataset)
    if not path.exists():
        return set()
    completed = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("dataset") == dataset_name:
                completed.add(str(entry["line_id"]))
        except (json.JSONDecodeError, KeyError):
            pass
    return completed


def get_total_spent():
    """Sum total_cost from all token JSONL files (all datasets, all prompts)."""
    total = 0.0
    for letter in PROMPTS:
        path = tokens_path(letter)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                total += json.loads(line).get("cost_usd", {}).get("total_cost", 0.0)
            except (json.JSONDecodeError, KeyError):
                pass
    return round(total, 6)


# ── prompt loading ─────────────────────────────────────────────────────────────

def load_prompt(letter):
    path = PROMPTS_DIR / f"prompt{letter}.py"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}\n"
                                f"Generate it by running the metaprompt against the paper.")
    spec   = importlib.util.spec_from_file_location("prompt_module", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable found in {path}")
    return module.prompt


# ── API helpers ───────────────────────────────────────────────────────────────

def parse_json_response(text):
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped.strip(), flags=re.MULTILINE)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def estimate_tokens(system_prompt, user_msg):
    return int((len(system_prompt) + len(user_msg)) / 3.5)


# ── single entry run ──────────────────────────────────────────────────────────

def run_entry(entry, letter, system_prompt, client, dataset_name, per_dataset):
    user_msg = json.dumps({"log_message": entry["content"]}, indent=2)

    est = estimate_tokens(system_prompt, user_msg)
    if est > CONTEXT_LIMIT:
        print(f"    [{letter}] SKIP LineId={entry['line_id']}: ~{est} estimated tokens "
              f"exceeds {CONTEXT_LIMIT}")
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    t_start   = time.time()
    response_text = ""

    with client.messages.stream(
        model=MODEL,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for chunk in stream.text_stream:
            response_text += chunk
            print(chunk, end="", flush=True)
        print()
        usage = stream.get_final_message().usage

    duration  = round(time.time() - t_start, 3)
    in_tok    = usage.input_tokens
    out_tok   = usage.output_tokens
    in_cost   = round(in_tok  * INPUT_PRICE  / 1_000_000, 6)
    out_cost  = round(out_tok * OUTPUT_PRICE / 1_000_000, 6)
    total     = round(in_cost + out_cost, 6)

    result       = parse_json_response(response_text)
    log_template = result.get("log_template", "")
    if log_template:
        log_template = correct_single_template(log_template)

    out_entry = {
        "line_id":      entry["line_id"],
        "content":      entry["content"],
        "log_template": log_template,
        "dataset":      dataset_name,
        "timestamp":    timestamp,
    }
    if not log_template:
        out_entry["parse_failed"] = True
        out_entry["raw_response"] = response_text[:500]

    with open(output_path(letter, dataset_name, per_dataset), "a", encoding="utf-8") as f:
        f.write(json.dumps(out_entry) + "\n")

    tok_entry = {
        "model":            MODEL,
        "prompt":           letter,
        "dataset":          dataset_name,
        "line_id":          entry["line_id"],
        "timestamp":        timestamp,
        "duration_seconds": duration,
        "tokens": {
            "input_tokens":  in_tok,
            "output_tokens": out_tok,
            "total_tokens":  in_tok + out_tok,
        },
        "cost_usd": {
            "input_cost":  in_cost,
            "output_cost": out_cost,
            "total_cost":  total,
        },
    }
    with open(tokens_path(letter), "a", encoding="utf-8") as f:
        f.write(json.dumps(tok_entry) + "\n")

    print(f"    [{letter}] in={in_tok} out={out_tok} cost=${total:.6f} time={duration}s")
    return True


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd> [dataset_name]")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2] if len(sys.argv) > 2 else "HPC"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    print(f"[*] Dataset:  {dataset_name}")
    print(f"[*] Model:    {MODEL}")
    print(f"[*] Budget:   ${budget:.4f}")

    entries     = load_dataset(dataset_name)
    per_dataset = use_per_dataset_files(entries)
    entry_map   = {e["line_id"]: e for e in entries}
    print(f"[*] Entries:  {len(entries)}")
    print(f"[*] Output:   {'per-dataset files' if per_dataset else 'aggregate file'}")

    prompts = {letter: load_prompt(letter) for letter in PROMPTS}
    client  = anthropic.Anthropic()

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.6f}  remaining=${remaining:.6f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        completed = {p: get_completed(p, dataset_name, per_dataset) for p in PROMPTS}

        # Partial entries (at least one prompt done, but not all) come first
        partial   = [lid for lid in entry_map
                     if any(lid in completed[p] for p in PROMPTS)
                     and not all(lid in completed[p] for p in PROMPTS)]
        untouched = [lid for lid in entry_map
                     if not any(lid in completed[p] for p in PROMPTS)]

        if not partial and not untouched:
            print("[*] All entries processed. Stopping.")
            break

        if partial:
            line_id = random.choice(partial)
            print(f"[*] Completing partial entry LineId={line_id}")
        else:
            line_id = random.choice(untouched)
            content_preview = entry_map[line_id]["content"][:60]
            print(f"[*] New entry LineId={line_id}  content={content_preview!r}")

        entry = entry_map[line_id]

        for letter in PROMPTS:
            if line_id in completed[letter]:
                print(f"    [{letter}] already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            print(f"    [{letter}] running ...")
            run_entry(entry, letter, prompts[letter], client, dataset_name, per_dataset)


if __name__ == "__main__":
    main()
