import argparse
import concurrent.futures
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
        model=model, max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    if _cost_tracker is not None:
        _cost_tracker.add(model, msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text


LLM_DISPATCH = {"claude": call_claude}


DATA_DIR = Path(__file__).parent / "dataset"


def load_test_cases(datasets: list) -> list:
    cases = []
    for ds in datasets:
        path = DATA_DIR / ds / "test.jsonl"
        if not path.exists():
            print(f"[WARN] Dataset {ds} not found at {path}")
            continue
        with open(path) as f:
            ds_cases = [json.loads(line) for line in f]
        for c in ds_cases:
            c["_dataset"] = ds
        cases.extend(ds_cases)
        print(f"  Dataset {ds}: {len(ds_cases)} test cases loaded")
    return cases


def build_prompt(system_prompt: str, case: dict) -> str:
    return f"{system_prompt}\n\n---\n\n{case['problem']}"


def parse_answer(raw: str) -> Optional[dict]:
    text = raw.strip()
    m = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    text = text.replace("```json", "").replace("```", "").strip()

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", text[idx:])
                obj = json.loads(fixed)
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict) and "rank_list" in obj:
            return obj
    return None


_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(case: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    ds = case["_dataset"]
    sol = json.loads(case["solution"])
    gt_root_causes = sol["root_cause"]

    prompt = build_prompt(system_prompt, case)
    raw = ""
    llm_response_time = 0.0
    predicted = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            predicted = parse_answer(raw)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [{ds}/{case.get('case_idx')} prompt={prompt_label}]: {e}")
            break

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] Dataset={ds} case_idx={case.get('case_idx','?')} prompt={prompt_label} | GT={gt_root_causes} | parsed={'yes' if predicted else 'no'}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "dataset":        ds,
        "case_idx":       case.get("case_idx"),
        "ground_truth":   gt_root_causes,
        "predicted":      predicted,
        "prompt_sent":    prompt,
        "raw_response":   raw,
        "llm_response_time": llm_response_time,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm",      choices=["claude"], default="claude")
    parser.add_argument("--prompt",   choices=["A", "B", "both"], required=True)
    parser.add_argument("--n",        type=int, default=5)
    parser.add_argument("--datasets", type=str, default="A,B,C,D")
    parser.add_argument("--sleep",    type=float, default=2.0)
    parser.add_argument("--model",    type=str, default=None)
    parser.add_argument("--threads",  type=int, default=8)
    parser.add_argument("--seed",     type=int, default=None)
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
    for pl in prompt_labels:
        if out_paths[pl].exists():
            with open(out_paths[pl]) as f:
                for line in f:
                    try:
                        rec = json.loads(line.strip())
                        completed[pl].add(f"{rec['dataset']}_{rec['case_idx']}")
                    except (json.JSONDecodeError, KeyError):
                        continue
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    datasets = [d.strip().upper() for d in args.datasets.split(",")]
    print(f"Loading test cases from datasets: {datasets}")
    all_cases = load_test_cases(datasets)
    if not all_cases:
        print("ERROR: No test cases found.")
        return

    def case_id(c):
        return f"{c['_dataset']}_{c.get('case_idx')}"

    all_done_ids = set().union(*completed.values())
    n_needed     = max(0, args.n - len(all_done_ids))
    pool         = [c for c in all_cases if case_id(c) not in all_done_ids]
    rng          = random.Random(args.seed)
    cases        = rng.sample(pool, min(n_needed, len(pool)))

    pending = [
        (case, pl)
        for case in cases
        for pl in prompt_labels
        if case_id(case) not in completed[pl]
    ]

    n_done = sum(len(v) for v in completed.values())
    total  = (n_done + len(cases)) * len(prompt_labels)
    print(f"Selected {len(cases)} cases × {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}")

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
                    process_example, case, pl, system_prompts[pl], call_fn,
                    args.model, args.sleep, counter, total, counter_lock
                ): (case, pl) for case, pl in pending
            }
            for future in concurrent.futures.as_completed(futures):
                case, pl = futures[future]
                try:
                    record = future.result()
                    append_record(record, pl)
                except Exception as e:
                    print(f"  FATAL ERROR for {case['_dataset']}/{case.get('case_idx')} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
