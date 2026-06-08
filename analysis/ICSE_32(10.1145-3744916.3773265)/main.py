#!/usr/bin/env python3
"""
Runs the single-LLM CIA pipeline on 10% of the 100 paper-evaluated instances,
using both Prompt A and Prompt B, until the given budget is exhausted.

Preprocessing (runs at startup):
  1. Reads assets/all-outputs.zip to identify the 100 paper instances.
  2. Selects a pool of 10% (= 10 instances) to work on:
       - Already-touched instances (from prior runs) are kept in the pool.
       - Remaining slots are filled randomly from the 100.
  3. For each pool instance that is missing input files, clones the repo into
     repos/<project-name>/, checks out the parent commit, then runs
     extract_methods to produce issue.json, repo_structure.xml, commit_history.json.

Budget loop:
  - On resume: finishes any partial instance (one prompt done, the other not)
    before randomly picking a new one.
  - Total distinct instances across all runs stays at the 10% quota; all are distinct.
  - Stops when budget is exhausted or all quota instances are fully done.

Outputs (in outputs/):
  instance-XXXXX_promptA.json   — parsed LLM response for Prompt A
  instance-XXXXX_promptB.json   — parsed LLM response for Prompt B
  tokens_A.jsonl                — token / cost / time log (JSONL, one line per run)
  tokens_B.jsonl                — same for Prompt B

Usage:
    python3 main.py <budget_usd>

Example:
    python3 main.py 20.0
"""

import importlib.util
import json
import os
import random
import re
import sys
import time
import zipfile
from pathlib import Path
from datetime import datetime

import anthropic

from extract_methods import extract_for_instance, prepare_repo

# ---------------------------------------------------------------------------
# Paths — all relative to this file
# ---------------------------------------------------------------------------
BASE_DIR        = Path(__file__).parent
PROMPTS_FOLDER  = BASE_DIR / "prompts"
OUTPUT_FOLDER   = BASE_DIR / "outputs"
INPUT_FOLDER    = BASE_DIR / "input"
REPOS_FOLDER    = BASE_DIR / "repos"
ALL_OUTPUTS_ZIP = BASE_DIR / "assets" / "all-outputs.zip"
CIA_DATASET     = BASE_DIR / "assets" / "cia-dataset.json"

REQUIRED_INPUTS = ["issue.json", "repo_structure.xml", "commit_history.json"]
PROMPTS      = ["A", "B"]
MODEL        = "claude-sonnet-4-6"
INPUT_PRICE  = 3.0    # USD per 1M input tokens
OUTPUT_PRICE = 15.0   # USD per 1M output tokens


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
def load_prompt(letter: str) -> str:
    path = PROMPTS_FOLDER / f"prompt{letter}.py"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    spec   = importlib.util.spec_from_file_location("prompt_module", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable found in {path}")
    return module.prompt


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------
def load_target_ids() -> list:
    """Return sorted list of 100 instance IDs the paper evaluated on."""
    ids = set()
    with zipfile.ZipFile(ALL_OUTPUTS_ZIP) as z:
        for name in z.namelist():
            m = re.match(
                r"all-outputs/(claude|gpt|gemini)/(instance-\d+)\.json", name
            )
            if m:
                ids.add(m.group(2))
    return sorted(ids)


def load_cia_data() -> dict:
    """Return flat dict: instance_id → instance_data (with 'repo' key added)."""
    with open(CIA_DATASET) as f:
        raw = json.load(f)
    by_id = {}
    for repo_key, instances in raw.items():
        for inst in instances:
            by_id[inst['id']] = {**inst, 'repo': repo_key}
    return by_id


# ---------------------------------------------------------------------------
# Input completeness
# ---------------------------------------------------------------------------
def is_input_complete(instance_id: str) -> bool:
    folder = INPUT_FOLDER / instance_id
    return all((folder / f).exists() for f in REQUIRED_INPUTS)


# ---------------------------------------------------------------------------
# User message construction
# ---------------------------------------------------------------------------
def build_user_message(instance_id: str) -> str:
    folder   = INPUT_FOLDER / instance_id
    combined = {}
    for fname in REQUIRED_INPUTS:
        content = (folder / fname).read_text(encoding='utf-8')
        if fname == "issue.json":
            combined.update(json.loads(content))
        elif fname == "repo_structure.xml":
            combined["repository"] = content
        elif fname == "commit_history.json":
            combined["commit_history"] = json.loads(content)
    return json.dumps(combined, indent=2)


# ---------------------------------------------------------------------------
# Output / completion tracking
# ---------------------------------------------------------------------------
def outputs_log_path(letter: str) -> Path:
    return OUTPUT_FOLDER / f"outputs_{letter}.jsonl"


def get_completed_ids(letter: str) -> set:
    """Return the set of instance_ids already recorded in outputs_{letter}.jsonl."""
    path = outputs_log_path(letter)
    if not path.exists():
        return set()
    ids = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)["instance_id"])
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return ids


