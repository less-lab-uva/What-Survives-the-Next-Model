#!/usr/bin/env python3
"""
Randomly samples contracts from a labeled dataset and runs signature replay
vulnerability detection (Prompt A and Prompt B) until the budget is exhausted.

Usage:
    python3 run_random.py <dataset_name> <budget_usd>

Dataset names: RQ2

Example:
    python3 run_random.py RQ2 5.0
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

LASIR_ROOT      = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER   = os.path.join(LASIR_ROOT, "output")
CONTRACTS_DIR   = os.path.join(LASIR_ROOT, "Dataset", "contracts", "Ethereum")
PROMPTS         = ["A", "B"]

DATASET_FILES = {
    "RQ2": os.path.join(LASIR_ROOT, "Dataset", "RQ2", "Labeled_Data.csv"),
}


# ── dataset ───────────────────────────────────────────────────────────────────

def load_dataset(dataset_name: str) -> list:
    """Return list of entry dicts: contract_id, label, solidity_source_code."""
    csv_path = DATASET_FILES.get(dataset_name)
    if not csv_path or not os.path.exists(csv_path):
        print(f"[!] Dataset not found for '{dataset_name}'. Expected: {csv_path}")
        sys.exit(1)

    entries = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            label, filename_with_prefix = row[0].strip(), row[1].strip()
            if label not in ("positive", "negative"):
                continue
            # Files on disk have the 0x prefix stripped
            filename_on_disk = filename_with_prefix[2:] if filename_with_prefix.startswith("0x") else filename_with_prefix
            sol_path = os.path.join(CONTRACTS_DIR, filename_on_disk)
            if not os.path.exists(sol_path):
                print(f"[!] Missing contract file: {sol_path} — skipping.")
                continue
            with open(sol_path, encoding="utf-8", errors="replace") as sf:
                source_code = sf.read()
            entries.append({
                "contract_id":            filename_on_disk,
                "label":                  label,
                "solidity_source_code":   source_code,
            })
    if not entries:
        print(f"[!] No valid entries loaded for dataset '{dataset_name}'.")
        sys.exit(1)
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
    """Return set of contract_ids already processed for this prompt."""
    data = load_output(prompt_letter, dataset_name)
    return {
        cid for cid, v in data.items()
        if isinstance(v, dict) and "Exist" in v
    }


def save_result(entry: dict, exist: bool, vuln_type: list,
                prompt_letter: str, dataset_name: str) -> None:
    data = load_output(prompt_letter, dataset_name)
    cid  = entry["contract_id"]
    data[cid] = {
        "label":      entry["label"],
        "Exist":      exist,
        "Vuln_type":  vuln_type,
    }
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
        if not all(e["contract_id"] in completed[p] for p in PROMPTS)
    ]


# ── API call ──────────────────────────────────────────────────────────────────

def load_prompt(prompt_letter: str) -> str:
    prompt_file = os.path.join(LASIR_ROOT, f"prompt{prompt_letter}.py")
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    spec   = importlib.util.spec_from_file_location("prompt_module", prompt_file)
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
    user_message  = json.dumps(
        {"solidity_source_code": entry["solidity_source_code"]}, indent=2
    )

    client    = anthropic.Anthropic()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response_text = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for chunk in stream.text_stream:
            response_text += chunk
            print(chunk, end="", flush=True)
        print()
        final_msg = stream.get_final_message()
        usage     = final_msg.usage

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    # Explicitly use only billed tokens — cache read/write tokens are excluded
    # to avoid underestimating cost (cached tokens have a different, lower rate
    # but we treat every token at the standard rate for a conservative budget).
    input_cost  = round(input_tokens  * 3  / 1_000_000, 6)
    output_cost = round(output_tokens * 15 / 1_000_000, 6)
    total_cost  = round(input_cost + output_cost, 6)

    result     = parse_json_response(response_text)
    exist      = result.get("Exist", None)
    vuln_type  = result.get("Vuln_type", None)

    if exist is not None and vuln_type is not None:
        save_result(entry, bool(exist), list(vuln_type), prompt_letter, dataset_name)
        print(f"    [+] Saved → {output_json_path(prompt_letter, dataset_name)}")
        print(f"    [+] Exist={exist}  Vuln_type={vuln_type}")
    else:
        raw_path = os.path.join(
            OUTPUT_FOLDER,
            f"raw_{dataset_name}_{entry['contract_id']}_prompt{prompt_letter}_{timestamp}.txt",
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw response saved: {raw_path}")

    # ── token record ──────────────────────────────────────────────────────────
    token_file = os.path.join(OUTPUT_FOLDER, f"tokens_prompt{prompt_letter}.json")
    record = {
        "model":       "claude-sonnet-4-6",
        "prompt":      prompt_letter,
        "dataset":     dataset_name,
        "contract_id": entry["contract_id"],
        "label":       entry["label"],
        "timestamp":   timestamp,
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

    print(f"    tokens : in={input_tokens}  out={output_tokens}  "
          f"cost=${total_cost:.6f}  (in=${input_cost:.6f}  out=${output_cost:.6f})")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 run_random.py <dataset_name> <budget_usd>")
        print("Dataset names: RQ2")
        sys.exit(1)

    dataset_name = sys.argv[1]
    budget       = float(sys.argv[2])
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    entries = load_dataset(dataset_name)
    pos     = sum(1 for e in entries if e["label"] == "positive")
    neg     = len(entries) - pos
    print(f"[*] Dataset : {dataset_name}  ({len(entries)} contracts — {pos} positive, {neg} negative)")
    print(f"[*] Budget  : ${budget:.4f}")

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.6f}  remaining=${remaining:.6f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        pool = get_pending(entries, dataset_name)
        if not pool:
            print("[*] All entries processed for both prompts. Stopping.")
            break

        entry = random.choice(pool)
        print(f"[*] Selected : {entry['contract_id']}  label={entry['label']}  "
              f"source_len={len(entry['solidity_source_code'])} chars")

        for letter in PROMPTS:
            completed = load_completed(letter, dataset_name)
            if entry["contract_id"] in completed:
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted mid-entry. Stopping.")
                return

            print(f"    prompt {letter}: running ...")
            run_entry(entry, letter, dataset_name)


if __name__ == "__main__":
    main()
