"""Project the cost of a FULL run over the 99 TPC-DS queries x both prompts — NO SPEND.

Input tokens are counted EXACTLY with Anthropic's free `messages.count_tokens` endpoint (no
generation, no billing), using the SAME message main.py builds, so the estimate matches the
real run's input side.

Output is the tricky part for this paper: unlike the label-classification papers (a ~30-token
JSON verdict), RISE's oracle returns a FULL translated query — roughly the same size as the
source. count_tokens has no output mode, so we PROXY output length with the source query's own
token count plus a small JSON-wrapper overhead ({"query": "..."} + escaping). This is an
approximation; the actual output varies a little as dialect constructs are rewritten.

Run from the analysis directory:  python3 utils/estimate_cost.py
Paths are FIXED relative to that directory. Writes logs/cost_estimate.json. Like main.py:
preconditions up front, hard-abort, no overwrite.
"""

import os
import sys
import glob
import json

import anthropic

MODEL = "claude-sonnet-4-6"
# claude-sonnet-4-6 published pricing, USD per 1M tokens (matches main.py).
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0
JSON_WRAPPER_OVERHEAD = 10   # tokens for the {"query": "..."} envelope around the translated SQL

SOURCE_DIALECT = "PostgreSQL"
TARGET_DIALECT = "MySQL"
N_EXPECTED_INPUTS = 99
PROGRESS_EVERY = 20

INPUT_DIR = os.path.join("inputs", "tpcds")
PROMPTS = {"A": os.path.join("prompts", "prompt_A.txt"),
           "B": os.path.join("prompts", "prompt_B.txt")}
ESTIMATE = os.path.join("logs", "cost_estimate.json")

# Preconditions.
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")
for path in PROMPTS.values():
    if not os.path.isfile(path):
        sys.exit(f"ABORT: missing prompt {path}")
if not os.path.isdir(INPUT_DIR):
    sys.exit(f"ABORT: missing input dir {INPUT_DIR}")
INPUT_PATHS = sorted(glob.glob(os.path.join(INPUT_DIR, "*.sql")))
assert len(INPUT_PATHS) == N_EXPECTED_INPUTS, (
    f"ABORT: expected {N_EXPECTED_INPUTS} .sql files in {INPUT_DIR}, found {len(INPUT_PATHS)}")
if os.path.exists(ESTIMATE):
    sys.exit(f"ABORT: output already exists (refusing to overwrite): {ESTIMATE}")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def count_tokens(content: str) -> int:
    return client.messages.count_tokens(
        model=MODEL, messages=[{"role": "user", "content": content}]).input_tokens


def build_content(prompt: str, source_query: str) -> str:
    """Mirror EXACTLY the message main.py sends, so the input count is faithful."""
    record = {"source_dialect": SOURCE_DIALECT,
              "target_dialect": TARGET_DIALECT,
              "query": source_query}
    return (prompt + "\n\n### Input instance to translate\n"
            + json.dumps(record, ensure_ascii=False)
            + "\n\nRespond with ONLY the JSON object described in the Output section"
            + " -- no preamble, no explanation, no alternative candidates.")


# Output proxy depends only on the source query (same for both prompts) -> count once, reuse.
print(f"Counting output proxy for {len(INPUT_PATHS)} source queries ...")
sources, out_proxy = {}, {}
for i, path in enumerate(INPUT_PATHS, 1):
    name = os.path.basename(path)
    sources[name] = open(path, encoding="utf-8").read()
    out_proxy[name] = count_tokens(sources[name]) + JSON_WRAPPER_OVERHEAD
    if i % PROGRESS_EVERY == 0:
        print(f"  {i}/{len(INPUT_PATHS)}")

variants = {}
for tag, prompt_path in PROMPTS.items():
    prompt = open(prompt_path, encoding="utf-8").read()
    print(f"\nCounting input tokens for prompt {tag} ({prompt_path}) ...")
    in_tok = out_tok = 0
    for i, path in enumerate(INPUT_PATHS, 1):
        name = os.path.basename(path)
        in_tok += count_tokens(build_content(prompt, sources[name]))
        out_tok += out_proxy[name]
        if i % PROGRESS_EVERY == 0:
            print(f"  {i}/{len(INPUT_PATHS)}")
    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    variants[tag] = {
        "prompt": tag,
        "prompt_file": prompt_path,
        "n_queries": len(INPUT_PATHS),
        "input_tokens": in_tok,
        "output_tokens_est": out_tok,
        "cost_usd": round(cost, 4),
    }
    print(f"  -> prompt {tag}: in={in_tok:,}  out~{out_tok:,}  =  ${variants[tag]['cost_usd']}")

grand = {
    "n_calls": sum(v["n_queries"] for v in variants.values()),
    "input_tokens": sum(v["input_tokens"] for v in variants.values()),
    "output_tokens_est": sum(v["output_tokens_est"] for v in variants.values()),
    "cost_usd": round(sum(v["cost_usd"] for v in variants.values()), 4),
}

estimate = {
    "model": MODEL,
    "price_in_per_mtok": PRICE_IN_PER_M,
    "price_out_per_mtok": PRICE_OUT_PER_M,
    "input_tokens": "EXACT via free count_tokens (same message main.py sends)",
    "output_tokens_est": ("PROXY: source-query tokens + JSON wrapper; a dialect translation "
                          "preserves query size, so output ~= input query length"),
    "A": variants["A"],
    "B": variants["B"],
    "grand_total": grand,
}

os.makedirs("logs", exist_ok=True)
with open(ESTIMATE, "w", encoding="utf-8") as f:
    json.dump(estimate, f, indent=2)

print(f"\nGRAND TOTAL (99 queries x A+B, full dataset): ${grand['cost_usd']}")
print(f"Saved {ESTIMATE}")
