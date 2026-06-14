import argparse
import concurrent.futures
import json
import random
import re
import subprocess
import sys
import tempfile
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


MAX_CONTEXT_TOKENS = 200_000
CHARS_PER_TOKEN    = 3.5

LFTBENCH      = Path(__file__).parent / "dataset" / "lftbench"
SUBS_JSONL    = LFTBENCH / "metadata" / "cpp_submissions.jsonl"
PROBLEMS_JSON = LFTBENCH / "metadata" / "problems.json"


def load_problems_index():
    with open(PROBLEMS_JSON, encoding="utf-8") as f:
        return {p["problem_id"]: p for p in json.load(f)}


def compile_cpp(code: str, timeout: int = 15) -> Optional[Path]:
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", encoding="utf-8", delete=False) as f:
        f.write(code)
        src = Path(f.name)
    binary = src.with_suffix("")
    try:
        result = subprocess.run(
            ["g++", "-O2", "-o", str(binary), str(src)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0 and binary.exists():
            return binary
    except subprocess.TimeoutExpired:
        pass
    finally:
        src.unlink(missing_ok=True)
    return None


def run_binary(binary: Path, stdin_text: str, timeout: int = 5) -> Optional[str]:
    try:
        r = subprocess.run([str(binary)], input=stdin_text,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, Exception):
        return None


def scan_eligible(problems_index: dict) -> list:
    eligible = []
    with open(SUBS_JSONL) as f:
        for line in f:
            sub = json.loads(line.strip())
            pid = sub["problem_id"]
            if pid not in problems_index:
                continue
            prob = problems_index[pid]

            wa_path        = LFTBENCH / sub["wa_code_path"]
            orig_input_path = LFTBENCH / sub.get("original_test_input_path", "")
            ac_path        = LFTBENCH / sub.get("ac_code_path", "")
            if not wa_path.exists() or not orig_input_path.exists() or not ac_path.exists():
                continue

            wa_code       = wa_path.read_text(errors="replace")
            failing_input = orig_input_path.read_text(errors="replace")

            prompt_chars = len(prob["description"]) + len(wa_code) + len(failing_input)
            if prompt_chars / CHARS_PER_TOKEN > MAX_CONTEXT_TOKENS:
                continue

            eligible.append({
                "submission_id":       sub["submission_id"],
                "problem_id":          pid,
                "language":            sub.get("language", "C++"),
                "wa_path":             str(wa_path),
                "ac_path":             str(ac_path),
                "failing_input":       failing_input,
                "problem_description": prob["description"],
                "all_samples":         prob.get("samples", []),
            })
    return eligible


def compile_example(item: dict) -> dict:
    wa_code       = Path(item["wa_path"]).read_text(errors="replace")
    ac_code       = Path(item["ac_path"]).read_text(errors="replace")
    failing_input = item["failing_input"]

    wa_binary = compile_cpp(wa_code)
    if wa_binary is None:
        wa_output = "(compilation failed)"
    else:
        wa_output = run_binary(wa_binary, failing_input) or "(timeout)"
        wa_binary.unlink(missing_ok=True)

    ac_binary = compile_cpp(ac_code)
    if ac_binary is None:
        expected_output = "(ac compilation failed)"
    else:
        expected_output = run_binary(ac_binary, failing_input) or "(timeout)"
        ac_binary.unlink(missing_ok=True)

    return {
        "submission_id":       item["submission_id"],
        "problem_id":          item["problem_id"],
        "language":            item["language"],
        "problem_description": item["problem_description"],
        "wa_code":             wa_code,
        "failing_input":       failing_input,
        "wa_output":           wa_output,
        "expected_output":     expected_output,
        "all_samples":         item["all_samples"],
    }


def build_prompt(system_prompt: str, ex: dict) -> str:
    user_block = json.dumps({
        "problem_description": ex["problem_description"],
        "wa_code":             ex["wa_code"],
        "failing_input":       ex["failing_input"],
    }, indent=2)
    return f"{system_prompt}\n\n---\n\n{user_block}"


def parse_fixed_code(raw: str) -> Optional[str]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text).get("fixed_code")
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end]).get("fixed_code")
            except json.JSONDecodeError:
                pass
    matches = re.findall(r'"fixed_code"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL)
    if matches:
        try:
            return json.loads(f'"{matches[-1]}"')
        except json.JSONDecodeError:
            return matches[-1].replace("\\n", "\n").replace('\\"', '"')
    return None


_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(ex: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    prompt = build_prompt(system_prompt, ex)
    raw = ""
    llm_response_time = 0.0
    fixed_code = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _t0 = time.time()
            raw = call_fn(prompt, model=model_arg) if model_arg else call_fn(prompt)
            llm_response_time = time.time() - _t0
            fixed_code = parse_fixed_code(raw)
            break
        except Exception as e:
            err = str(e)
            if ("429" in err or "rate_limit" in err.lower()) and attempt < len(_RETRY_DELAYS):
                continue
            print(f"  ERROR [{ex['submission_id']} prompt={prompt_label}]: {e}")
            break

    if fixed_code is None:
        print(f"  WARNING [{ex['submission_id']} prompt={prompt_label}]: could not parse fixed_code")
        fixed_code = ""

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] {ex['problem_id']} / {ex['submission_id']} prompt={prompt_label}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "submission_id":   ex["submission_id"],
        "problem_id":      ex["problem_id"],
        "failing_input":   ex["failing_input"],
        "wa_output":       ex["wa_output"],
        "expected_output": ex["expected_output"],
        "all_samples":     ex["all_samples"],
        "fixed_code":      fixed_code,
        "prompt_sent":     prompt,
        "raw_response":    raw,
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
    for pl in prompt_labels:
        if out_paths[pl].exists():
            with open(out_paths[pl]) as f:
                for line in f:
                    try:
                        completed[pl].add(json.loads(line.strip())["submission_id"])
                    except (json.JSONDecodeError, KeyError):
                        continue
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    problems_index = load_problems_index()
    print("Scanning eligible submissions (context-window check, no compilation)...")
    all_eligible = scan_eligible(problems_index)
    print(f"Eligible pool: {len(all_eligible)} submissions fit within context window")

    all_done_ids = set().union(*completed.values())
    n_needed     = max(0, args.n - len(all_done_ids))
    pool         = [e for e in all_eligible if e["submission_id"] not in all_done_ids]
    rng          = random.Random(args.seed)
    selected     = rng.sample(pool, min(n_needed, len(pool)))

    print(f"Compiling {len(selected)} selected submissions...")
    examples = [compile_example(item) for item in selected]

    if not examples:
        print("No new examples to process.")
        return

    pending = [
        (ex, pl)
        for ex in examples
        for pl in prompt_labels
        if ex["submission_id"] not in completed[pl]
    ]

    n_done = len(all_done_ids) * len(prompt_labels)
    total  = (len(all_done_ids) + len(examples)) * len(prompt_labels)
    print(f"Selected {len(examples)} × {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}")

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
                    print(f"  FATAL ERROR for {ex['submission_id']} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