def is_done(instance_id: str, letter: str) -> bool:
    return instance_id in get_completed_ids(letter)


def get_touched_ids(universe: list) -> set:
    """IDs in universe that appear in at least one prompt's output log."""
    completed = {p: get_completed_ids(p) for p in PROMPTS}
    return {i for i in universe if any(i in completed[p] for p in PROMPTS)}


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------
def build_pool(universe: list, pool_size: int) -> list:
    """
    Ensure total distinct instances stays at pool_size.
    Already-touched instances are always kept; remaining slots are filled
    randomly from untouched ones.
    """
    touched     = get_touched_ids(universe)
    touched_lst = [i for i in universe if i in touched]
    remaining   = pool_size - len(touched_lst)
    if remaining > 0:
        untouched     = [i for i in universe if i not in touched]
        newly_sampled = random.sample(untouched, min(remaining, len(untouched)))
    else:
        newly_sampled = []
    return touched_lst + newly_sampled


def get_pending(pool: list) -> tuple:
    """
    Returns (partial, untouched).
    partial   — instances where some but not all prompts are done.
    untouched — instances where no prompt has been run yet.
    Always drain partial before picking from untouched.
    """
    completed = {p: get_completed_ids(p) for p in PROMPTS}
    partial, untouched = [], []
    for inst_id in pool:
        done = [p for p in PROMPTS if inst_id in completed[p]]
        if done and len(done) < len(PROMPTS):
            partial.append(inst_id)
        elif not done:
            untouched.append(inst_id)
    return partial, untouched


# ---------------------------------------------------------------------------
# Spending tracker (reads only outputs/tokens_*.jsonl)
# ---------------------------------------------------------------------------
def token_log_path(letter: str) -> Path:
    return OUTPUT_FOLDER / f"tokens_{letter}.jsonl"


def get_total_spent() -> float:
    total = 0.0
    for letter in PROMPTS:
        path = token_log_path(letter)
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    total += r.get("cost_usd", {}).get("total_cost", 0.0)
        except (json.JSONDecodeError, OSError):
            pass
    return round(total, 6)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def parse_response(response_text: str) -> dict:
    # 1. Prefer an explicit ```json ... ``` fence (handles reasoning-before-answer responses)
    m = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Scan all { positions right-to-left; raw_decode rejects non-JSON on the spot
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r'\{', response_text))):
        try:
            obj, _ = decoder.raw_decode(response_text, match.start())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    return {}


# ---------------------------------------------------------------------------
# Token log
# ---------------------------------------------------------------------------
def append_token_log(letter: str, entry: dict):
    path = token_log_path(letter)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Single prompt run
