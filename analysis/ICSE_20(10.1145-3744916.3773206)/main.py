"""
HoarePrompt inference script.
Calls the LLM for each example and writes per-example records to outputs/.

Usage:
  python main.py --llm claude|kimi --prompt A|B --n N [--model MODEL] [--sleep S] [--threads T]

Output:
  outputs/outputs_{llm}_prompt{P}_n{N}.jsonl
  Each line: {id, source_file, ground_truth, predicted, match, prompt_sent, raw_response}
"""

import argparse
import concurrent.futures
import json
import os
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

DATA_DIR = Path(__file__).parent / "dataset"


def load_dataset(n: int, dataset_file: Optional[Path] = None):
    files = [dataset_file] if dataset_file else sorted(DATA_DIR.glob("*.json"))
    examples = []
    for json_file in files:
        try:
            data = json.loads(json_file.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            desc = item.get("description", "")
            code = item.get("generated_code", "")
            correct = item.get("correct")
            task_id = item.get("task_id") or item.get("task_name") or item.get("unique_id", "unknown")
            if not desc or not code or correct is None:
                continue
            examples.append({
                "id": str(task_id),
                "source_file": json_file.name,
                "description": desc,
                "generated_code": code,
                "ground_truth": bool(correct),
            })
            if len(examples) >= n:
                return examples
    return examples

# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(system_prompt: str, example: dict) -> str:
    user_block = (
        f"description:\n{example['description']}\n\n"
        f"generated_code:\n```\n{example['generated_code']}\n```"
    )
    return f"{system_prompt}\n\n---\n\n{user_block}"

# ── Output parser ─────────────────────────────────────────────────────────────

def parse_verdict(raw: str) -> Optional[str]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        obj = json.loads(text)
        return str(obj.get("verdict", "")).strip().upper() or None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end])
                return str(obj.get("verdict", "")).strip().upper() or None
            except json.JSONDecodeError:
                pass
    for word in ("INCORRECT", "CORRECT"):
        if re.search(rf"\b{word}\b", text.upper()):
            return word
    return None

# ── Per-example worker ────────────────────────────────────────────────────────

_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(ex: dict, system_prompt: str, call_fn, model_arg: Optional[str],
                    sleep_sec: float, counter: list, total: int, lock: threading.Lock) -> dict:
    prompt = build_prompt(system_prompt, ex)
    raw = ""
    llm_response_time = 0.0
    verdict = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            verdict = parse_verdict(raw)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [{ex['id']}]: {e}")
            break

    if verdict is None:
        print(f"  WARNING [{ex['id']}]: could not parse verdict — raw: {raw[:120]!r}")
        verdict = "UNKNOWN"

    gt_str = "CORRECT" if ex["ground_truth"] else "INCORRECT"
    match = verdict == gt_str

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] {ex['id']} | gt={gt_str} | predicted={verdict} | match={match}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "id": ex["id"],
        "source_file": ex["source_file"],
        "ground_truth": gt_str,
        "predicted": verdict,
        "match": match,
        "prompt_sent": prompt,
        "raw_response": raw,
        "llm_response_time": llm_response_time,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", choices=["claude", "kimi"], default="claude")
    parser.add_argument("--prompt", choices=["A", "B"], required=True)
    parser.add_argument("--n", type=lambda v: 10**9 if v.lower() == "all" else int(v), default=5)
    parser.add_argument("--dataset", type=str, default="CoCoClaNeL_experiments.json")
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()

    global _cost_tracker
    if args.llm == "claude" and _CostTracker is not None:
        _cost_tracker = _CostTracker()

    prompt_file = Path(__file__).parent / "prompts" / f"prompt_{args.prompt}.txt"
    system_prompt = prompt_file.read_text(encoding="utf-8").lstrip("﻿")

    dataset_path = DATA_DIR / args.dataset
    if not dataset_path.exists():
        print(f"ERROR: Dataset file not found: {dataset_path}")
        return
    examples = load_dataset(args.n, dataset_file=dataset_path)
    if not examples:
        print(f"ERROR: No examples found in {dataset_path}")
        return

    outputs_dir = Path(__file__).parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    n_tag = "all" if args.n >= 10**9 else args.n
    out_path = outputs_dir / f"outputs_{args.prompt}.jsonl"
    # Resume support: skip already-completed ids
    completed = {}
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    completed[rec["id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue
        if completed:
            print(f"Resuming: {len(completed)} already done")

    pending = [ex for ex in examples if ex["id"] not in completed]
    print(f"Loaded {len(examples)} examples | pending={len(pending)} | LLM={args.llm} | Prompt={args.prompt}")

    if pending:
        call_fn = LLM_DISPATCH[args.llm]
        write_lock = threading.Lock()
        counter = [len(completed)]
        total = len(examples)

        def append_record(record: dict):
            with write_lock:
                with open(out_path, "a") as f:
                    f.write(json.dumps(record) + "\n")

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = {
                executor.submit(
                    process_example, ex, system_prompt, call_fn,
                    args.model, args.sleep, counter, total, write_lock
                ): ex for ex in pending
            }
            for future in concurrent.futures.as_completed(futures):
                ex = futures[future]
                try:
                    record = future.result()
                    append_record(record)
                except Exception as e:
                    print(f"  FATAL ERROR for {ex['id']}: {e}")

    print(f"\nOutputs written to: {out_path}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
