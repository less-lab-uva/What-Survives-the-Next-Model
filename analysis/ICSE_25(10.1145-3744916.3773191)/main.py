import argparse
import concurrent.futures
import json
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
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    if _cost_tracker is not None:
        _cost_tracker.add(model, msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text


LLM_DISPATCH = {"claude": call_claude}


DATASET_FILE = Path(__file__).parent / "dataset" / "test.jsonl"


def load_dataset(n: int):
    examples = []
    with open(DATASET_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            patch = item.get("patch", "")
            if not patch:
                continue
            examples.append({
                "patch": patch,
                "ref_security_type": item.get("security_type", ""),
                "ref_description":   item.get("description", ""),
                "ref_impact":        item.get("impact", ""),
                "ref_advice":        item.get("advice", ""),
            })
            if len(examples) >= n:
                break
    return examples


def build_prompt(system_prompt: str, example: dict) -> str:
    return f"{system_prompt}\n\n---\n\npatch:\n{example['patch']}"


def parse_review(raw: str) -> Optional[dict]:
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


_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(orig_i: int, ex: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    prompt = build_prompt(system_prompt, ex)
    raw = ""
    llm_response_time = 0.0
    review = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            review = parse_review(raw)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [idx={orig_i} prompt={prompt_label}]: {e}")
            break

    if review is None:
        print(f"  WARNING [idx={orig_i} prompt={prompt_label}]: could not parse review")
        review = {"Security Type": "Non-Issue", "Description": "", "Impact": "", "Advice": ""}

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] idx={orig_i} prompt={prompt_label} | Security Type: {review.get('Security Type', '')}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "_idx": orig_i,
        "patch": ex["patch"],
        "predicted": review,
        "reference": {
            "security_type": ex["ref_security_type"],
            "description":   ex["ref_description"],
            "impact":        ex["ref_impact"],
            "advice":        ex["ref_advice"],
        },
        "prompt_sent":  prompt,
        "raw_response": raw,
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
    args = parser.parse_args()

    global _cost_tracker
    if args.llm == "claude" and _CostTracker is not None:
        _cost_tracker = _CostTracker()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]

    system_prompts = {}
    for pl in prompt_labels:
        pf = Path(__file__).parent / "prompts" / f"prompt_{pl}.txt"
        system_prompts[pl] = pf.read_text(encoding="utf-8").lstrip("﻿")

    examples = load_dataset(args.n)
    if not examples:
        print(f"ERROR: No examples found in {DATASET_FILE}")
        return

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
                        completed[pl].add(json.loads(line.strip())["_idx"])
                    except (json.JSONDecodeError, KeyError):
                        continue
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    pending = [
        (i, ex, pl)
        for i, ex in enumerate(examples)
        for pl in prompt_labels
        if i not in completed[pl]
    ]

    n_done = sum(len(v) for v in completed.values())
    total = len(examples) * len(prompt_labels)
    print(f"Loaded {len(examples)} examples × {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}")

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
                    process_example, orig_i, ex, pl, system_prompts[pl], call_fn,
                    args.model, args.sleep, counter, total, counter_lock
                ): (orig_i, ex, pl) for orig_i, ex, pl in pending
            }
            for future in concurrent.futures.as_completed(futures):
                orig_i, ex, pl = futures[future]
                try:
                    record = future.result()
                    append_record(record, pl)
                except Exception as e:
                    print(f"  FATAL ERROR for idx={orig_i} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