# ---------------------------------------------------------------------------
def run_prompt(
    instance_id: str,
    letter: str,
    system_prompt: str,
    client: anthropic.Anthropic,
):
    user_msg  = build_user_message(instance_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Pre-flight: estimate tokens (~3.5 chars/token); hard API limit is 1,000,000
    estimated_tokens = (len(system_prompt) + len(user_msg)) / 3.5
    if estimated_tokens > 950_000:
        print(f"    prompt {letter}: SKIPPED — estimated {int(estimated_tokens):,} tokens exceeds limit")
        with open(outputs_log_path(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "instance_id": instance_id, "timestamp": timestamp,
                "skipped": True, "reason": "too_large",
                "estimated_tokens": int(estimated_tokens),
            }) + "\n")
        return

    print(f"    prompt {letter}: running {instance_id} ...")
    t_start       = time.time()
    response_text = ""
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                response_text += chunk
                print(chunk, end="", flush=True)
            print()
            usage = stream.get_final_message().usage
    except anthropic.BadRequestError as e:
        if "prompt is too long" in str(e):
            print(f"    prompt {letter}: SKIPPED — {e}")
            with open(outputs_log_path(letter), "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "instance_id": instance_id, "timestamp": timestamp,
                    "skipped": True, "reason": "too_large",
                }) + "\n")
            return
        raise
    duration_seconds = round(time.time() - t_start, 3)

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost   = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    result = parse_response(response_text)
    log_entry = {"instance_id": instance_id, "timestamp": timestamp}
    if result:
        log_entry.update(result)
        print(f"    [+] Appended to outputs_{letter}.jsonl")
    else:
        raw_path = OUTPUT_FOLDER / f"{instance_id}_prompt{letter}_raw_{timestamp}.txt"
        raw_path.write_text(response_text, encoding='utf-8')
        log_entry["parse_failed"] = True
        log_entry["raw_file"]     = raw_path.name
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    with open(outputs_log_path(letter), "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    append_token_log(letter, {
        "model":            MODEL,
        "prompt":           letter,
        "instance_id":      instance_id,
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
    print(
        f"    tokens: in={input_tokens} out={output_tokens} "
        f"cost=${total_cost}  time={duration_seconds}s"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd>")
        sys.exit(1)

    budget = float(sys.argv[1])
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    REPOS_FOLDER.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    # --- Step 1: identify 100 target instances ---
    print("[*] Preprocessing ...")
    target_ids = load_target_ids()
    cia_data   = load_cia_data()
    pool_size  = max(1, len(target_ids) // 10)   # 10% of 100 = 10

    prompts = {letter: load_prompt(letter) for letter in PROMPTS}
    client  = anthropic.Anthropic()

    already_touched = get_touched_ids(target_ids)
    print(f"    Paper instances (all-outputs.zip) : {len(target_ids)}")
    print(f"    10% pool size                     : {pool_size}")
    print(f"    Already touched from prior runs   : {len(already_touched)}")

    # --- Step 2: iteratively prepare instances, skipping any that exceed the limit ---
    # Token limit: Claude's hard limit is 1,000,000; we use 950,000 as a safe threshold.
    MAX_TOKENS  = 950_000
    CHARS_PER_TOKEN = 3.5
    sys_chars   = max(len(p) for p in prompts.values())

    def estimate_tokens(instance_id: str) -> int:
        folder = INPUT_FOLDER / instance_id
        user_chars = sum(
            (folder / f).stat().st_size
            for f in REQUIRED_INPUTS if (folder / f).exists()
        )
        return int((sys_chars + user_chars) / CHARS_PER_TOKEN)

    # Already-touched instances always stay in the pool (may be partially run).
    pool        = [i for i in target_ids if i in already_touched]
    candidates  = [i for i in target_ids if i not in already_touched]
    random.shuffle(candidates)

    print(f"\n[*] Building pool (target {pool_size}) — preparing and size-checking ...")
    failed_prep = set()
    for inst_id in candidates:
        if len(pool) >= pool_size:
            break

        inst_data = cia_data.get(inst_id)
        if inst_data is None:
            continue

        if is_input_complete(inst_id):
            print(f"  {inst_id}: input already complete.")
        else:
            print(f"  {inst_id}: preparing input ...")
            try:
                repo_dir = prepare_repo(
                    inst_data['repo'], inst_data['parent-commit'], REPOS_FOLDER,
                )
                ok = extract_for_instance(
                    inst_id, inst_data, repo_dir, INPUT_FOLDER / inst_id,
                )
                if not ok:
                    print(f"  [!] {inst_id}: seed method not found; input may be incomplete.")
            except Exception as e:
                print(f"  [!] {inst_id}: preparation failed — {e}. Skipping.")
                failed_prep.add(inst_id)
                continue

        est = estimate_tokens(inst_id)
        if est > MAX_TOKENS:
            print(f"  {inst_id}: TOO LARGE (~{est:,} tokens > {MAX_TOKENS:,}) — discarding.")
            import shutil
            shutil.rmtree(INPUT_FOLDER / inst_id, ignore_errors=True)
            continue

        print(f"  {inst_id}: accepted (~{est:,} estimated tokens).")
        pool.append(inst_id)

    # Pool instances that are ready to run
    runnable = [i for i in pool if i not in failed_prep and is_input_complete(i)]
    skipped  = [i for i in pool if i not in runnable]
    print(f"\n[*] Active pool           : {pool}")
    print(f"[*] Runnable instances    : {len(runnable)}")
    if skipped:
        print(f"[*] Skipped (prep failed) : {skipped}")

    if not runnable:
        print("[!] No runnable instances. Exiting.")
        sys.exit(1)

    print(f"\n[*] Budget : ${budget:.4f}")

    # --- Budget loop ---
    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(runnable)
        if not partial and not untouched:
            print("[*] All sampled instances processed. Stopping.")
            break

        if partial:
            inst_id = random.choice(partial)
            status  = "Completing partial"
        else:
            inst_id = random.choice(untouched)
            status  = "Selected new instance"

        print(f"[*] {status}: {inst_id}")

        for letter in PROMPTS:
            if is_done(inst_id, letter):
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_prompt(inst_id, letter, prompts[letter], client)

    # --- Summary ---
    final_spent   = get_total_spent()
    final_touched = get_touched_ids(target_ids)
    print(f"\n[*] Run complete.")
    print(f"    Total spent       : ${final_spent:.4f}")
    print(f"    Instances touched : {len(final_touched)} / {pool_size} (quota)")


if __name__ == "__main__":
    main()
