#!/usr/bin/env python3
"""
Usage:
    python3 main.py <budget_usd> [dataset]
"""

import csv
import importlib.util
import json
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Paths — all relative to this file so the folder stays portable
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
PROMPTS_DIR  = BASE_DIR / "prompts"
OUTPUT_DIR   = BASE_DIR / "outputs"
DATASETS_DIR = BASE_DIR / ".." / "datasets" / "agora"
GT_DIR       = BASE_DIR / ".." / "approaches" / "agora_data" / "our_ground_truth"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FEASIBLE_AGORA_SERVICES = [
    "OMDB bySearch",
    "OMDB byIdOrTitle",
    "Yelp getBusinesses",
    "Hotel Search",
    "Spotify createPlaylist",
    "Spotify getAlbumTracks",
    "Spotify getArtistAlbums",
    "Marvel getComicById",
    "Youtube GetVideos",
]

PROMPTS          = ["A", "B"]
MODEL            = "claude-sonnet-4-6"
INPUT_PRICE      = 3.0    # USD per 1M input tokens
OUTPUT_PRICE     = 15.0   # USD per 1M output tokens
MAX_INPUT_TOKENS = 190_000  # safe threshold for 200K context window
CHARS_PER_TOKEN  = 3.5
SIZE_THRESHOLD   = 50_000   # bytes: outputs larger than this get their own file

csv.field_size_limit(10_000_000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)


def parse_query_params(query_str: str) -> dict:
    """Parse a semicolon-separated query string into a flat str→str dict."""
    result = {}
    if not query_str or not query_str.strip():
        return result
    for part in query_str.strip().split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[urllib.parse.unquote_plus(k.strip())] = urllib.parse.unquote_plus(v.strip())
    return result


