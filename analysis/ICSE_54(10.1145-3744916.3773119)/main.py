#!/usr/bin/env python3
"""
Single-call LLM pipeline for partial Java program approximation.

Usage:
    python3 main.py <budget_usd> [dataset_name]

Dataset names: stattype  (default: stattype)

Preprocessing (runs at startup):
  Loads dataset/Stattype_res.json, extracts all entries that have a valid
  ground_truth_res (the set the paper evaluated on). These are the only entries
  eligible for selection.

Budget loop:
  - On resume: finishes any partial entry (one prompt done, the other not)
    before randomly picking a new untouched entry.
  - Checks combined token cost of both prompts before starting any new entry.
  - Stops when budget is exhausted or all eligible entries are fully done.

Outputs (in outputs/):
  outputs_A.jsonl       — one JSON line per entry processed with Prompt A
  outputs_B.jsonl       — one JSON line per entry processed with Prompt B
  tokens_A.jsonl        — cost + token + duration log per API call (Prompt A)
  tokens_B.jsonl        — same for Prompt B
  (if any partial_code exceeds 2000 chars, per-entry files are used instead:
   {entry_name}_{variant}_A.jsonl and {entry_name}_{variant}_B.jsonl)
"""

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
# Paths — all relative to this file
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
PROMPTS_DIR  = BASE_DIR / "prompts"
OUTPUT_DIR   = BASE_DIR / "outputs"
DATASET_DIR  = BASE_DIR / "dataset"

DATASET_FILES = {
    "stattype": DATASET_DIR / "Stattype_res.json",
}

MODEL        = "claude-sonnet-4-6"
INPUT_PRICE  = 3.0    # USD per 1M input tokens
OUTPUT_PRICE = 15.0   # USD per 1M output tokens
CONTEXT_LIMIT = 190_000  # safe threshold below Sonnet 4.6's 200K context window
MAX_TOKENS   = 4096
PROMPTS      = ["A", "B"]


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
        raise AttributeError(f"No 'prompt' variable found in {path}")
    return module.prompt


