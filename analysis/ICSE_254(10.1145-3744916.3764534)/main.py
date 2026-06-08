"""
ReInFix (program repair) inference script.
Calls the LLM for each buggy function and writes per-example records to outputs/.
Defects4J validation is deferred to evaluator.py.

Usage:
  python main.py --llm claude|kimi --prompt A|B|both --n N

Output:
  outputs/outputs_{P}.jsonl
  Each line includes: {bug_id, version, scenario, file_path, predicted_fix/predicted_fixes, prompt_sent, raw_response}
"""

import argparse
import ast
import concurrent.futures
import json
import os
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from cost_tracker import CostTracker as _CostTracker
except ImportError:
    _CostTracker = None

_cost_tracker = None

# ── LLM clients ───────────────────────────────────────────────────────────────

def call_claude(prompt: str, model: str = "claude-sonnet-4-6") -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    if _cost_tracker is not None:
        _cost_tracker.add(model, msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text


def call_kimi(prompt: str, model: str = "Kimi K2.5") -> str:
    import requests
    api_key = os.environ.get("UVARC_GenAI_API")
    if not api_key:
        raise EnvironmentError("UVARC_GenAI_API is not set.")
    url = "https://open-webui.rc.virginia.edu/api/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0, "top_p": 0.9, "stream": True,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=300, stream=True)
    resp.raise_for_status()
    parts = []
    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            text = chunk["choices"][0]["delta"].get("content", "")
            if text:
                parts.append(text)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return "".join(parts)


LLM_DISPATCH = {"claude": call_claude, "kimi": call_kimi}

# ── Dataset ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR / "dataset"
SF_DATASET_FILE = DATASET_DIR / "defects4j-sf.json"
MF_DATASET_FILE = DATASET_DIR / "defects4j-mf.json"
BUG_LIST_FILE = DATASET_DIR / "bug_list_d4j.txt"


def parse_bug_list():
    text = BUG_LIST_FILE.read_text(encoding="utf-8")
    raw_lists = re.findall(r"\[[^\]]*\]", text)
    if len(raw_lists) < 4:
        raise ValueError(f"Expected four bug ID lists in {BUG_LIST_FILE}")
    parsed = [ast.literal_eval(raw) for raw in raw_lists[:4]]
    return {
        ("v1.2", "sf"): parsed[0],
        ("v1.2", "mf"): parsed[1],
        ("v2.0", "sf"): parsed[2],
        ("v2.0", "mf"): parsed[3],
    }


def _trigger_text(trigger_tests):
    trigger_src_list, err_msg_list = [], []
    for tt in trigger_tests.values():
        trigger_src_list.append(tt.get("src", ""))
        err_msg_list.append(tt.get("clean_error_msg", tt.get("error_msg", "")))
    return "\n---\n".join(trigger_src_list), "\n---\n".join(err_msg_list)


def _mf_buggy_functions(functions):
    blocks = []
    for idx, function in enumerate(functions, start=1):
        comment = function.get("comment", "")
        buggy = function.get("buggy_fl") or function.get("buggy_function", "")
        path = function.get("path", "")
        blocks.append(
            f"Function ID: {idx}\n"
            f"file_path: {path}\n"
            f"{comment}{buggy}"
        )
    return "\n\n---\n\n".join(blocks)


def load_dataset():
    with open(SF_DATASET_FILE) as f:
        sf_data = json.load(f)
    with open(MF_DATASET_FILE) as f:
        mf_data = json.load(f)

    bug_lists = parse_bug_list()
    examples = []
    for bench in ["v1.2", "v2.0"]:
        for scen in ["sf", "mf"]:
            dataset = sf_data if scen == "sf" else mf_data
            for name in bug_lists[(bench, scen)]:
                if name not in dataset:
                    print(f"  WARNING: {name} missing from {scen} dataset")
                    continue
                d = dataset[name]
                trigger_src, error_message = _trigger_text(d.get("trigger_test", {}))
                if scen == "sf":
                    examples.append({
                        "bug_id": name,
                        "benchmark": bench,
                        "scenario": scen,
                        "buggy_function": d.get("buggy_fl", ""),
                        "file_path": d.get("loc", ""),
                        "trigger_test_src": trigger_src,
                        "error_message": error_message,
                        "issue_title": d.get("issue_title", ""),
                    })
                else:
                    functions = d.get("functions", [])
                    examples.append({
                        "bug_id": name,
                        "benchmark": bench,
                        "scenario": scen,
                        "buggy_function": _mf_buggy_functions(functions),
                        "file_path": functions[0].get("path", "") if functions else "",
                        "trigger_test_src": trigger_src,
                        "error_message": error_message,
                        "issue_title": "",
                        "function_count": len(functions),
                    })
    return examples

# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(system_prompt: str, example: dict) -> str:
    if example.get("scenario") == "mf":
        mf_instruction = (
            "This is a multi-function repair case. The input contains multiple "
            "buggy functions labeled by Function ID. Output only one JSON object "
            "with a `fixed_functions` field mapping each Function ID string to "
            "the complete corrected source code for that function."
        )
        user_block = (
            f"{mf_instruction}\n\n"
            f"buggy_functions:\n{example['buggy_function']}\n\n"
            f"trigger_test_src:\n{example['trigger_test_src']}\n\n"
            f"error_message:\n{example['error_message']}\n\n"
            f"issue_title:\n{example['issue_title']}"
        )
    else:
        user_block = (
            f"buggy_function:\n{example['buggy_function']}\n\n"
            f"trigger_test_src:\n{example['trigger_test_src']}\n\n"
            f"error_message:\n{example['error_message']}\n\n"
            f"issue_title:\n{example['issue_title']}"
        )
    return f"{system_prompt}\n\n---\n\n{user_block}"

# ── Output parser ─────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> Optional[dict]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


def parse_fixed_payload(raw: str, scenario: str) -> dict:
    payload = _parse_json_response(raw) or {}
    if scenario == "mf":
        fixed_functions = payload.get("fixed_functions")
        if isinstance(fixed_functions, list):
            fixed_functions = {str(idx): value for idx, value in enumerate(fixed_functions, start=1)}
        if not isinstance(fixed_functions, dict):
            fixed_functions = {}
        return {"predicted_fix": "", "predicted_fixes": fixed_functions}
    fixed = payload.get("fixed_function")
    return {"predicted_fix": fixed if isinstance(fixed, str) else "", "predicted_fixes": None}

# ── Per-example worker ────────────────────────────────────────────────────────

_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(ex: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    prompt = build_prompt(system_prompt, ex)
    raw = ""
    llm_response_time = 0.0
    fixed_payload = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            fixed_payload = parse_fixed_payload(raw, ex.get("scenario", "sf"))
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [{ex['bug_id']} prompt={prompt_label}]: {e}")
            break

    if fixed_payload is None:
        print(f"  WARNING [{ex['bug_id']} prompt={prompt_label}]: could not parse fixed payload")
        fixed_payload = {"predicted_fix": "", "predicted_fixes": None}

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] {ex['bug_id']} {ex.get('benchmark')} {ex.get('scenario')} prompt={prompt_label}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "bug_id": ex["bug_id"],
        "version": ex.get("benchmark"),
        "benchmark": ex.get("benchmark"),
        "scenario": ex.get("scenario", "sf"),
        "file_path": ex["file_path"],
        "predicted_fix": fixed_payload["predicted_fix"],
        "predicted_fixes": fixed_payload["predicted_fixes"],
        "prompt_sent": prompt,
        "raw_response": raw,
        "llm_response_time": llm_response_time,
    }


