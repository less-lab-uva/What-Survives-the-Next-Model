#!/usr/bin/env python3
"""
Randomly samples log entries from a dataset and runs the log parsing pipeline
(Prompt A and Prompt B) until the budget is exhausted.

Usage:
    python3 run_random.py <budget_usd> <dataset_name>

Example:
    python3 run_random.py 5.0 Thunderbird
"""

import anthropic
import csv
import importlib.util
import json
import os
import random
import re
import sys
from datetime import datetime

INFERLOG_ROOT  = os.path.dirname(os.path.abspath(__file__))
DATASET_ROOT   = os.path.join(INFERLOG_ROOT, "benchmark", "dataset")
OUTPUT_FOLDER  = os.path.join(INFERLOG_ROOT, "output")
PROMPTS        = ["A", "B"]


# ── dataset ──────────────────────────────────────────────────────────────────

def load_dataset(dataset_name: str) -> list:
    """Return list of dicts with line_id and content (no ground truth)."""
    csv_path = os.path.join(
        DATASET_ROOT, dataset_name,
        f"{dataset_name}_2k.log_structured_corrected.csv",
    )
    if not os.path.exists(csv_path):
        print(f"[!] Dataset CSV not found: {csv_path}")
        sys.exit(1)
    entries = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entries.append({"line_id": row["LineId"], "content": row["Content"]})
    return entries


# ── output CSV ────────────────────────────────────────────────────────────────

def output_csv_path(prompt_letter: str, dataset_name: str) -> str:
    return os.path.join(OUTPUT_FOLDER, f"{dataset_name}_prompt{prompt_letter}.csv")


def load_completed(prompt_letter: str, dataset_name: str) -> set:
    """Return set of LineIds already written to the output CSV."""
    path = output_csv_path(prompt_letter, dataset_name)
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {row["LineId"] for row in csv.DictReader(f)}


def append_result(line_id: str, content: str, log_template: str,
                  prompt_letter: str, dataset_name: str) -> None:
    path = output_csv_path(prompt_letter, dataset_name)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["LineId", "Content", "log_template"])
        writer.writerow([line_id, content, log_template])


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
        if not all(e["line_id"] in completed[p] for p in PROMPTS)
    ]


# ── API call ──────────────────────────────────────────────────────────────────

def load_prompt(prompt_letter: str) -> str:
    prompt_file = os.path.join(INFERLOG_ROOT, f"prompt{prompt_letter}.py")
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

    # Send only the log message — ground truth (EventTemplate) is never included
    user_message = json.dumps({"log_message": entry["content"]}, indent=2)

    client = anthropic.Anthropic()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response_text = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=512,
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

    result = parse_json_response(response_text)
    log_template = result.get("log_template", "")

    if log_template:
        append_result(
            entry["line_id"], entry["content"], log_template,
            prompt_letter, dataset_name,
        )
        print(f"    [+] Saved to {output_csv_path(prompt_letter, dataset_name)}")
    else:
        raw_path = os.path.join(
            OUTPUT_FOLDER,
            f"raw_{dataset_name}_L{entry['line_id']}_prompt{prompt_letter}_{timestamp}.txt",
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    # Append to per-prompt token file
    token_file = os.path.join(OUTPUT_FOLDER, f"tokens_prompt{prompt_letter}.json")
    record = {
        "model": "claude-sonnet-4-6",
        "prompt": prompt_letter,
        "dataset": dataset_name,
        "line_id": entry["line_id"],
        "timestamp": timestamp,
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
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2]
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
        print(f"[*] Selected: LineId={entry['line_id']}  content={entry['content'][:70]!r}")

        for letter in PROMPTS:
            if entry["line_id"] in load_completed(letter, dataset_name):
                print(f"    prompt {letter}: already exists, skipping.")
                continue

            # Re-check budget before each API call
            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            print(f"    prompt {letter}: running ...")
            run_entry(entry, letter, dataset_name)


if __name__ == "__main__":
    main()
