#!/usr/bin/env python3
"""
EchoFuzz single-call LLM pipeline (claude-sonnet-4-6).

Usage:
    python3 main.py --total_cost <float> [--dataset <name>]
"""

import argparse
import importlib.util
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime

import anthropic

# ── paths (all relative to this script) ──────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))

def _rel(*parts):
    return os.path.join(_BASE, *parts)

PROMPTS_DIR = _rel("prompts")
OUTPUTS_DIR = _rel("outputs")
RESULTS_DIR = _rel("results")
STATE_FILE  = _rel("outputs", "state.json")

# ── model constants ───────────────────────────────────────────────────────────
MODEL              = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS  = 32_000
INPUT_TOKEN_LIMIT  = 168_000         # 200 k context − 32 k output
PRICE_IN           = 3  / 1_000_000  # $/input-token
PRICE_OUT          = 15 / 1_000_000  # $/output-token
DURATION           = 300
ROUNDS             = 3
LARGE_OUTPUT_BYTES = 20_000          # threshold: separate file vs JSONL


# ── helpers ───────────────────────────────────────────────────────────────────

def load_prompt(letter: str) -> str:
    path = os.path.join(PROMPTS_DIR, f"prompt{letter}.py")
    spec = importlib.util.spec_from_file_location(f"prompt_{letter}", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.prompt


def extract_ground_truth(raw: str) -> list[str]:
    """Return all <report> label tokens found in the raw source."""
    return sorted(set(re.findall(r"<report>\s+(\w+)", raw)))


def strip_annotations(source: str) -> str:
    """Remove D2 evaluation metadata lines before sending to LLM."""
    source = re.sub(r"[^\n]*<report>[^\n]*\n?", "", source)
    source = re.sub(r"[^\n]*@vulnerable_at_lines[^\n]*\n?", "", source)
    return source


def build_user_message(source: str) -> str:
    return json.dumps(
        {"source_code": source, "duration": DURATION, "rounds": ROUNDS},
        indent=2,
    )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def parse_json_response(text: str) -> dict | None:
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
    return None


# ── state management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"selected": [], "target_count": 0}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_processed(outputs_dir: str) -> dict:
    """Returns {stem: set_of_completed_letters}."""
    processed: dict[str, set] = {}
    for letter in ("A", "B"):
        path = os.path.join(outputs_dir, f"outputs_{letter}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    stem = entry.get("contract")
                    if stem:
                        processed.setdefault(stem, set()).add(letter)
                except json.JSONDecodeError:
                    pass
    return processed


def token_log_path(outputs_dir: str, letter: str) -> str:
    return os.path.join(outputs_dir, f"tokens_{letter}.jsonl")


def append_token_log(outputs_dir: str, letter: str, entry: dict) -> None:
    with open(token_log_path(outputs_dir, letter), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_total_cost_spent(outputs_dir: str) -> float:
    """Reads cumulative cost from tokens_*.jsonl (source of truth for budget)."""
    total = 0.0
    for letter in ("A", "B"):
        path = token_log_path(outputs_dir, letter)
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    total += r.get("cost_usd", {}).get("total_cost", 0.0)
                except json.JSONDecodeError:
                    pass
    return round(total, 6)


def migrate_to_token_logs(outputs_dir: str) -> None:
    """
    One-time migration: if tokens_*.jsonl is absent but outputs_*.jsonl exists
    with embedded cost fields (from earlier runs), regenerate the token files so
    budget tracking carries over correctly.
    """
    for letter in ("A", "B"):
        tok_path = token_log_path(outputs_dir, letter)
        out_path = os.path.join(outputs_dir, f"outputs_{letter}.jsonl")
        if os.path.exists(tok_path) or not os.path.exists(out_path):
            continue
        print(f"  [migrate] outputs_{letter}.jsonl → tokens_{letter}.jsonl ...")
        count = 0
        with open(out_path, "r") as fin, open(tok_path, "a", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stem    = e.get("contract")
                cost    = e.get("cost")
                in_tok  = e.get("tokens_in")
                out_tok = e.get("tokens_out")
                elapsed = e.get("time_taken")
                if stem and cost is not None and in_tok is not None:
                    fout.write(json.dumps({
                        "model":            MODEL,
                        "prompt":           letter,
                        "contract":         stem,
                        "timestamp":        "migrated",
                        "duration_seconds": elapsed,
                        "tokens": {
                            "input_tokens":  in_tok,
                            "output_tokens": out_tok,
                            "total_tokens":  in_tok + out_tok,
                        },
                        "cost_usd": {
                            "input_cost":  round(in_tok  * PRICE_IN,  6),
                            "output_cost": round(out_tok * PRICE_OUT, 6),
                            "total_cost":  cost,
                        },
                    }) + "\n")
                    count += 1
        print(f"    migrated {count} entries.")


# ── output writing ────────────────────────────────────────────────────────────

def append_to_jsonl(outputs_dir: str, letter: str, entry: dict) -> None:
    path = os.path.join(outputs_dir, f"outputs_{letter}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def maybe_write_separate_file(outputs_dir: str, letter: str, stem: str,
                               entry: dict) -> None:
    raw = json.dumps(entry, indent=2)
    if len(raw.encode()) >= LARGE_OUTPUT_BYTES:
        sep_path = os.path.join(outputs_dir, f"{stem}_prompt{letter}.json")
        with open(sep_path, "w", encoding="utf-8") as f:
            f.write(raw)


# ── LLM call ─────────────────────────────────────────────────────────────────

def run_prompt(client: anthropic.Anthropic, stem: str, source: str,
               letter: str, system_prompt: str, outputs_dir: str) -> None:
    user_msg  = build_user_message(source)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    in_est = estimate_tokens(system_prompt) + estimate_tokens(user_msg)
    if in_est > INPUT_TOKEN_LIMIT:
        print(f"    [{letter}] SKIP {stem}: estimated input tokens {in_est} > limit")
        return

    print(f"    [{letter}] calling LLM for {stem} ...", flush=True)
    response_text = ""
    t_start = time.time()

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                response_text += chunk
                print(chunk, end="", flush=True)
            print()
            usage = stream.get_final_message().usage

        t_elapsed = round(time.time() - t_start, 3)
        in_tok    = usage.input_tokens
        out_tok   = usage.output_tokens
        in_cost   = round(in_tok  * PRICE_IN,  6)
        out_cost  = round(out_tok * PRICE_OUT, 6)
        cost      = round(in_cost + out_cost,  6)
        print(f"    [{letter}] tokens: in={in_tok} out={out_tok}  "
              f"cost=${cost}  time={t_elapsed}s")

    except Exception as exc:
        print(f"    [{letter}] ERROR on {stem}: {exc}")
        return

    parsed = parse_json_response(response_text)
    if parsed is None:
        raw_path = os.path.join(outputs_dir, f"{stem}_prompt{letter}_raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [{letter}] JSON parse failed — raw saved to {raw_path}")
        return

    # ── output entry (LLM response fields only) ───────────────────────────────
    entry = {"contract": stem, "timestamp": timestamp}
    entry.update(parsed)

    append_to_jsonl(outputs_dir, letter, entry)
    maybe_write_separate_file(outputs_dir, letter, stem, entry)
    print(f"    [{letter}] saved to outputs_{letter}.jsonl")

    # ── token / cost / time log (separate file, like ripple) ─────────────────
    append_token_log(outputs_dir, letter, {
        "model":            MODEL,
        "prompt":           letter,
        "contract":         stem,
        "timestamp":        timestamp,
        "duration_seconds": t_elapsed,
        "tokens": {
            "input_tokens":  in_tok,
            "output_tokens": out_tok,
            "total_tokens":  in_tok + out_tok,
        },
        "cost_usd": {
            "input_cost":  in_cost,
            "output_cost": out_cost,
            "total_cost":  cost,
        },
    })
    print(f"    [{letter}] logged to tokens_{letter}.jsonl")


# ── preprocessing ─────────────────────────────────────────────────────────────

def preprocess_dataset(dataset_dir: str) -> list[tuple[str, str, list[str]]]:
    """
    For every .sol file in dataset_dir:
      1. Read raw source.
      2. Extract ground-truth labels from <report> annotations.
      3. Strip those annotations so the LLM never sees them.
      4. Skip files that are empty after stripping.

    Returns list of (stem, clean_source, ground_truth_labels).
    """
    sol_files = sorted(f for f in os.listdir(dataset_dir) if f.endswith(".sol"))
    if not sol_files:
        print(f"ERROR: no .sol files found in {dataset_dir}", file=sys.stderr)
        sys.exit(1)

    contracts = []
    skipped   = 0
    labeled   = 0

    for fname in sol_files:
        path = os.path.join(dataset_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as exc:
            print(f"  WARNING: cannot read {fname}: {exc}")
            skipped += 1
            continue

        gt_labels = extract_ground_truth(raw)
        source    = strip_annotations(raw).strip()

        if not source:
            print(f"  WARNING: {fname} is empty after stripping — skipping")
            skipped += 1
            continue

        stem = os.path.splitext(fname)[0]
        contracts.append((stem, source, gt_labels))
        if gt_labels:
            labeled += 1

    print(f"  Loaded   : {len(contracts)} contracts  ({skipped} skipped)")
    print(f"  Labeled  : {labeled} contracts have ground-truth annotations")
    print(f"  Unlabeled: {len(contracts) - labeled} contracts (no <report> tags)")
    return contracts


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EchoFuzz single-call LLM pipeline"
    )
    parser.add_argument(
        "--total_cost", type=float, required=True,
        help="Budget in USD; stop when cumulative cost reaches this value."
    )
    parser.add_argument(
        "--dataset", type=str, default="D2",
        help="Dataset subfolder under dataset/ (default: D2)."
    )
    args = parser.parse_args()

    total_budget: float = args.total_cost
    dataset_dir = _rel("dataset", args.dataset)

    if not os.path.isdir(dataset_dir):
        print(f"ERROR: dataset directory not found: {dataset_dir}", file=sys.stderr)
        sys.exit(1)

    # ── setup ────────────────────────────────────────────────────────────────
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    migrate_to_token_logs(OUTPUTS_DIR)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    prompt_A = load_prompt("A")
    prompt_B = load_prompt("B")
    print("Prompts A and B loaded.")

    # ── preprocessing ────────────────────────────────────────────────────────
    print(f"\n[1] Preprocessing {args.dataset} dataset ...")
    contracts = preprocess_dataset(dataset_dir)

    n_total      = len(contracts)
    # target_count = max(1, math.ceil(n_total * 0.1))
    target_count = n_total
    print(f"  Total contracts : {n_total}")
    # print(f"  10% target      : {target_count}")

    contract_map = {stem: (src, gt) for stem, src, gt in contracts}
    all_stems    = [stem for stem, _, _ in contracts]

    # ── load state & processed outputs ───────────────────────────────────────
    state     = load_state()
    processed = get_processed(OUTPUTS_DIR)

    state["target_count"] = target_count
    save_state(state)

    print(f"\n[2] Resume check ...")
    print(f"  Previously selected : {len(state['selected'])}")
    print(f"  With outputs        : {len(processed)}")

    # ── step 1: complete any partial runs (one prompt done, other missing) ───
    for stem in list(state["selected"]):
        if stem not in contract_map:
            continue
        done    = processed.get(stem, set())
        missing = sorted({"A", "B"} - done)
        if not missing:
            continue
        cost_now = get_total_cost_spent(OUTPUTS_DIR)
        if cost_now >= total_budget:
            print(f"\nBudget exhausted (${cost_now:.6f} >= ${total_budget}).")
            return
        src, _ = contract_map[stem]
        print(f"\n  Completing partial: {stem}, missing prompt(s): {missing}")
        for letter in missing:
            prompt = prompt_A if letter == "A" else prompt_B
            run_prompt(client, stem, src, letter, prompt, OUTPUTS_DIR)

    # ── step 2: randomly add new contracts until target_count reached ─────────
    already_selected = set(state["selected"])
    candidates       = [s for s in all_stems if s not in already_selected]
    random.shuffle(candidates)

    print(f"\n[3] Selecting new contracts "
          f"(need {max(0, target_count - len(already_selected))} more) ...")

    for stem in candidates:
        if len(state["selected"]) >= target_count:
            break

        cost_now = get_total_cost_spent(OUTPUTS_DIR)
        if cost_now >= total_budget:
            print(f"\nBudget exhausted (${cost_now:.6f} >= ${total_budget}).")
            break

        src, _ = contract_map[stem]
        user_msg = build_user_message(src)

        tok_A = estimate_tokens(prompt_A) + estimate_tokens(user_msg)
        tok_B = estimate_tokens(prompt_B) + estimate_tokens(user_msg)
        if tok_A > INPUT_TOKEN_LIMIT or tok_B > INPUT_TOKEN_LIMIT:
            print(f"  SKIP {stem}: too large for context "
                  f"(A≈{tok_A}, B≈{tok_B} tokens)")
            continue

        print(f"\n  Selected: {stem}  "
              f"(spent so far: ${cost_now:.6f} / ${total_budget})")
        state["selected"].append(stem)
        save_state(state)

        run_prompt(client, stem, src, "A", prompt_A, OUTPUTS_DIR)
        run_prompt(client, stem, src, "B", prompt_B, OUTPUTS_DIR)

    # ── summary ───────────────────────────────────────────────────────────────
    final_cost = get_total_cost_spent(OUTPUTS_DIR)
    print(f"\nDone.")
    print(f"  Contracts selected : {len(state['selected'])} / {target_count} target")
    print(f"  Total cost spent   : ${final_cost:.6f}")
    print(f"  Outputs written to : {os.path.relpath(OUTPUTS_DIR, _BASE)}/")


if __name__ == "__main__":
    main()