def completion_key(record: dict) -> str:
    version = record.get("version") or record.get("benchmark") or ""
    scenario = record.get("scenario") or ""
    return f"{version}|{scenario}|{record.get('bug_id', '')}"


def balanced_sample(pool: list, n: int, seed: Optional[int]) -> list:
    rng = random.Random(seed)
    by_version = {
        "v1.2": [ex for ex in pool if ex.get("benchmark") == "v1.2"],
        "v2.0": [ex for ex in pool if ex.get("benchmark") == "v2.0"],
    }
    n_v12 = n // 2
    n_v20 = n - n_v12
    selected = []
    for version, count in [("v1.2", n_v12), ("v2.0", n_v20)]:
        version_pool = by_version[version]
        selected.extend(rng.sample(version_pool, min(count, len(version_pool))))
    rng.shuffle(selected)
    return selected

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm",     choices=["claude", "kimi"], default="claude")
    parser.add_argument("--prompt",  choices=["A", "B", "both"], required=True)
    parser.add_argument("--n",       type=int, default=5)
    parser.add_argument("--sleep",   type=float, default=2.0)
    parser.add_argument("--model",   type=str, default=None)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--seed",    type=int, default=None)
    args = parser.parse_args()

    global _cost_tracker
    if args.llm == "claude" and _CostTracker is not None:
        _cost_tracker = _CostTracker()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]

    system_prompts = {}
    for pl in prompt_labels:
        pf = BASE_DIR / "prompts" / f"prompt_{pl}.txt"
        system_prompts[pl] = pf.read_text(encoding="utf-8").lstrip("﻿")

    outputs_dir = Path(__file__).parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {pl: outputs_dir / f"outputs_{pl}.jsonl" for pl in prompt_labels}
    call_fn = LLM_DISPATCH[args.llm]

    completed = {pl: set() for pl in prompt_labels}
    for pl in prompt_labels:
        if out_paths[pl].exists():
            with open(out_paths[pl]) as f:
                for line in f:
                    try:
                        completed[pl].add(completion_key(json.loads(line.strip())))
                    except (json.JSONDecodeError, KeyError):
                        continue
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    all_examples = load_dataset()
    if not all_examples:
        print(f"ERROR: No examples loaded from {BUG_LIST_FILE}")
        return

    fully_completed = set.intersection(*(completed[pl] for pl in prompt_labels)) if prompt_labels else set()
    pool = [ex for ex in all_examples if completion_key(ex) not in fully_completed]
    n_needed = max(0, args.n - len(fully_completed))
    examples = balanced_sample(pool, n_needed, args.seed)

    pending = [
        (ex, pl)
        for ex in examples
        for pl in prompt_labels
        if completion_key(ex) not in completed[pl]
    ]

    n_done = sum(len(v) for v in completed.values())
    total = n_done + len(pending)
    v12_count = sum(1 for ex in examples if ex.get("benchmark") == "v1.2")
    v20_count = sum(1 for ex in examples if ex.get("benchmark") == "v2.0")
    print(
        f"Selected {len(examples)} bugs ({v12_count} v1.2, {v20_count} v2.0) "
        f"× {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}"
    )

    if pending:
        counter_lock = threading.Lock()
        counter = [n_done]
        write_locks = {pl: threading.Lock() for pl in prompt_labels}

        def append_record(record: dict, pl: str):
            with write_locks[pl]:
                with open(out_paths[pl], "a") as f:
                    f.write(json.dumps(record) + "\n")

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = {
                executor.submit(
                    process_example, ex, pl, system_prompts[pl], call_fn,
                    args.model, args.sleep, counter, total, counter_lock
                ): (ex, pl) for ex, pl in pending
            }
            for future in concurrent.futures.as_completed(futures):
                ex, pl = futures[future]
                try:
                    record = future.result()
                    append_record(record, pl)
                except Exception as e:
                    print(f"  FATAL ERROR for {ex['bug_id']} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