# ---------------------------------------------------------------------------
# Dataset / preprocessing
# ---------------------------------------------------------------------------
def load_dataset(dataset_name: str) -> list:
    """
    Load and preprocess the dataset.

    Extracts all (entry_name, variant) pairs that have a valid ground_truth_res
    — the same set the paper evaluated on. Entries with a missing or failure-
    string ground_truth_res are excluded, matching the paper's evaluation scope.

    Returns a list of dicts: {entry_name, variant, partial_code, dataset}.
    """
    path = DATASET_FILES.get(dataset_name)
    if path is None or not path.exists():
        print(f"[!] Dataset not found for '{dataset_name}'. Expected: {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entries = []
    excluded = 0
    for entry_name, entry_data in data.items():
        gt = entry_data.get("ground_truth", {})
        gt_res = gt.get("ground_truth_res")
        if not gt_res or isinstance(gt_res, str):
            excluded += 1
            continue
        for variant, variant_data in entry_data.items():
            if variant == "ground_truth" or not isinstance(variant_data, dict):
                continue
            pc = variant_data.get("partial_code", "")
            if not pc:
                excluded += 1
                continue
            entries.append({
                "entry_name":   entry_name,
                "variant":      variant,
                "partial_code": pc,
                "dataset":      dataset_name,
            })

    print(f"[*] Preprocessed {dataset_name}: {len(entries)} eligible entries "
          f"({excluded} excluded — no valid ground truth)")
    return entries


def use_per_entry_files(entries: list) -> bool:
    """Use per-entry output files if any partial_code exceeds 10000 chars.
    Java code snippets are larger than log messages; 10000 chars is the
    threshold above which aggregate JSONL entries become unwieldy."""
    return max((len(e["partial_code"]) for e in entries), default=0) > 10_000


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
def outputs_path(letter: str, entry_name: str, variant: str, per_entry: bool) -> Path:
    if per_entry:
        return OUTPUT_DIR / f"{entry_name}_{variant}_{letter}.jsonl"
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


def token_log_path(letter: str) -> Path:
    return OUTPUT_DIR / f"tokens_{letter}.jsonl"


# ---------------------------------------------------------------------------
# Completion tracking
# ---------------------------------------------------------------------------
def get_completed(letter: str, per_entry: bool, all_entries: list) -> set:
    """Return set of (entry_name, variant) already recorded for this prompt."""
    completed = set()
    if per_entry:
        for e in all_entries:
            path = outputs_path(letter, e["entry_name"], e["variant"], True)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            if "entry_name" in rec and "variant" in rec:
                                completed.add((rec["entry_name"], rec["variant"]))
                        except json.JSONDecodeError:
                            pass
    else:
        path = OUTPUT_DIR / f"outputs_{letter}.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        if "entry_name" in rec and "variant" in rec:
                            completed.add((rec["entry_name"], rec["variant"]))
                    except json.JSONDecodeError:
                        pass
    return completed


def get_pending(entries: list, per_entry: bool) -> tuple:
    """
    Returns (partial, untouched).
    partial   — entries where some but not all prompts are done.
    untouched — entries where no prompt has been run yet.
    Always drain partial before picking from untouched.
    """
    completed = {p: get_completed(p, per_entry, entries) for p in PROMPTS}
    partial, untouched = [], []
    for e in entries:
        key = (e["entry_name"], e["variant"])
        done = [p for p in PROMPTS if key in completed[p]]
        if done and len(done) < len(PROMPTS):
            partial.append(e)
        elif not done:
            untouched.append(e)
    return partial, untouched


# ---------------------------------------------------------------------------
# Spending tracker — reads only tokens_*.jsonl
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
                    total += json.loads(line).get("cost_usd", {}).get("total_cost", 0.0)
        except (json.JSONDecodeError, OSError):
            pass
    return round(total, 6)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def parse_response(text: str) -> dict:
    # 1. Prefer explicit ```json ... ``` fence
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. Scan all { positions right-to-left
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
# Single prompt run
# ---------------------------------------------------------------------------
def run_entry(entry: dict, letter: str, system_prompt: str,
              client: anthropic.Anthropic, per_entry: bool) -> None:
    user_msg  = json.dumps({"partial_code": entry["partial_code"]}, indent=2)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Token pre-flight: estimate and reject if over context limit
    estimated_tokens = (len(system_prompt) + len(user_msg)) / 3.5
    if estimated_tokens > CONTEXT_LIMIT:
        print(f"    [{letter}] SKIP {entry['entry_name']}/{entry['variant']}: "
              f"~{int(estimated_tokens):,} tokens exceeds {CONTEXT_LIMIT:,} limit")
        out = {
            "entry_name":       entry["entry_name"],
            "variant":          entry["variant"],
            "dataset":          entry["dataset"],
            "partial_code":     entry["partial_code"],
            "approximated_code": None,
            "type_information": [],
            "timestamp":        timestamp,
            "parse_failed":     True,
            "skip_reason":      "too_large",
        }
        with open(outputs_path(letter, entry["entry_name"], entry["variant"], per_entry),
                  "a", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")
        return

    print(f"    [{letter}] running {entry['entry_name']}/{entry['variant']} ...")
    t_start       = time.time()
    response_text = ""

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                response_text += chunk
                print(chunk, end="", flush=True)
            print()
            usage = stream.get_final_message().usage
    except anthropic.BadRequestError as exc:
        if "prompt is too long" in str(exc).lower():
            print(f"    [{letter}] SKIP — prompt too long: {exc}")
            out = {
                "entry_name":       entry["entry_name"],
                "variant":          entry["variant"],
                "dataset":          entry["dataset"],
                "partial_code":     entry["partial_code"],
                "approximated_code": None,
                "type_information": [],
                "timestamp":        timestamp,
                "parse_failed":     True,
                "skip_reason":      "too_large",
            }
            with open(outputs_path(letter, entry["entry_name"], entry["variant"], per_entry),
                      "a", encoding="utf-8") as f:
                f.write(json.dumps(out) + "\n")
            return
        raise

    duration_seconds = round(time.time() - t_start, 3)
    input_tokens     = usage.input_tokens
    output_tokens    = usage.output_tokens
    input_cost       = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost      = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost       = round(input_cost + output_cost, 6)

    result            = parse_response(response_text)
    approximated_code = result.get("approximated_code")
    type_information  = result.get("type_information", [])
    parse_failed      = not bool(approximated_code)

    out = {
        "entry_name":        entry["entry_name"],
        "variant":           entry["variant"],
        "dataset":           entry["dataset"],
        "partial_code":      entry["partial_code"],
        "approximated_code": approximated_code,
        "type_information":  type_information,
        "timestamp":         timestamp,
        "parse_failed":      parse_failed,
    }
    if parse_failed:
        # save truncated raw for debugging
        out["raw_response"] = response_text[:500]
        print(f"    [{letter}] WARNING — JSON parse failed for "
              f"{entry['entry_name']}/{entry['variant']}")
    else:
        print(f"    [{letter}] OK — {entry['entry_name']}/{entry['variant']}")

    with open(outputs_path(letter, entry["entry_name"], entry["variant"], per_entry),
              "a", encoding="utf-8") as f:
        f.write(json.dumps(out) + "\n")

    # Token log (JSONL, one line per API call)
    tok = {
        "model":            MODEL,
        "prompt":           letter,
        "entry_name":       entry["entry_name"],
        "variant":          entry["variant"],
        "dataset":          entry["dataset"],
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
    }
    with open(token_log_path(letter), "a", encoding="utf-8") as f:
        f.write(json.dumps(tok) + "\n")

    print(f"    [{letter}] in={input_tokens} out={output_tokens} "
          f"cost=${total_cost:.6f} time={duration_seconds}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd> [dataset_name]")
        print("  dataset_name: stattype  (default)")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2].lower() if len(sys.argv) > 2 else "stattype"

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[*] Model:   {MODEL}")
    print(f"[*] Dataset: {dataset_name}")
    print(f"[*] Budget:  ${budget:.4f}")

    # ── Preprocessing ───────────────────────────────────────────────────────
    entries   = load_dataset(dataset_name)
    per_entry = use_per_entry_files(entries)
    entry_map = {(e["entry_name"], e["variant"]): e for e in entries}
    print(f"[*] Output:  {'per-entry files' if per_entry else 'aggregate outputs_A/B.jsonl'}")

    prompts = {letter: load_prompt(letter) for letter in PROMPTS}
    client  = anthropic.Anthropic()

    # ── Budget loop ─────────────────────────────────────────────────────────
    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.6f}  remaining=${remaining:.6f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(entries, per_entry)

        if not partial and not untouched:
            print("[*] All eligible entries processed. Stopping.")
            break

        if partial:
            entry = random.choice(partial)
            print(f"[*] Completing partial: {entry['entry_name']}/{entry['variant']}")
        else:
            entry = random.choice(untouched)
            print(f"[*] New entry: {entry['entry_name']}/{entry['variant']}  "
                  f"partial_code_len={len(entry['partial_code'])}")

        completed = {p: get_completed(p, per_entry, entries) for p in PROMPTS}
        key       = (entry["entry_name"], entry["variant"])

        for letter in PROMPTS:
            if key in completed[letter]:
                print(f"    [{letter}] already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_entry(entry, letter, prompts[letter], client, per_entry)


if __name__ == "__main__":
    main()
