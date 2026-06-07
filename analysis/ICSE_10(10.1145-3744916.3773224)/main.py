#!/usr/bin/env python3
"""
Randomly samples 10% of CoderEval tasks from input/input_codereval.jsonl
and runs both Prompt A and Prompt B on each sampled task until the
budget is exhausted.

Outputs (under outputs/):
  outputs_A.jsonl      — one JSON line per task: input trace + predictions for Prompt A
  outputs_B.jsonl      — same for Prompt B
  tokens_A.jsonl       — token/cost/time log for Prompt A
  tokens_B.jsonl       — token/cost/time log for Prompt B

Usage:
    python3 main.py <budget_usd>

Example:
    python3 main.py 5.0
"""

import importlib.util
import json
import os
import random
import re
import sys
import time
from datetime import datetime

import anthropic

PROJECT_FOLDER = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE     = os.path.join(PROJECT_FOLDER, "input", "input_codereval.jsonl")
OUTPUTS_FOLDER = os.path.join(PROJECT_FOLDER, "outputs")
PROMPTS        = ["A", "B"]
MODEL          = "claude-sonnet-4-6"
INPUT_PRICE    = 3.0    # USD per 1M input tokens
OUTPUT_PRICE   = 15.0   # USD per 1M output tokens


def load_prompt(letter: str) -> str:
    path = os.path.join(PROJECT_FOLDER, f"prompt{letter}.py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Prompt file not found: {path}")
    spec   = importlib.util.spec_from_file_location("prompt_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable found in {path}")
    return module.prompt


def load_tasks() -> list:
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_results(letter: str) -> list:
    path = os.path.join(OUTPUTS_FOLDER, f"outputs_{letter}.jsonl")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (json.JSONDecodeError, OSError):
        return []


def get_completed_ids(letter: str) -> set:
    return {r["_id"] for r in load_results(letter)}


def has_result(task_id: str, letter: str) -> bool:
    return task_id in get_completed_ids(letter)


def get_touched_ids() -> set:
    """IDs that have been processed by at least one prompt in any prior run."""
    touched = set()
    for letter in PROMPTS:
        touched |= get_completed_ids(letter)
    return touched


def build_pool(all_tasks: list, pool_size: int) -> list:
    """
    Build the working pool so that total distinct tasks ever run stays at pool_size.
    Already-touched tasks count toward the quota; remaining slots are filled
    randomly from completely untouched tasks.
    """
    touched_ids   = get_touched_ids()
    touched_tasks = [t for t in all_tasks if t["metadata"]["_id"] in touched_ids]

    remaining_slots = pool_size - len(touched_tasks)
    if remaining_slots > 0:
        untouched      = [t for t in all_tasks if t["metadata"]["_id"] not in touched_ids]
        newly_sampled  = random.sample(untouched, min(remaining_slots, len(untouched)))
    else:
        newly_sampled = []

    return touched_tasks + newly_sampled


def get_pending(pool: list) -> tuple:
    """
    Returns (partial, untouched):
      partial   — tasks where at least one prompt is done but not all
      untouched — tasks where no prompt has been run yet
    Callers should always drain partial before picking from untouched.
    """
    completed = {p: get_completed_ids(p) for p in PROMPTS}
    partial, untouched = [], []
    for t in pool:
        tid  = t["metadata"]["_id"]
        done = [p for p in PROMPTS if tid in completed[p]]
        if done and len(done) < len(PROMPTS):
            partial.append(t)
        elif not done:
            untouched.append(t)
    return partial, untouched


def get_total_spent() -> float:
    total = 0.0
    if not os.path.exists(OUTPUTS_FOLDER):
        return total
    for fname in os.listdir(OUTPUTS_FOLDER):
        if fname.startswith("tokens_") and fname.endswith(".jsonl"):
            fpath = os.path.join(OUTPUTS_FOLDER, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            r = json.loads(line)
                            total += r.get("cost_usd", {}).get("total_cost", 0.0)
            except (json.JSONDecodeError, KeyError):
                pass
    return round(total, 6)


def build_user_message(task: dict) -> str:
    return json.dumps(
        {"prompt": task["prompt"], "current_file": task["current_file"]},
        indent=2,
    )


def parse_predictions(response_text: str) -> list:
    stripped = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped.strip(), flags=re.MULTILINE)
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict) and "predictions" in obj:
            return obj["predictions"]
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if "predictions" in obj:
                return obj["predictions"]
        except json.JSONDecodeError:
            pass
    return []


def append_result(letter: str, entry: dict):
    """Append one result entry (input trace + predictions) to outputs_{letter}.jsonl."""
    path = os.path.join(OUTPUTS_FOLDER, f"outputs_{letter}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def append_token_log(letter: str, entry: dict):
    path = os.path.join(OUTPUTS_FOLDER, f"tokens_{letter}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def run_prompt(task: dict, letter: str, system_prompt: str, client: anthropic.Anthropic):
    meta      = task["metadata"]
    task_id   = meta["_id"]
    func_name = meta["function_name"]
    user_msg  = build_user_message(task)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"    prompt {letter}: running [{func_name}] ...")
    t_start = time.time()
    response_text = ""
    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for chunk in stream.text_stream:
            response_text += chunk
            print(chunk, end="", flush=True)
        print()
        usage = stream.get_final_message().usage
    duration_seconds = round(time.time() - t_start, 3)

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost   = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    predictions = parse_predictions(response_text)

    if predictions:
        append_result(letter, {
            "_id":           task_id,
            "task_id":       meta["task_id"],
            "function_name": func_name,
            "timestamp":     timestamp,
            "input": {
                "prompt":       task["prompt"],
                "current_file": task["current_file"],
            },
            "predictions": predictions,
        })
        print(f"    [+] Result appended to outputs_{letter}.jsonl")
    else:
        raw_path = os.path.join(OUTPUTS_FOLDER, f"{task_id}_prompt{letter}_raw_{timestamp}.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    append_token_log(letter, {
        "model":            MODEL,
        "prompt":           letter,
        "task_id":          task_id,
        "function_name":    func_name,
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd>")
        sys.exit(1)

    budget = float(sys.argv[1])
    os.makedirs(OUTPUTS_FOLDER, exist_ok=True)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    all_tasks = load_tasks()
    total     = len(all_tasks)
    pool_size = max(1, total // 10)
    pool      = build_pool(all_tasks, pool_size)

    already_done = len(get_touched_ids())
    print(f"[*] Total tasks in dataset : {total}")
    print(f"[*] 10% quota              : {pool_size}")
    print(f"[*] Already touched        : {already_done}")
    print(f"[*] Newly sampled this run : {len(pool) - already_done}")
    print(f"[*] Active pool size       : {len(pool)}")
    print(f"[*] Budget                 : ${budget:.4f}")

    prompts = {letter: load_prompt(letter) for letter in PROMPTS}
    client  = anthropic.Anthropic()

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(pool)
        if not partial and not untouched:
            print("[*] All sampled tasks processed. Stopping.")
            break

        if partial:
            task = random.choice(partial)
        else:
            task = random.choice(untouched)

        task_id = task["metadata"]["_id"]
        status  = "Completing partial" if partial else "Selected new task"
        print(f"[*] {status}: {task_id}  func={task['metadata']['function_name']}")

        for letter in PROMPTS:
            if has_result(task_id, letter):
                print(f"    prompt {letter}: already exists, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_prompt(task, letter, prompts[letter], client)


if __name__ == "__main__":
    main()
