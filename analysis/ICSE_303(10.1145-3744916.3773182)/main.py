"""
Regression bug detection inference script.
Calls the LLM for each commit and writes per-example records to outputs/.

Usage:
  python main.py --llm claude|kimi --prompt A|B|both --n N [--model MODEL] [--sleep S] [--threads T]

Output:
  outputs/outputs_{llm}_prompt{P}_n{N}.jsonl
  Each line: {owner_repo, sha, split, true_label, pred_label, skipped,
              commit_message, diff_chars, raw_response, predicted}
"""

import argparse
import concurrent.futures
import csv
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
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

DATASET_DIR   = Path(__file__).parent / "dataset"
BICS_CSV      = DATASET_DIR / "280BICs.csv"
BFCS_CSV      = DATASET_DIR / "2800BFCs.csv"
DATASET_JSONL = DATASET_DIR / "dataset.jsonl"
MAX_DIFF_CHARS = 12000


def fetch_commit_diff(owner_repo: str, sha: str, retries: int = 3) -> Optional[tuple]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    url = f"https://api.github.com/repos/{owner_repo}/commits/{sha}"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            commit_message = data.get("commit", {}).get("message", "")
            files = data.get("files", [])
            diff_parts = []
            for f in files:
                filename = f.get("filename", "")
                patch = f.get("patch", "")
                if patch:
                    diff_parts.append(f"--- a/{filename}\n+++ b/{filename}\n{patch}")
            diff = "\n".join(diff_parts)
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + "\n...[diff truncated]..."
            return commit_message, diff
        except urllib.error.HTTPError as e:
            if e.code == 403:
                time.sleep(60)
            elif e.code == 404:
                return None
            else:
                if attempt < retries:
                    time.sleep(5 * attempt)
        except Exception as e:
            print(f"    Error fetching {owner_repo}/{sha}: {e}")
            if attempt < retries:
                time.sleep(5 * attempt)
    return None


def load_dataset() -> list:
    if DATASET_JSONL.exists():
        return _load_from_jsonl()
    print(f"[INFO] {DATASET_JSONL} not found — diffs will be fetched from GitHub at runtime.")
    print("[INFO] Run `python3 fetch_dataset.py` first to pre-build the dataset (recommended).")
    return _load_from_csvs()


