#!/usr/bin/env python3
"""
Randomly samples services from the AGORA+ benchmark and runs the constraint
mining pipeline (Prompt A and Prompt B) until the budget is exhausted.

Only services whose OpenAPI spec fits within Opus's 200K-token context window
are eligible. The two oversized GitHub specs (~400K tokens each) are excluded.

Usage:
    python3 run_random.py <budget_usd> [dataset_name]

Dataset names: agora (default, only supported option)

Example:
    python3 run_random.py 10.0 agora
"""

import anthropic
import csv
import importlib.util
import json
import os
import random
import re
import sys
import urllib.parse
from datetime import datetime

csv.field_size_limit(10_000_000)

RBCTEST_ROOT  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER = os.path.join(RBCTEST_ROOT, "output")
PROMPTS       = ["A", "B"]

# Services whose OAS fits in the model's context window.
# Github CreateOrganizationRepository (~403K tokens) and
# Github GetOrganizationRepositories (~402K tokens) are excluded.
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

AGORA_DATASET_DIR = os.path.join(RBCTEST_ROOT, "datasets", "agora")


# ── dataset ───────────────────────────────────────────────────────────────────

def find_csv(service_dir):
    for fname in os.listdir(service_dir):
        if fname.endswith(".csv"):
            return os.path.join(service_dir, fname)
    return None


def load_dataset(dataset_name):
    if dataset_name != "agora":
        print(f"[!] Unknown dataset '{dataset_name}'. Only 'agora' is supported.")
        sys.exit(1)

    entries = []
    for service_name in FEASIBLE_AGORA_SERVICES:
        service_dir = os.path.join(AGORA_DATASET_DIR, service_name)
        oas_path    = os.path.join(service_dir, "openapi.json")
        csv_path    = find_csv(service_dir)

        if not os.path.exists(oas_path):
            print(f"[!] OAS not found for '{service_name}', skipping.")
            continue
        if not csv_path:
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
            print(f"[!] No 2xx responses in CSV for '{service_name}', skipping.")
            continue

        entries.append({
            "service_name": service_name,
            "openapi_spec": openapi_spec,
            "rows_2xx":     rows_2xx,
        })

    return entries


# ── output ────────────────────────────────────────────────────────────────────

def safe_name(name):
    return re.sub(r"[^\w\-]", "_", name)


def output_json_path(prompt_letter, service_name):
    return os.path.join(
        OUTPUT_FOLDER,
        f"agora_{safe_name(service_name)}_prompt{prompt_letter}.json",
    )


def is_completed(prompt_letter, service_name):
    path = output_json_path(prompt_letter, service_name)
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return bool(
            data.get("response_property_constraints") or
            data.get("request_response_constraints")
        )
    except (json.JSONDecodeError, KeyError):
        return False


def save_result(service_name, prompt_letter, result, raw_response, request_info, response_body):
    path = output_json_path(prompt_letter, service_name)
    payload = {
        "service":                       service_name,
        "prompt":                        prompt_letter,
        "request_info":                  request_info,
        "response_body":                 response_body,
        "response_property_constraints": result.get("response_property_constraints", []),
        "request_response_constraints":  result.get("request_response_constraints", []),
        "raw_response":                  raw_response,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ── budget ────────────────────────────────────────────────────────────────────

def get_total_spent():
    total = 0.0
    if not os.path.exists(OUTPUT_FOLDER):
        return total
    for fname in os.listdir(OUTPUT_FOLDER):
        if fname.startswith("tokens_prompt") and fname.endswith(".json"):
            fpath = os.path.join(OUTPUT_FOLDER, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    records = json.load(f)
                if isinstance(records, list):
                    total += sum(
                        r.get("cost_usd", {}).get("total_cost", 0.0) for r in records
                    )
            except (json.JSONDecodeError, KeyError):
                pass
    return round(total, 6)


# ── pending entries ───────────────────────────────────────────────────────────

def get_pending(entries):
    return [
        e for e in entries
        if not all(is_completed(p, e["service_name"]) for p in PROMPTS)
    ]


# ── API call ──────────────────────────────────────────────────────────────────

def load_prompt(prompt_letter):
    prompt_file = os.path.join(RBCTEST_ROOT, f"prompt{prompt_letter}.py")
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    spec = importlib.util.spec_from_file_location("prompt_module", prompt_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable in {prompt_file}")
    return module.prompt


def parse_query_params(query_str):
    """Parse a semicolon-separated query string into a flat str→str dict."""
    if not query_str or not query_str.strip():
        return {}
    result = {}
    for part in query_str.strip().split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            result[urllib.parse.unquote_plus(k.strip())] = urllib.parse.unquote_plus(v.strip())
    return result


def parse_json_response(response_text):
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


def run_entry(entry, prompt_letter):
    system_prompt = load_prompt(prompt_letter)
    service_name  = entry["service_name"]

    row = random.choice(entry["rows_2xx"])
    request_info = parse_query_params(row.get("queryParameters", ""))
    response_body_raw = row.get("responseBody", "{}")
    try:
        response_body = json.loads(response_body_raw)
    except (json.JSONDecodeError, TypeError):
        response_body = response_body_raw

    user_message = json.dumps({
        "openapi_spec":  entry["openapi_spec"],
        "request_info":  request_info,
        "response_body": response_body,
    }, indent=2)

    client        = anthropic.Anthropic()
    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    response_text = ""

    print(f"    prompt {prompt_letter}: calling Sonnet for '{service_name}' ...")

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=32000,
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

    if result.get("response_property_constraints") or result.get("request_response_constraints"):
        save_result(service_name, prompt_letter, result, response_text, request_info, response_body)
        print(f"    [+] Saved to {output_json_path(prompt_letter, service_name)}")
    else:
        raw_path = os.path.join(
            OUTPUT_FOLDER,
            f"raw_agora_{safe_name(service_name)}_prompt{prompt_letter}_{timestamp}.txt",
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(response_text)
        print(f"    [!] JSON parse failed. Raw saved: {raw_path}")

    token_file = os.path.join(OUTPUT_FOLDER, f"tokens_prompt{prompt_letter}.json")
    record = {
        "model":        "claude-sonnet-4-6",
        "prompt":       prompt_letter,
        "dataset":      "agora",
        "service_name": service_name,
        "timestamp":    timestamp,
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
        print("Usage: python3 run_random.py <budget_usd> [dataset_name]")
        print("Dataset names: agora")
        sys.exit(1)

    budget       = float(sys.argv[1])
    dataset_name = sys.argv[2].lower() if len(sys.argv) > 2 else "agora"
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    entries = load_dataset(dataset_name)
    print(f"[*] Dataset: {dataset_name}  ({len(entries)} feasible services)")
    print(f"[*] Budget: ${budget:.4f}")
    for e in entries:
        print(f"    - {e['service_name']}  ({len(e['rows_2xx'])} 2xx responses available)")

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        pool = get_pending(entries)
        if not pool:
            print("[*] All services processed. Stopping.")
            break

        entry = random.choice(pool)
        print(f"[*] Selected: {entry['service_name']}")

        for letter in PROMPTS:
            if is_completed(letter, entry["service_name"]):
                print(f"    prompt {letter}: already exists, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            run_entry(entry, letter)


if __name__ == "__main__":
    main()