def parse_json_response(text: str) -> dict:
    """Extract the first valid JSON object from LLM response text."""
    # 1. explicit ```json fence
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. scan { positions right-to-left
    decoder = json.JSONDecoder()
    for match in reversed(list(re.finditer(r"\{", text))):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
def load_prompt(letter: str) -> str:
    path = PROMPTS_DIR / f"prompt{letter}.py"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    spec   = importlib.util.spec_from_file_location("prompt_module", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable in {path}")
    return module.prompt


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def find_csv(service_dir: Path):
    for fname in service_dir.iterdir():
        if fname.suffix == ".csv":
            return fname
    return None


def load_dataset(dataset_name: str) -> list:
    if dataset_name != "agora":
        print(f"[!] Unknown dataset '{dataset_name}'. Only 'agora' is supported.")
        sys.exit(1)

    entries = []
    for service_name in FEASIBLE_AGORA_SERVICES:
        service_dir = DATASETS_DIR / service_name
        oas_path    = service_dir / "openapi.json"
        csv_path    = find_csv(service_dir)

        if not oas_path.exists():
            print(f"[!] OAS not found for '{service_name}', skipping.")
            continue
        if csv_path is None:
            print(f"[!] CSV not found for '{service_name}', skipping.")
            continue

        with open(oas_path, encoding="utf-8") as f:
            openapi_spec = json.load(f)

        rows_2xx = []
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = str(row.get("statusCode", "")).strip()
                if status.startswith("2") and row.get("responseBody", "").strip():
                    rows_2xx.append(row)

        if not rows_2xx:
            print(f"[!] No 2xx rows in CSV for '{service_name}', skipping.")
            continue

        entries.append({
            "service_name": service_name,
            "openapi_spec": openapi_spec,
            "rows_2xx":     rows_2xx,
        })

    return entries


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def sep_output_path(letter: str, service_name: str) -> Path:
    return OUTPUT_DIR / f"{safe_name(service_name)}_prompt{letter}.json"


def jsonl_output_path(letter: str) -> Path:
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


def token_log_path(letter: str) -> Path:
    return OUTPUT_DIR / f"tokens_{letter}.jsonl"


def is_done(service_name: str, letter: str) -> bool:
    """Return True if this (service, prompt) pair already has output."""
    # check separate file first
    if sep_output_path(letter, service_name).exists():
        return True
    # check JSONL
    jpath = jsonl_output_path(letter)
    if not jpath.exists():
        return False
    try:
        for line in jpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("service_name") == service_name and not rec.get("skipped"):
                    return True
    except (json.JSONDecodeError, OSError):
        pass
    return False


def get_pending(entries: list) -> tuple:
    """
    Returns (partial, untouched).
    partial   — services where some but not all prompts are done.
    untouched — services where no prompt has been run.
    """
    partial, untouched = [], []
    for entry in entries:
        done = [p for p in PROMPTS if is_done(entry["service_name"], p)]
        if done and len(done) < len(PROMPTS):
            partial.append(entry)
        elif not done:
            untouched.append(entry)
    return partial, untouched


def save_output(letter: str, service_name: str, payload: dict):
    """Save to JSONL or separate file depending on serialised size."""
    json_str = json.dumps(payload, indent=2)
    if len(json_str.encode("utf-8")) > SIZE_THRESHOLD:
        path = sep_output_path(letter, service_name)
        path.write_text(json_str, encoding="utf-8")
        print(f"    [+] Saved to {path.relative_to(BASE_DIR)}")
    else:
        jpath = jsonl_output_path(letter)
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        print(f"    [+] Appended to {jpath.relative_to(BASE_DIR)}")


def append_token_log(letter: str, entry: dict):
    path = token_log_path(letter)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Spending tracker
# ---------------------------------------------------------------------------
def get_total_spent() -> float:
    total = 0.0
    for letter in PROMPTS:
        path = token_log_path(letter)
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    total += r.get("cost_usd", {}).get("total_cost", 0.0)
        except (json.JSONDecodeError, OSError):
            pass
    return round(total, 6)


# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------
def run_entry(entry: dict, letter: str, system_prompt: str, client: anthropic.Anthropic):
    service_name = entry["service_name"]
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")

    row = random.choice(entry["rows_2xx"])
    request_info = parse_query_params(row.get("queryParameters", ""))
    try:
        response_body = json.loads(row.get("responseBody", "{}"))
    except (json.JSONDecodeError, TypeError):
        response_body = row.get("responseBody", "")

    user_message = json.dumps({
        "openapi_spec":  entry["openapi_spec"],
        "request_info":  request_info,
        "response_body": response_body,
    }, indent=2)

    # Token pre-flight check
    estimated = (len(system_prompt) + len(user_message)) / CHARS_PER_TOKEN
    if estimated > MAX_INPUT_TOKENS:
        print(f"    prompt {letter}: SKIPPED — estimated {int(estimated):,} tokens > {MAX_INPUT_TOKENS:,} limit")
        payload = {"service_name": service_name, "prompt": letter,
                   "timestamp": timestamp, "skipped": True, "reason": "too_large",
                   "estimated_tokens": int(estimated)}
        with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        return

    print(f"    prompt {letter}: calling {MODEL} for '{service_name}' ...")
    t_start       = time.time()
    response_text = ""

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for chunk in stream.text_stream:
                response_text += chunk
                print(chunk, end="", flush=True)
            print()
            usage = stream.get_final_message().usage
    except anthropic.BadRequestError as e:
        if "prompt is too long" in str(e).lower():
            print(f"    prompt {letter}: SKIPPED — {e}")
            payload = {"service_name": service_name, "prompt": letter,
                       "timestamp": timestamp, "skipped": True, "reason": "too_large"}
            with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
            return
        raise

    duration_seconds = round(time.time() - t_start, 3)

    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost   = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    result = parse_json_response(response_text)

    if result.get("response_property_constraints") is not None or \
       result.get("request_response_constraints") is not None:
        payload = {
            "service_name":                  service_name,
            "prompt":                        letter,
            "request_info":                  request_info,
            "response_body":                 response_body,
            "response_property_constraints": result.get("response_property_constraints", []),
            "request_response_constraints":  result.get("request_response_constraints", []),
        }
        save_output(letter, service_name, payload)
    else:
        raw_path = OUTPUT_DIR / f"{safe_name(service_name)}_prompt{letter}_raw_{timestamp}.txt"
        raw_path.write_text(response_text, encoding="utf-8")
        # still mark as done so resume logic skips it
        payload = {"service_name": service_name, "prompt": letter,
                   "timestamp": timestamp, "parse_failed": True,
                   "raw_file": raw_path.name}
        with open(jsonl_output_path(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        print(f"    [!] JSON parse failed. Raw saved: {raw_path.relative_to(BASE_DIR)}")

    append_token_log(letter, {
        "model":            MODEL,
        "prompt":           letter,
        "dataset":          "agora",
        "service_name":     service_name,
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
    print(f"    tokens: in={input_tokens} out={output_tokens}  "
          f"cost=${total_cost}  time={duration_seconds}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd> [dataset]")
        print("  dataset: agora (default)")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2].lower() if len(sys.argv) > 2 else "agora"

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load prompts ---
    prompts = {}
    for letter in PROMPTS:
        try:
            prompts[letter] = load_prompt(letter)
        except FileNotFoundError as e:
            print(f"[!] {e}")
            sys.exit(1)

    client = anthropic.Anthropic()

    # --- Preprocessing ---
    print("[*] Preprocessing ...")
    entries = load_dataset(dataset_name)
    print(f"    Dataset: {dataset_name}  ({len(entries)} feasible services)")
    for e in entries:
        done_prompts = [p for p in PROMPTS if is_done(e["service_name"], p)]
        status = f"done: {done_prompts}" if done_prompts else "not started"
        print(f"    - {e['service_name']}  ({len(e['rows_2xx'])} 2xx rows)  [{status}]")

    print(f"\n[*] Budget: ${budget:.4f}")

    # --- Budget loop ---
    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(entries)

        if not partial and not untouched:
            print("[*] All services processed. Stopping.")
            break

        if partial:
            entry = random.choice(partial)
            print(f"[*] Completing partial: {entry['service_name']}")
        else:
            entry = random.choice(untouched)
            print(f"[*] Selected new: {entry['service_name']}")

        for letter in PROMPTS:
            if is_done(entry["service_name"], letter):
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_entry(entry, letter, prompts[letter], client)

    # --- Summary ---
    final_spent = get_total_spent()
    partial, untouched = get_pending(entries)
    done_count = len(entries) - len(partial) - len(untouched)
    print(f"\n[*] Run complete.")
    print(f"    Total spent       : ${final_spent:.4f}")
    print(f"    Services fully done: {done_count} / {len(entries)}")


if __name__ == "__main__":
    main()
