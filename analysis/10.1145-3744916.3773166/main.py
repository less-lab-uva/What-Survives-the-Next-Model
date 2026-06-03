#!/usr/bin/env python3
"""
Runs the EchoFuzz LLM pipeline on D2 contracts using claude-sonnet-4-6.

Usage:
    python3 main.py <A|B>

Example:
    python3 main.py A
"""

import importlib.util
import json
import os
import re
import sys

import anthropic

DATASET_D2    = os.path.join(os.path.dirname(__file__), "dataset", "D2")
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), "output")
MODEL         = "claude-sonnet-4-6"
DURATION      = 300
ROUNDS        = 3


def load_prompt(letter: str) -> str:
    path = os.path.join(os.path.dirname(__file__), f"prompt{letter}.py")
    spec = importlib.util.spec_from_file_location("prompt_module", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.prompt


def build_user_message(sol_path: str) -> str:
    with open(sol_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    source_code = re.sub(
        r"[^\n]*(?:<report>|@vulnerable_at_lines)[^\n]*\n?", "", source_code
    )
    return json.dumps(
        {"source_code": source_code, "duration": DURATION, "rounds": ROUNDS},
        indent=2,
    )


def parse_json_response(text: str) -> dict:
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\s*```$", "", stripped.strip(), flags=re.MULTILINE)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def already_done(stem: str, letter: str) -> bool:
    return os.path.exists(os.path.join(OUTPUT_FOLDER, f"{stem}_prompt{letter}.json"))


def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
        print("Usage: python3 main.py <A|B>")
        sys.exit(1)

    letter = sys.argv[1].upper()
    system_prompt = load_prompt(letter)
    print(f"Prompt {letter} loaded.")

    sol_files = sorted(
        os.path.join(DATASET_D2, f)
        for f in os.listdir(DATASET_D2)
        if f.endswith(".sol")
    )
    print(f"Found {len(sol_files)} contracts in dataset/D2/")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set. Run 'source ~/.bashrc' first.")

    client = anthropic.Anthropic(api_key=api_key)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    total_in, total_out, total_cost = 0, 0, 0.0

    for i, sol_path in enumerate(sol_files, 1):
        stem = os.path.splitext(os.path.basename(sol_path))[0]
        out_path = os.path.join(OUTPUT_FOLDER, f"{stem}_prompt{letter}.json")

        if already_done(stem, letter):
            print(f"[{i}/{len(sol_files)}] {stem} — already done, skipping.")
            continue

        print(f"[{i}/{len(sol_files)}] {stem} ...")
        user_message = build_user_message(sol_path)
        response_text = ""

        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=32000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for chunk in stream.text_stream:
                    response_text += chunk
                    print(chunk, end="", flush=True)
                print()
                usage = stream.get_final_message().usage

            in_tok   = usage.input_tokens
            out_tok  = usage.output_tokens
            cost     = round(in_tok * 3 / 1_000_000 + out_tok * 15 / 1_000_000, 6)
            total_in  += in_tok
            total_out += out_tok
            total_cost = round(total_cost + cost, 6)
            print(f"    tokens: in={in_tok} out={out_tok}  cost=${cost}")

        except Exception as e:
            print(f"  ERROR on {stem}: {e}")
            continue

        result = parse_json_response(response_text)
        if result:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"    saved → {out_path}")
        else:
            raw_path = out_path.replace(".json", "_raw.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(response_text)
            print(f"    JSON parse failed — raw saved → {raw_path}")

    print(f"\nDone.")
    print(f"Total tokens: in={total_in}  out={total_out}  cost=${total_cost}")


if __name__ == "__main__":
    main()
