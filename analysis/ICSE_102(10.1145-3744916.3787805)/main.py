import argparse
import concurrent.futures
import csv
import json
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


def call_claude(prompt: str, model: str = "claude-sonnet-4-6") -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    if _cost_tracker is not None:
        _cost_tracker.add(model, msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text


LLM_DISPATCH = {"claude": call_claude}


REPO_DIR      = Path(__file__).parent / "dataset" / "TestWeaver"
CODAMOSA_BASE = REPO_DIR / "codamosa" / "replication"
CODAMOSA_DIR  = CODAMOSA_BASE / "test-apps"
MODULES_CSV   = CODAMOSA_DIR / "cm_modules.csv"


def load_dataset(suite: str = "codamosa"):
    examples = []
    with open(MODULES_CSV) as f:
        reader = csv.reader(f)
        for d_str, m in reader:
            parts = m.split(".")
            candidates = [
                CODAMOSA_BASE / d_str / Path(*parts).with_suffix(".py"),
                CODAMOSA_BASE / d_str / Path(*parts[1:]).with_suffix(".py") if len(parts) > 1 else None,
            ]
            source_path = None
            for c in candidates:
                if c and c.exists():
                    source_path = c
                    break
            if source_path is None:
                continue
            code = source_path.read_text(errors="replace")
            examples.append({
                "suite":           suite,
                "modules_csv_row": {"d": d_str, "m": m},
                "source_file":     str(source_path.relative_to(REPO_DIR)),
                "source_file_abs": str(source_path),
                "d":               d_str,
                "m":               m,
                "stem":            source_path.stem,
                "code":            code,
            })
    return examples


def build_prompt(system_prompt: str, example: dict) -> str:
    user_block = json.dumps({
        "m":    example["m"],
        "code": example["code"],
    }, indent=2)
    return f"{system_prompt}\n\n---\n\n{user_block}"


def parse_partial_tests(text: str) -> Optional[list]:
    tests_key = re.search(r'"tests"\s*:', text)
    if not tests_key:
        return None

    array_start = text.find("[", tests_key.end())
    if array_start == -1:
        return None

    decoder = json.JSONDecoder()
    tests = []
    i = array_start + 1
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1

        if text.startswith("\\n", i):
            i += 2
            continue

        if i >= len(text) or text[i] == "]":
            break
        if text[i] != '"':
            break

        try:
            test, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break

        if not isinstance(test, str):
            break
        tests.append(test)
        i = end

    return tests or None


def parse_response(raw: str) -> Optional[dict]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "tests" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end])
            if isinstance(obj, dict) and "tests" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    m = re.search(r'"tests"\s*:\s*(\[.*?\])', text, re.DOTALL)
    if m:
        try:
            tests = json.loads(m.group(1))
            return {"tests": tests, "code": "", "task_num": "", "task_title": ""}
        except json.JSONDecodeError:
            pass
    tests = parse_partial_tests(text)
    if tests:
        return {"tests": tests, "code": "", "task_num": "", "task_title": ""}
    return None


_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(ex: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    prompt = build_prompt(system_prompt, ex)
    raw = ""
    llm_response_time = 0.0
    parsed = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            parsed = parse_response(raw)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [{ex['m']} prompt={prompt_label}]: {e}")
            break

    if parsed is None:
        print(f"  WARNING [{ex['m']} prompt={prompt_label}]: could not parse response")
        parsed = {"tests": []}

    tests = parsed.get("tests", [])

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] {ex['m']} prompt={prompt_label} | Generated {len(tests)} test(s)")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "id":               ex["m"],
        "source_file":      ex["source_file"],
        "source_file_abs":  ex["source_file_abs"],
        "d":                ex["d"],
        "tests":            tests,
        "n_tests_generated": len(tests),
        "prompt_sent":      prompt,
        "raw_response":     raw,
        "llm_response_time": llm_response_time,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm",     choices=["claude"], default="claude")
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
        pf = Path(__file__).parent / "prompts" / f"prompt_{pl}.txt"
        system_prompts[pl] = pf.read_text(encoding="utf-8").lstrip("﻿")

    outputs_dir = Path(__file__).parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {pl: outputs_dir / f"outputs_{pl}.jsonl" for pl in prompt_labels}
    call_fn = LLM_DISPATCH[args.llm]

    completed = {pl: set() for pl in prompt_labels}
    completed_order = []
    seen_completed = set()
    for pl in prompt_labels:
        if out_paths[pl].exists():
            with open(out_paths[pl]) as f:
                for line in f:
                    try:
                        rec_id = json.loads(line.strip())["id"]
                    except (json.JSONDecodeError, KeyError):
                        continue
                    completed[pl].add(rec_id)
                    if rec_id not in seen_completed:
                        completed_order.append(rec_id)
                        seen_completed.add(rec_id)
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    all_examples = load_dataset()
    if not all_examples:
        print(f"ERROR: No examples found. Check {MODULES_CSV}")
        return

    examples_by_id = {ex["m"]: ex for ex in all_examples}
    target_ids = [rec_id for rec_id in completed_order if rec_id in examples_by_id]
    n_needed = max(0, args.n - len(target_ids))
    pool = [ex for ex in all_examples if ex["m"] not in seen_completed]
    rng = random.Random(args.seed)
    sampled = rng.sample(pool, min(n_needed, len(pool)))
    target_ids.extend(ex["m"] for ex in sampled)
    examples = [examples_by_id[rec_id] for rec_id in target_ids[:args.n]]

    pending = [
        (ex, pl)
        for ex in examples
        for pl in prompt_labels
        if ex["m"] not in completed[pl]
    ]

    total = len(examples) * len(prompt_labels)
    n_done = total - len(pending)
    print(f"Selected {len(examples)} examples × {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}")

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
                    print(f"  FATAL ERROR for {ex['m']} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
