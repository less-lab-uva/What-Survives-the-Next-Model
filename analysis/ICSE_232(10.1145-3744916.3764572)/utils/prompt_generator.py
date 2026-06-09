"""Generate prompts/prompt_A.txt and prompt_B.txt from the paper + meta_prompt.txt.

Sends the paper PDF (as a document block) plus prompts/meta_prompt.txt to Claude, which
returns PROMPT A (black-box) and PROMPT B (informed); both are extracted and written out.

Like main.py: fixed paths, preconditions checked up front, hard-abort on anything not set
up, and it will NOT overwrite existing prompt files.

Run from the analysis directory:  python3 utils/prompt_generator.py
"""

import os
import re
import sys
import base64
import anthropic

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64000

PDF = "paper.pdf"
META_PROMPT = "prompts/meta_prompt.txt"
PROMPT_A = "prompts/prompt_A.txt"
PROMPT_B = "prompts/prompt_B.txt"
RAW_OUTPUT = "prompts/raw_output.txt"

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
if not os.path.exists(PDF):
    sys.exit(f"ABORT: missing {PDF}")
if not os.path.exists(META_PROMPT):
    sys.exit(f"ABORT: missing {META_PROMPT}")
if os.path.exists(PROMPT_A):
    sys.exit(f"ABORT: output already exists: {PROMPT_A}")
if os.path.exists(PROMPT_B):
    sys.exit(f"ABORT: output already exists: {PROMPT_B}")
if os.path.exists(RAW_OUTPUT):
    sys.exit(f"ABORT: output already exists: {RAW_OUTPUT}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def strip_outer_fence(section):
    section = re.sub(r"^##[^\n]*\n", "", section.strip()).strip()
    section = re.sub(r"^```[a-z]*\n", "", section)
    if section.endswith("```"):
        section = section[:-3].rstrip("\n")
    return section.strip()


def extract_prompts(text):
    prompt_a = prompt_b = ""
    if "## PROMPT B" in text:
        a_raw, b_raw = text.split("## PROMPT B", 1)
        b_raw = "## PROMPT B" + b_raw
    else:
        a_raw, b_raw = text, ""
    if "## PROMPT A" in a_raw:
        a_section = re.sub(r"\s*---\s*$", "", a_raw[a_raw.index("## PROMPT A"):])
        prompt_a = strip_outer_fence(a_section)
    if b_raw:
        prompt_b = strip_outer_fence(b_raw)
    return prompt_a, prompt_b


meta_prompt = open(META_PROMPT, encoding="utf-8").read()
pdf_b64 = base64.standard_b64encode(open(PDF, "rb").read()).decode("utf-8")
print(f"Sending {PDF} + {META_PROMPT} to {MODEL}...")

with client.messages.stream(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    messages=[{
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64",
             "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text": meta_prompt},
        ],
    }],
) as stream:
    raw = stream.get_final_text()
    final = stream.get_final_message()

print(f"Tokens: {final.usage.input_tokens} in / {final.usage.output_tokens} out")
open(RAW_OUTPUT, "w", encoding="utf-8").write(raw)

prompt_a, prompt_b = extract_prompts(raw)
if not prompt_a:
    sys.exit(f"ABORT: could not extract Prompt A from the response (see {RAW_OUTPUT})")
if not prompt_b:
    sys.exit(f"ABORT: could not extract Prompt B from the response (see {RAW_OUTPUT})")

open(PROMPT_A, "w", encoding="utf-8").write(prompt_a)
open(PROMPT_B, "w", encoding="utf-8").write(prompt_b)
print(f"Wrote {PROMPT_A} and {PROMPT_B}")
