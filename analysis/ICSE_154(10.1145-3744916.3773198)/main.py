#!/usr/bin/env python3
"""
LASIR single-call pipeline: detects signature replay vulnerabilities
in Solidity smart contracts using Claude claude-sonnet-4-6.

Budget loop: on resume, finishes any partial entry (one prompt done,
other not) before randomly picking a new untouched contract. Stops when
budget is exhausted or all contracts are fully processed.

Outputs (in outputs/):
  If serialised output is <= SIZE_THRESHOLD bytes:
    appended as a single JSONL line to outputs/outputs_A.jsonl (or _B.jsonl)
  Otherwise:
    saved as outputs/<safe_contract_id>_prompt<letter>.json

  Token / cost / duration logs:
    outputs/tokens_A.jsonl   — one JSON line per successful run
    outputs/tokens_B.jsonl

Usage:
    python3 main.py <budget_usd> [dataset]

Dataset names: RQ2 (default)

Example:
    python3 main.py 7.0 RQ2

Only 10% of the dataset (50 contracts) is used per run. The sampled
contract IDs are saved to outputs/sample_ids.json on the first run and
reused on every subsequent run, so results are reproducible.
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

# ---------------------------------------------------------------------------
# Paths — all relative to this file so the folder stays portable
# ---------------------------------------------------------------------------
BASE_DIR      = Path(__file__).parent
PROMPTS_DIR   = BASE_DIR / "prompts"
OUTPUT_DIR    = BASE_DIR / "outputs"
DATASET_DIR   = BASE_DIR / "Dataset"
CONTRACTS_DIR = DATASET_DIR / "contracts" / "Ethereum"

DATASET_CSVS = {
    "RQ2": DATASET_DIR / "RQ2" / "Labeled_Data.csv",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROMPTS          = ["A", "B"]
MODEL            = "claude-sonnet-4-6"
INPUT_PRICE      = 3.0    # USD per 1M input tokens
OUTPUT_PRICE     = 15.0   # USD per 1M output tokens
MAX_INPUT_TOKENS = 190_000
CHARS_PER_TOKEN  = 3.5
SIZE_THRESHOLD   = 50_000   # bytes: outputs larger than this get their own file
SAMPLE_FRACTION  = 0.1      # fraction of the dataset to evaluate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)


def parse_json_response(text: str) -> dict:
    """Extract the first valid JSON object from LLM response text."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r"\{", text))):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
def load_prompt(letter: str) -> str:
    path = PROMPTS_DIR / f"prompt{letter}.py"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    spec   = importlib.util.spec_from_file_location("prompt_module", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable in {path}")
    return module.prompt


# ---------------------------------------------------------------------------
# 10 % sampling — persisted so resume always uses the same contracts
# ---------------------------------------------------------------------------
SAMPLE_IDS_FILE = OUTPUT_DIR / "sample_ids.json"


def sample_entries(all_entries: list) -> list:
    """Return the 10% sample, creating and persisting it on first call."""
    sample_size = max(1, round(len(all_entries) * SAMPLE_FRACTION))

    if SAMPLE_IDS_FILE.exists():
        saved_ids = set(json.loads(SAMPLE_IDS_FILE.read_text(encoding="utf-8")))
        sampled = [e for e in all_entries if e["contract_id"] in saved_ids]
        if sampled:
            print(f"    Sample  : {len(sampled)} contracts loaded from {SAMPLE_IDS_FILE.name}")
            return sampled

    # First run — draw a stratified random sample (proportional pos/neg split)
    positives = [e for e in all_entries if e["label"] == "positive"]
    negatives = [e for e in all_entries if e["label"] == "negative"]
    n_pos = round(len(positives) * SAMPLE_FRACTION)
    n_neg = sample_size - n_pos
    sampled = random.sample(positives, min(n_pos, len(positives))) + \
              random.sample(negatives, min(n_neg, len(negatives)))
    random.shuffle(sampled)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_IDS_FILE.write_text(
        json.dumps([e["contract_id"] for e in sampled], indent=2), encoding="utf-8"
    )
    print(f"    Sample  : {len(sampled)} contracts drawn ({n_pos} positive, "
          f"{sample_size - n_pos} negative) — saved to {SAMPLE_IDS_FILE.name}")
    return sampled


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def load_dataset(dataset_name: str) -> list:
    csv_path = DATASET_CSVS.get(dataset_name.upper())
    if csv_path is None or not csv_path.exists():
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
            filename_on_disk = (filename_with_prefix[2:]
                                if filename_with_prefix.startswith("0x")
                                else filename_with_prefix)
            sol_path = CONTRACTS_DIR / filename_on_disk
            if not sol_path.exists():
                print(f"[!] Missing: {filename_on_disk} — skipping.")
                continue
            with open(sol_path, encoding="utf-8", errors="replace") as sf:
                source_code = sf.read()
            entries.append({
                "contract_id": filename_on_disk,
                "label":       label,
                "source_code": source_code,
            })

    if not entries:
        print(f"[!] No valid entries loaded for dataset '{dataset_name}'.")
        sys.exit(1)
    return entries


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def sep_output_path(letter: str, contract_id: str) -> Path:
    return OUTPUT_DIR / f"{safe_name(contract_id)}_prompt{letter}.json"


def jsonl_output_path(letter: str) -> Path:
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


def token_log_path(letter: str) -> Path:
    return OUTPUT_DIR / f"tokens_{letter}.jsonl"


def is_done(contract_id: str, letter: str) -> bool:
    """Return True if this (contract, prompt) pair already has a result."""
    if sep_output_path(letter, contract_id).exists():
        return True
    jpath = jsonl_output_path(letter)
    if not jpath.exists():
        return False
    try:
        for line in jpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("contract_id") == contract_id and not rec.get("skipped"):
                    return True
    except (json.JSONDecodeError, OSError):
        pass
    return False


def get_pending(entries: list) -> tuple:
    """Returns (partial, untouched).
    partial   — contracts where some but not all prompts are done.
    untouched — contracts where no prompt has been run.
    """
    partial, untouched = [], []
    for entry in entries:
        done = [p for p in PROMPTS if is_done(entry["contract_id"], p)]
        if done and len(done) < len(PROMPTS):
            partial.append(entry)
        elif not done:
            untouched.append(entry)
    return partial, untouched


def save_output(letter: str, contract_id: str, payload: dict):
    """Save to JSONL or separate file depending on serialised size."""
    json_str = json.dumps(payload, indent=2)
    if len(json_str.encode("utf-8")) > SIZE_THRESHOLD:
        path = sep_output_path(letter, contract_id)
        path.write_text(json_str, encoding="utf-8")
        print(f"    [+] Saved to {path.relative_to(BASE_DIR)}")
    else:
        jpath = jsonl_output_path(letter)
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        print(f"    [+] Appended to {jpath.relative_to(BASE_DIR)}")


def append_token_log(letter: str, record: dict):
    path = token_log_path(letter)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Spending tracker
# ---------------------------------------------------------------------------
def get_total_spent() -> float:
    total = 0.0
    for letter in PROMPTS:
        path = token_log_path(letter)
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    total += r.get("cost_usd", {}).get("total_cost", 0.0)
        except (json.JSONDecodeError, OSError):
            pass
    return round(total, 6)


# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------
def run_entry(entry: dict, letter: str, dataset_name: str,
              system_prompt: str, client: anthropic.Anthropic):
    contract_id = entry["contract_id"]
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")

    user_message = json.dumps(
        {"solidity_source_code": entry["source_code"]}, indent=2
    )

    # Token pre-flight check
    estimated = (len(system_prompt) + len(user_message)) / CHARS_PER_TOKEN
    if estimated > MAX_INPUT_TOKENS:
        print(f"    prompt {letter}: SKIPPED — estimated {int(estimated):,} tokens "
              f"> {MAX_INPUT_TOKENS:,} limit")
        payload = {
            "contract_id":      contract_id,
            "label":            entry["label"],
            "prompt":           letter,
            "dataset":          dataset_name,
            "timestamp":        timestamp,
            "skipped":          True,
            "reason":           "too_large",
            "estimated_tokens": int(estimated),
        }
        with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        return

    print(f"    prompt {letter}: calling {MODEL} for '{contract_id}' ...")
    t_start       = time.time()
    response_text = ""

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for chunk in stream.text_stream:
                response_text += chunk
                print(chunk, end="", flush=True)
            print()
            usage = stream.get_final_message().usage
    except anthropic.BadRequestError as e:
        if "prompt is too long" in str(e).lower():
            print(f"    prompt {letter}: SKIPPED — {e}")
            payload = {
                "contract_id": contract_id,
                "label":       entry["label"],
                "prompt":      letter,
                "dataset":     dataset_name,
                "timestamp":   timestamp,
                "skipped":     True,
                "reason":      "too_large",
            }
            with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
            return
        raise

    duration_seconds = round(time.time() - t_start, 3)

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost   = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    result    = parse_json_response(response_text)
    exist     = result.get("Exist")
    vuln_type = result.get("Vuln_type")

    if exist is not None and vuln_type is not None:
        payload = {
            "contract_id": contract_id,
            "label":       entry["label"],
            "prompt":      letter,
            "dataset":     dataset_name,
            "Exist":       bool(exist),
            "Vuln_type":   list(vuln_type),
        }
        save_output(letter, contract_id, payload)
    else:
        raw_path = (OUTPUT_DIR /
                    f"raw_{dataset_name}_{safe_name(contract_id)}_prompt{letter}_{timestamp}.txt")
        raw_path.write_text(response_text, encoding="utf-8")
        payload = {
            "contract_id":  contract_id,
            "label":        entry["label"],
            "prompt":       letter,
            "dataset":      dataset_name,
            "timestamp":    timestamp,
            "parse_failed": True,
            "raw_file":     raw_path.name,
        }
        with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        print(f"    [!] JSON parse failed. Raw saved: {raw_path.relative_to(BASE_DIR)}")

    append_token_log(letter, {
        "model":            MODEL,
        "prompt":           letter,
        "dataset":          dataset_name,
        "contract_id":      contract_id,
        "label":            entry["label"],
        "timestamp":        timestamp,
        "duration_seconds": duration_seconds,
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
    })
    print(f"    tokens: in={input_tokens} out={output_tokens}  "
          f"cost=${total_cost:.6f}  time={duration_seconds}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd> [dataset]")
        print("  dataset: RQ2 (default)")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2].upper() if len(sys.argv) > 2 else "RQ2"

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load prompts ---
    prompts = {}
    for letter in PROMPTS:
        try:
            prompts[letter] = load_prompt(letter)
        except FileNotFoundError as e:
            print(f"[!] {e}")
            sys.exit(1)

    client = anthropic.Anthropic()

    # --- Preprocessing ---
    print("[*] Preprocessing ...")
    all_entries = load_dataset(dataset_name)
    pos_all = sum(1 for e in all_entries if e["label"] == "positive")
    print(f"    Dataset : {dataset_name}  ({len(all_entries)} contracts — "
          f"{pos_all} positive, {len(all_entries) - pos_all} negative)")
    entries = sample_entries(all_entries)
    pos = sum(1 for e in entries if e["label"] == "positive")
    neg = len(entries) - pos
    print(f"    Running on {len(entries)} contracts ({pos} positive, {neg} negative)")

    partial, untouched = get_pending(entries)
    done_count = len(entries) - len(partial) - len(untouched)
    print(f"    Status  : {done_count} fully done, {len(partial)} partial, "
          f"{len(untouched)} untouched")
    print(f"\n[*] Budget: ${budget:.4f}")

    # --- Budget loop ---
    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(entries)

        if not partial and not untouched:
            print("[*] All contracts processed. Stopping.")
            break

        if partial:
            entry = random.choice(partial)
            print(f"[*] Completing partial: {entry['contract_id']} "
                  f"(label={entry['label']})")
        else:
            entry = random.choice(untouched)
            print(f"[*] Selected new: {entry['contract_id']} "
                  f"(label={entry['label']})")

        for letter in PROMPTS:
            if is_done(entry["contract_id"], letter):
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_entry(entry, letter, dataset_name, prompts[letter], client)

    # --- Summary ---
    final_spent = get_total_spent()
    partial, untouched = get_pending(entries)
    done_count = len(entries) - len(partial) - len(untouched)
    print(f"\n[*] Run complete.")
    print(f"    Total spent          : ${final_spent:.4f}")
    print(f"    Contracts fully done : {done_count} / {len(entries)} sampled "
          f"(10% of {len(all_entries)} total)")


if __name__ == "__main__":
    main()
