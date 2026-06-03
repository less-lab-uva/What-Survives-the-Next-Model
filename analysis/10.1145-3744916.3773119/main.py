#!/usr/bin/env python3
"""
Randomly samples entries from a benchmark dataset and runs the code approximation
pipeline (Prompt A and Prompt B) until the budget is exhausted.

Usage:
    python3 run_random.py <budget_usd> <dataset_name>

Dataset names: stattype, coster

Example:
    python3 run_random.py 5.0 stattype
"""

import anthropic
import importlib.util
import json
import os
import random
import re
import sys
from datetime import datetime

PREPA_ROOT    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER = os.path.join(PREPA_ROOT, "output")
PROMPTS       = ["A", "B"]

DATASET_FILES = {
    "stattype": os.path.join(PREPA_ROOT, "Stattype_res.json"),
    "coster":   os.path.join(PREPA_ROOT, "Coster_res.json"),
}


# ── dataset ───────────────────────────────────────────────────────────────────

def load_dataset(dataset_name: str) -> list:
    """Return list of entry dicts with entry_name, variant, partial_code, ground_truth."""
    path = DATASET_FILES.get(dataset_name)
    if not path or not os.path.exists(path):
        print(f"[!] Dataset not found for '{dataset_name}'. Expected: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = []
    for entry_name, entry_data in data.items():
        ground_truth = entry_data.get("ground_truth", {})
        for variant, variant_data in entry_data.items():
            if variant == "ground_truth":
                continue
            entries.append({
                "entry_name":   entry_name,
                "variant":      variant,
                "partial_code": variant_data.get("partial_code", ""),
                "ground_truth": ground_truth,
            })
    return entries


# ── output JSON ───────────────────────────────────────────────────────────────

def output_json_path(prompt_letter: str, dataset_name: str) -> str:
    return os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{prompt_letter}.json")


def load_output(prompt_letter: str, dataset_name: str) -> dict:
    path = output_json_path(prompt_letter, dataset_name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_completed(prompt_letter: str, dataset_name: str) -> set:
    """Return set of (entry_name, variant) tuples already processed."""
    data = load_output(prompt_letter, dataset_name)
    completed = set()
    for entry_name, entry_data in data.items():
        for variant, variant_data in entry_data.items():
            if variant == "ground_truth":
                continue
            if isinstance(variant_data, dict) and "approximated_code" in variant_data:
                completed.add((entry_name, variant))
    return completed


def save_result(entry: dict, approximated_code: str, type_information: list,
                prompt_letter: str, dataset_name: str) -> None:
    data = load_output(prompt_letter, dataset_name)
    entry_name = entry["entry_name"]
    variant    = entry["variant"]
    if entry_name not in data:
        data[entry_name] = {"ground_truth": entry["ground_truth"]}
    if variant not in data[entry_name]:
        data[entry_name][variant] = {}
    data[entry_name][variant]["partial_code"]      = entry["partial_code"]
    data[entry_name][variant]["approximated_code"] = approximated_code
    data[entry_name][variant]["type_information"]  = type_information
    data[entry_name][variant]["code_res"]          = None
    with open(output_json_path(prompt_letter, dataset_name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── budget ────────────────────────────────────────────────────────────────────

def get_total_spent() -> float:
    """Sum total_cost from all tokens_prompt*.json files in the output folder."""
    total = 0.0
    if not os.path.exists(OUTPUT_FOLDER):
        return total
    for fname in os.listdir(OUTPUT_FOLDER):
        if fname.startswith("tokens_prompt") and fname.endswith(".json"):
            fpath = os.path.join(OUTPUT_FOLDER, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    records = json.load(f)
                if isinstance(records, list):
                    total += sum(
                        r.get("cost_usd", {}).get("total_cost", 0.0) for r in records
                    )
            except (json.JSONDecodeError, KeyError):
                pass
    return round(total, 6)


# ── pending entries ───────────────────────────────────────────────────────────

def get_pending(entries: list, dataset_name: str) -> list:
    """Entries where at least one prompt result is still missing."""
    completed = {p: load_completed(p, dataset_name) for p in PROMPTS}
    return [
        e for e in entries
        if not all((e["entry_name"], e["variant"]) in completed[p] for p in PROMPTS)
    ]


# ── API call ──────────────────────────────────────────────────────────────────

def load_prompt(prompt_letter: str) -> str:
    prompt_file = os.path.join(PREPA_ROOT, f"prompt{prompt_letter}.py")
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    spec = importlib.util.spec_from_file_location("prompt_module", prompt_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable in {prompt_file}")
    return module.prompt


def parse_json_response(response_text: str) -> dict:
    stripped = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped.strip(), flags=re.MULTILINE)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def run_entry(entry: dict, prompt_letter: str, dataset_name: str) -> None:
    system_prompt = load_prompt(prompt_letter)
    user_message  = json.dumps({"partial_code": entry["partial_code"]}, indent=2)

    client    = anthropic.Anthropic()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response_text = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for chunk in stream.text_stream:
            response_text += chunk
            print(chunk, end="", flush=True)
        print()
        usage = stream.get_final_message().usage

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * 3  / 1_000_000, 6)
    output_cost   = round(output_tokens * 15 / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    result            = parse_json_response(response_text)
    approximated_code = result.get("approximated_code", "")
    type_information  = result.get("type_information", [])

    if approximated_code:
        save_result(entry, approximated_code, type_information, prompt_letter, dataset_name)
        print(f"    [+] Saved to {output_json_path(prompt_letter, dataset_name)}")
    else:
        raw_path = os.path.join(
            OUTPUT_FOLDER,
            f"raw_{dataset_name}_{entry['entry_name']}_{entry['variant']}_prompt{prompt_letter}_{timestamp}.txt",
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    token_file = os.path.join(OUTPUT_FOLDER, f"tokens_prompt{prompt_letter}.json")
    record = {
        "model":      "claude-sonnet-4-6",
        "prompt":     prompt_letter,
        "dataset":    dataset_name,
        "entry_name": entry["entry_name"],
        "variant":    entry["variant"],
        "timestamp":  timestamp,
        "tokens": {
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "total_tokens":  input_tokens + output_tokens,
        },
        "cost_usd": {
            "input_cost":  input_cost,
            "output_cost": output_cost,
            "total_cost":  total_cost,
        },
    }
    if os.path.exists(token_file):
        with open(token_file, encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(record)
        records = existing
    else:
        records = [record]
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(f"    tokens: in={input_tokens} out={output_tokens}  cost=${total_cost}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 run_random.py <budget_usd> <dataset_name>")
        print("Dataset names: stattype, coster")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2].lower()
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    entries = load_dataset(dataset_name)
    print(f"[*] Dataset: {dataset_name}  ({len(entries)} entries)")
    print(f"[*] Budget: ${budget:.4f}")

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        pool = get_pending(entries, dataset_name)
        if not pool:
            print("[*] All entries processed. Stopping.")
            break

        entry = random.choice(pool)
        print(f"[*] Selected: {entry['entry_name']}/{entry['variant']}  "
              f"partial_code={entry['partial_code'][:70]!r}")

        for letter in PROMPTS:
            if (entry["entry_name"], entry["variant"]) in load_completed(letter, dataset_name):
                print(f"    prompt {letter}: already exists, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            print(f"    prompt {letter}: running ...")
            run_entry(entry, letter, dataset_name)


if __name__ == "__main__":
    main()