def _load_from_jsonl() -> list:
    samples = []
    with open(DATASET_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("skipped"):
                continue
            samples.append({
                "owner_repo":     rec["owner_repo"],
                "sha":            rec["sha"],
                "label":          rec["label"],
                "split":          "BIC" if rec["label"] == 1 else "BFC",
                "commit_message": rec.get("commit_message", ""),
                "diff":           rec.get("diff", ""),
                "_prefetched":    True,
            })
    pos = sum(1 for s in samples if s["label"] == 1)
    print(f"[INFO] Loaded from dataset.jsonl: {pos} BIC + {len(samples) - pos} BFC")
    return samples


def _load_from_csvs() -> list:
    samples = []
    with open(BICS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            samples.append({"owner_repo": row["Project"], "sha": row["BIC"],
                             "label": 1, "split": "BIC", "_prefetched": False})
    with open(BFCS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            samples.append({"owner_repo": row["project"], "sha": row["commit_hash"],
                             "label": 0, "split": "BFC", "_prefetched": False})
    return samples

# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(system_prompt: str, commit_message: str, diff: str) -> str:
    user_block = json.dumps({"commit_message": commit_message, "diff": diff}, indent=2)
    return f"{system_prompt}\n\n---\n\n{user_block}"

# ── Output parser ─────────────────────────────────────────────────────────────

def parse_prediction(raw: str) -> Optional[dict]:
    text = raw.strip().replace("```json", "").replace("```", "").strip()
    # Scan flat (non-nested) {...} blocks from last to first, since the final
    # answer comes after any reasoning/code snippets that may also contain braces.
    for candidate in reversed(re.findall(r'\{[^{}]*\}', text)):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if "label" in obj:
            return obj
    if re.search(r'"label"\s*:\s*"Yes"', raw, re.IGNORECASE):
        return {"label": "Yes", "explanation": "(parsed from text)"}
    if re.search(r'"label"\s*:\s*"No"', raw, re.IGNORECASE):
        return {"label": "No", "explanation": "(parsed from text)"}
    match = re.search(r'"label"\s*:\s*(\d+)', raw)
    if match:
        return {"label": int(match.group(1))}
    return None


def label_to_pred(label) -> int:
    """Normalize a parsed `label` value (int per the prompt spec, or the
    "Yes"/"No" strings produced by parse_prediction's regex fallback) to
    0/1, or -1 if it can't be interpreted as a binary label."""
    if isinstance(label, bool):
        return int(label)
    if isinstance(label, (int, float)):
        return 1 if int(label) == 1 else 0
    if isinstance(label, str):
        s = label.strip().lower()
        if s in ("1", "yes", "true"):
            return 1
        if s in ("0", "no", "false"):
            return 0
    return -1

# ── Per-example worker ────────────────────────────────────────────────────────

_RETRY_DELAYS = [5, 15, 30, 60]


def process_example(sample: dict, prompt_label: str, system_prompt: str,
                    call_fn, model_arg, sleep_sec: float,
                    counter: list, total: int, lock: threading.Lock) -> dict:
    owner_repo = sample["owner_repo"]
    sha        = sample["sha"]
    true_label = sample["label"]
    split      = sample["split"]

    if sample.get("_prefetched"):
        commit_message = sample["commit_message"]
        diff = sample["diff"]
    else:
        result = fetch_commit_diff(owner_repo, sha)
        if result is None:
            with lock:
                counter[0] += 1
                idx = counter[0]
            print(f"[{idx}/{total}] {split} | {owner_repo}@{sha[:8]} prompt={prompt_label} | SKIP: could not fetch diff")
            return {
                "owner_repo": owner_repo, "sha": sha, "split": split,
                "true_label": true_label, "pred_label": -1,
                "skipped": True, "skip_reason": "fetch_failed",
                "prompt_sent": "", "raw_response": "", "predicted": None,
                "commit_message": "", "diff_chars": 0,
            }
        commit_message, diff = result

    prompt = build_prompt(system_prompt, commit_message, diff)
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
            predicted = parse_prediction(raw)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                if attempt < len(_RETRY_DELAYS):
                    continue
            print(f"  ERROR [{owner_repo}@{sha[:8]} prompt={prompt_label}]: {e}")
            break

    if predicted is None:
        pred_label = -1
    else:
        pred_label = label_to_pred(predicted.get("label"))

    correct = "✓" if pred_label == true_label else ("✗" if pred_label != -1 else "?")
    pred_str = "Yes" if pred_label == 1 else ("No" if pred_label == 0 else "?")
    true_str = "Yes" if true_label == 1 else "No"

    with lock:
        counter[0] += 1
        idx = counter[0]
    print(f"[{idx}/{total}] {split} | {owner_repo}@{sha[:8]} prompt={prompt_label} | pred={pred_str} true={true_str} {correct}")

    if sleep_sec > 0:
        time.sleep(sleep_sec)

    return {
        "owner_repo":     owner_repo,
        "sha":            sha,
        "split":          split,
        "true_label":     true_label,
        "pred_label":     pred_label,
        "skipped":        False,
        "commit_message": commit_message,
        "diff_chars":     len(diff),
        "prompt_sent":    prompt,
        "raw_response":   raw,
        "predicted":      predicted,
        "llm_response_time": llm_response_time,
    }

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
        pf = Path(__file__).parent / "prompts" / f"prompt_{pl}.txt"
        system_prompts[pl] = pf.read_text(encoding="utf-8").lstrip("﻿")

    if not os.environ.get("GITHUB_TOKEN"):
        print("[WARN] GITHUB_TOKEN not set. GitHub API rate limit: 60 req/hour.")

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
                        completed[pl].add(f"{rec['owner_repo']}@{rec['sha']}")
                    except (json.JSONDecodeError, KeyError):
                        continue
            if completed[pl]:
                print(f"Resuming prompt {pl}: {len(completed[pl])} already done")

    print("Loading full dataset...")
    all_samples = load_dataset()
    print(f"Full pool: {len(all_samples)} samples")

    def sample_id(s):
        return f"{s['owner_repo']}@{s['sha']}"

    seen_ids       = set().union(*completed.values())
    fully_done_ids = set.intersection(*completed.values()) if completed else set()
    partial_ids    = seen_ids - fully_done_ids
    n_needed       = max(0, args.n - len(fully_done_ids) - len(partial_ids))
    pool           = [s for s in all_samples if sample_id(s) not in seen_ids]
    rng            = random.Random(args.seed)
    new_samples    = rng.sample(pool, min(n_needed, len(pool)))
    partial_samples = [s for s in all_samples if sample_id(s) in partial_ids]
    samples        = partial_samples + new_samples

    pending = [
        (sample, pl)
        for sample in samples
        for pl in prompt_labels
        if sample_id(sample) not in completed[pl]
    ]

    n_done = sum(len(v) for v in completed.values())
    total  = n_done + len(pending)
    print(f"Selected {len(samples)} samples × {len(prompt_labels)} prompt(s) | {len(pending)} pending | LLM={args.llm}")

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
                    process_example, sample, pl, system_prompts[pl], call_fn,
                    args.model, args.sleep, counter, total, counter_lock
                ): (sample, pl) for sample, pl in pending
            }
            for future in concurrent.futures.as_completed(futures):
                sample, pl = futures[future]
                try:
                    record = future.result()
                    append_record(record, pl)
                except Exception as e:
                    print(f"  FATAL ERROR for {sample['owner_repo']}@{sample['sha'][:8]} prompt={pl}: {e}")

    for pl in prompt_labels:
        print(f"\nOutputs written to: {out_paths[pl]}")
    if _cost_tracker is not None:
        print(f"\n{_cost_tracker.summary()}")


if __name__ == "__main__":
    main()
