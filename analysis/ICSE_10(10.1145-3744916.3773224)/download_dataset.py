#!/usr/bin/env python3
"""
Downloads CoderEval4Python.json from the CoderEval GitHub repository and
processes it into input/input_codereval.jsonl, the format expected by main.py.

Dataset source : https://github.com/CoderEval/CoderEval
Processing logic adapted from : https://github.com/Elendil3703/AllianceCoder
  (input/handle_input+CoderEval+Context.py)

Usage:
    python3 download_dataset.py
"""

import json
import os
import re
import urllib.request

PROJECT_FOLDER = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER   = os.path.join(PROJECT_FOLDER, "input")
RAW_JSON       = os.path.join(INPUT_FOLDER, "CoderEval4Python.json")
OUTPUT_JSONL   = os.path.join(INPUT_FOLDER, "input_codereval.jsonl")

# Shared raw JSON downloaded for the original with_sonnet run.
# Use this copy if present so the processed JSONL is byte-for-byte
# identical to what with_sonnet was evaluated on.
SHARED_RAW_JSON = os.path.join(PROJECT_FOLDER, "..", "input", "CoderEval4Python.json")

DATASET_URL = (
    "https://raw.githubusercontent.com/CoderEval/CoderEval/main/CoderEval4Python.json"
)


def download():
    import shutil
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    shared = os.path.normpath(SHARED_RAW_JSON)
    if os.path.exists(shared):
        shutil.copy2(shared, RAW_JSON)
        print(f"[*] Copied shared CoderEval4Python.json from {shared}")
        return
    print(f"[*] Downloading CoderEval4Python.json from CoderEval/CoderEval ...")
    urllib.request.urlretrieve(DATASET_URL, RAW_JSON)
    size_mb = os.path.getsize(RAW_JSON) / 1_048_576
    print(f"[+] Downloaded ({size_mb:.1f} MB) -> {RAW_JSON}")


def process():
    print(f"[*] Processing {RAW_JSON} ...")
    with open(RAW_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data["RECORDS"]
    task_counter = 0
    written = 0

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as fout:
        for record in records:
            code_str = record["code"]

            # Extract function signature + docstring (everything up to end of first docstring)
            triple_quote_positions = [m.start() for m in re.finditer(r'"""', code_str)]
            if len(triple_quote_positions) >= 2:
                prompt = code_str[: triple_quote_positions[1]] + '"""'
            else:
                prompt = code_str + '"""'

            file_path    = record["file_path"]
            fpath_tuple  = file_path.split("/")
            file_content = record["file_content"]

            # Capture only the file content that appears before the target function
            code_pos     = file_content.find(record["code"])
            current_file = file_content[:code_pos] if code_pos != -1 else file_content

            out_record = {
                "prompt": prompt,
                "current_file": current_file,
                "metadata": {
                    "ground_truth":         code_str,
                    "fpath_tuple":          fpath_tuple,
                    "function_name":        record["name"],
                    "lineno":               int(record["lineno"]),
                    "context_start_lineno": 0,
                    "_id":                  record["_id"],
                    "task_id":              f"{fpath_tuple[0]}/id{task_counter}",
                },
            }
            fout.write(json.dumps(out_record, ensure_ascii=False) + "\n")
            task_counter += 1
            written += 1

    print(f"[+] Wrote {written} tasks -> {OUTPUT_JSONL}")


def main():
    download()
    process()
    print("[*] Dataset ready. You can now run: python3 main.py <budget_usd>")


if __name__ == "__main__":
    main()
