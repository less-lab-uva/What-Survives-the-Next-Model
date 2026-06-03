#!/usr/bin/env python3
"""
Randomly samples PRs from data/pulled_prs and runs the regression detection
pipeline (Prompt A and Prompt B) until the budget is exhausted.

Usage:
    python3 run_random.py <budget_usd>

Example:
    python3 run_random.py 5.0
"""

import anthropic
import importlib.util
import json
import os
import random
import re
import sys
from datetime import datetime

TESTORA_ROOT = os.path.dirname(os.path.abspath(__file__))
PR_DIR       = os.path.join(TESTORA_ROOT, "data", "pulled_prs")
OUTPUT_DIR   = os.path.join(TESTORA_ROOT, "outputs")
PROMPTS      = ["A", "B"]


# ── dataset ───────────────────────────────────────────────────────────────────

def load_prs() -> list:
    """Return list of PR dicts loaded from all JSON files under data/pulled_prs/."""
    prs = []
    for root, _, files in os.walk(PR_DIR):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            # derive project name from directory structure
            rel = os.path.relpath(root, PR_DIR)
            parts = rel.replace("\\", "/").split("/")
            project = parts[-1] if parts else "unknown"
            data["project"] = project
            prs.append(data)
    return prs


# ── output JSONL ──────────────────────────────────────────────────────────────

def output_jsonl_path(prompt_letter: str) -> str:
    return os.path.join(OUTPUT_DIR, f"outputs_{prompt_letter}.jsonl")


def load_completed(prompt_letter: str) -> set:
    """Return set of (project, pr_number) tuples already in the JSONL output."""
    path = output_jsonl_path(prompt_letter)
    completed = set()
    if not os.path.exists(path):
        return completed
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                completed.add((record.get("project"), record.get("pr_number")))
            except json.JSONDecodeError:
                pass
    return completed


def save_result(pr: dict, result: dict, prompt_letter: str, timestamp: str) -> None:
    record = {
        "pr_number":                pr.get("pr_number"),
        "project":                  pr.get("project"),
        "timestamp":                timestamp,
        "verdict":                  result.get("verdict", ""),
        "test_case":                result.get("test_case", ""),
        "predicted_output_before_pr": result.get("predicted_output_before_pr", ""),
        "predicted_output_after_pr":  result.get("predicted_output_after_pr", ""),
        "explanation":              result.get("explanation", ""),
    }
    path = output_jsonl_path(prompt_letter)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ── budget ────────────────────────────────────────────────────────────────────

def get_total_spent() -> float:
    """Sum total_cost from all tokens_*.json files in the output folder."""
    total = 0.0
    if not os.path.exists(OUTPUT_DIR):
        return total
    for fname in os.listdir(OUTPUT_DIR):
        if fname.startswith("tokens_") and fname.endswith(".json"):
            fpath = os.path.join(OUTPUT_DIR, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    records = json.load(f)
                if isinstance(records, list):
                    total += sum(r.get("cost_usd", {}).get("total_cost", 0.0) for r in records)
            except (json.JSONDecodeError, KeyError):
                pass
    return round(total, 6)


# ── pending PRs ───────────────────────────────────────────────────────────────

def get_pending(prs: list) -> list:
    """PRs where at least one prompt result is still missing."""
    completed = {p: load_completed(p) for p in PROMPTS}
    return [
        pr for pr in prs
        if not all(
            (pr.get("project"), pr.get("pr_number")) in completed[p]
            for p in PROMPTS
        )
    ]


# ── API call ──────────────────────────────────────────────────────────────────

def load_prompt(prompt_letter: str) -> str:
    prompt_file = os.path.join(TESTORA_ROOT, f"prompt{prompt_letter}.py")
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


def run_pr(pr: dict, prompt_letter: str) -> None:
    system_prompt = load_prompt(prompt_letter)
    user_message  = json.dumps({
        "title":               pr.get("title", ""),
        "description":         pr.get("description", ""),
        "diff":                pr.get("diff", ""),
        "commit_messages":     pr.get("commit_messages", []),
        "discussion_comments": pr.get("discussion_comments", []),
    }, indent=2)

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

    result = parse_json_response(response_text)

    if result.get("verdict"):
        save_result(pr, result, prompt_letter, timestamp)
        print(f"    [+] Saved to {output_jsonl_path(prompt_letter)}")
    else:
        raw_path = os.path.join(
            OUTPUT_DIR,
            f"raw_pr{pr.get('pr_number')}_prompt{prompt_letter}_{timestamp}.txt",
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    token_file = os.path.join(OUTPUT_DIR, f"tokens_{prompt_letter}.json")
    record = {
        "model":      "claude-sonnet-4-6",
        "prompt":     prompt_letter,
        "project":    pr.get("project"),
        "pr_number":  pr.get("pr_number"),
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
    if len(sys.argv) < 2:
        print("Usage: python3 run_random.py <budget_usd>")
        sys.exit(1)

    budget = float(sys.argv[1])
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    prs = load_prs()
    print(f"[*] Loaded {len(prs)} PRs from {PR_DIR}")
    print(f"[*] Budget: ${budget:.4f}")

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        pool = get_pending(prs)
        if not pool:
            print("[*] All PRs processed. Stopping.")
            break

        pr = random.choice(pool)
        print(f"[*] Selected: project={pr.get('project')}  pr={pr.get('pr_number')}  "
              f"title={pr.get('title', '')[:60]!r}")

        for letter in PROMPTS:
            completed = load_completed(letter)
            if (pr.get("project"), pr.get("pr_number")) in completed:
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            print(f"    prompt {letter}: running ...")
            run_pr(pr, letter)


if __name__ == "__main__":
    main()
