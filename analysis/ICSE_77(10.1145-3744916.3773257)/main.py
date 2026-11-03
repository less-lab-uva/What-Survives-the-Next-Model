"""RISE single-call oracle: PostgreSQL query -> MySQL query (TPC-DS, RQ3 accuracy).

Collapses RISE's entire pipeline (query validation -> dialect-aware reduction ->
LLM translation of the simplified query -> AST rule extraction/abstraction ->
rule-driven conversion -> revalidation, with a ruleset accumulated across queries)
into a SINGLE LLM call per query. This is deliberately the paper's own SingleLLM /
LLMTranslator baseline (Table 1/2), reframed as the oracle: how far does one direct
Claude call get on TPC-DS when scored the same way the paper scores (execution).

TSE RERUN CONFIG: prompt B (informed) only, on claude-sonnet-5-5, over all 99 TPC-DS
queries (same sample as the Sonnet 4.6 run). Files carry the LLM id as a suffix so they
sit beside the Sonnet 4.6 originals (output_A.jsonl / output_B.jsonl).
THE ONE COMMITTED OUTPUT:
  - outputs/output_B_claude-sonnet-5-5.jsonl  -- one translation per line
Everything else goes to logs/ (gitignored):
  - logs/log_B_claude-sonnet-5-5.jsonl     -- raw per-call log (timings, tokens, verbatim response)
  - logs/tokens_B_claude-sonnet-5-5.jsonl  -- per-call tokens + cost
  - logs/usage_B_claude-sonnet-5-5.json    -- wall-time + cost totals
The run stops before any call that would start once spend has reached BUDGET_USD.

This script ONLY produces translations + usage; it needs no database. Scoring is
separate and execution-based (evaluator.py).

Reproducibility: hard-aborts unless the API key, both prompts, and all 99 inputs are
present, and refuses to overwrite any existing output/log/usage file.
"""

import os
import re
import sys
import glob
import json
import time

import anthropic

# ---------------------------------------------------------------- hardcoded config
MODEL = "claude-sonnet-5-5"     # rejects the `temperature` param (400: deprecated), so we don't send one
MAX_TOKENS = 8192               # a translated TPC-DS query is long; headroom vs truncation
SOURCE_DIALECT = "PostgreSQL"  # TPC-DS source dialect (RQ3: PostgreSQL -> MySQL)
TARGET_DIALECT = "MySQL"
N_EXPECTED_INPUTS = 99         # TPC-DS has exactly 99 queries; a different count == bad inputs

# USD per 1M tokens. ASSUMED: Sonnet 4.6's $3/$15 / 1.5 (team email: "1.5x cheaper") -- confirm rate.
PRICE_IN_PER_M = 2.0
PRICE_OUT_PER_M = 10.0
BUDGET_USD = 6.0               # hard stop; ~3x the estimate (Opus run: 430K in / 83K out tokens)

# Quick smoke test: set to a positive N to translate ONLY the first N queries. 0 = the full run.
SMOKE = 0

TAG = f"B_{MODEL}"
INPUT_DIR = os.path.join("inputs", "tpcds")
PROMPTS = {TAG: os.path.join("prompts", "prompt_B.txt")}    # TSE rerun: prompt B only
OUTPUTS = {TAG: os.path.join("outputs", f"output_{TAG}.jsonl")}
TOKENS = {TAG: os.path.join("logs", f"tokens_{TAG}.jsonl")}
LOGS = {TAG: os.path.join("logs", f"log_{TAG}.jsonl")}
USAGE = os.path.join("logs", f"usage_{TAG}.json")

# ---------------------------------------------------------------- preconditions (fail fast)
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ABORT: ANTHROPIC_API_KEY is not set.")

for path in PROMPTS.values():
    if not os.path.isfile(path):
        sys.exit(f"ABORT: missing prompt {path}")

if not os.path.isdir(INPUT_DIR):
    sys.exit(f"ABORT: missing input dir {INPUT_DIR}")

INPUT_PATHS = sorted(glob.glob(os.path.join(INPUT_DIR, "*.sql")))
assert len(INPUT_PATHS) == N_EXPECTED_INPUTS, (
    f"ABORT: expected {N_EXPECTED_INPUTS} .sql files in {INPUT_DIR}, "
    f"found {len(INPUT_PATHS)} (inputs incomplete?)")

for path in list(OUTPUTS.values()) + list(TOKENS.values()) + list(LOGS.values()) + [USAGE]:
    if os.path.exists(path):
        sys.exit(f"ABORT: output already exists (refusing to overwrite): {path}")

os.makedirs("outputs", exist_ok=True)
os.makedirs("logs", exist_ok=True)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------- core
def _query_from(text: str):
    """json.loads `text`; return its 'query' string if present and a string, else None."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("query"), str):
        return obj["query"]
    return None


def extract_translation(raw: str):
    """Post-process one model response into the translated SQL string, or None.

    The output schema is {"query": "<sql>"}, but a model (especially the black-box
    prompt) can emit reasoning and/or SEVERAL candidate ```json blocks before its final
    answer. Strategy: take the LAST fenced json block that parses to a 'query' string
    (the model's final answer); if there are no usable fenced blocks, fall back to the
    whole response, then to the outermost {...} span. Return None if nothing parses --
    the caller records a failed translation and continues (an unusable output IS a
    failed translation, not a reason to kill the whole run).
    """
    for block in reversed(re.findall(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)):
        q = _query_from(block.strip())
        if q is not None:
            return q
    q = _query_from(raw.strip())
    if q is not None:
        return q
    a, b = raw.find("{"), raw.rfind("}")
    if a != -1 and b > a:
        return _query_from(raw[a:b + 1])
    return None


def call_oracle(prompt: str, record: dict) -> dict:
    """One LLM call: prompt + the instance record -> translation + call facts."""
    content = (prompt + "\n\n### Input instance to translate\n"
               + json.dumps(record, ensure_ascii=False)
               + "\n\nRespond with ONLY the JSON object described in the Output section"
               + " -- no preamble, no explanation, no alternative candidates.")
    start = time.time()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": content}],
    )
    end = time.time()
    # Sonnet 5.5 may think before answering, so content[0] can be a ThinkingBlock: keep text blocks only.
    # (output_tokens already includes any thinking tokens, so cost stays exact.)
    raw = "".join(b.text for b in resp.content if b.type == "text")
    return {
        "translated_query": extract_translation(raw),
        "start_time": start,
        "end_time": end,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "stop_reason": resp.stop_reason,
        "thinking": any(b.type == "thinking" for b in resp.content),
        "raw": raw,
    }


def run_variant(tag: str) -> dict:
    """Translate all 99 queries under one prompt variant; write output + tokens + log JSONL."""
    prompt = open(PROMPTS[tag], encoding="utf-8").read()
    out_path, tok_path, log_path = OUTPUTS[tag], TOKENS[tag], LOGS[tag]
    print(f"\n=== prompt {tag}: {PROMPTS[tag]} -> {out_path} ===")

    seconds, in_tok, out_tok, failures = [], 0, 0, 0
    with open(out_path, "w", encoding="utf-8") as fout, \
         open(tok_path, "w", encoding="utf-8") as ftok, \
         open(log_path, "w", encoding="utf-8") as flog:
        for path in INPUT_PATHS[:SMOKE] if SMOKE else INPUT_PATHS:
            spent = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
            if spent >= BUDGET_USD:
                print(f"BUDGET: stopping at ${spent:.4f} >= ${BUDGET_USD} "
                      f"({len(seconds)} calls)", file=sys.stderr)
                break
            name = os.path.basename(path)
            source_query = open(path, encoding="utf-8").read()
            record = {"source_dialect": SOURCE_DIALECT,
                      "target_dialect": TARGET_DIALECT,
                      "query": source_query}
            call = call_oracle(prompt, record)

            fout.write(json.dumps({
                "name": name,
                "source_dialect": SOURCE_DIALECT,
                "target_dialect": TARGET_DIALECT,
                "source_query": source_query,
                "translated_query": call["translated_query"],
            }, ensure_ascii=False) + "\n")
            flog.write(json.dumps({
                "name": name,
                "start_time": call["start_time"],
                "end_time": call["end_time"],
                "input_tokens": call["input_tokens"],
                "output_tokens": call["output_tokens"],
                "model": MODEL,
                "stop_reason": call["stop_reason"],
                "thinking": call["thinking"],
                "raw": call["raw"],
            }, ensure_ascii=False) + "\n")
            in_cost = call["input_tokens"] * PRICE_IN_PER_M / 1e6
            out_cost = call["output_tokens"] * PRICE_OUT_PER_M / 1e6
            ftok.write(json.dumps({
                "llm": MODEL, "prompt": "B", "name": name,
                "duration_seconds": round(call["end_time"] - call["start_time"], 3),
                "tokens": {"input_tokens": call["input_tokens"], "output_tokens": call["output_tokens"]},
                "cost_usd": {"input_cost": round(in_cost, 6), "output_cost": round(out_cost, 6),
                             "total_cost": round(in_cost + out_cost, 6)},
            }) + "\n")
            fout.flush(); ftok.flush(); flog.flush()

            dt = call["end_time"] - call["start_time"]
            seconds.append(dt)
            in_tok += call["input_tokens"]
            out_tok += call["output_tokens"]
            if call["translated_query"] is None:
                failures += 1
                # raw is preserved in the log for inspection; scored as a failed translation.
                print(f"  {name}: WARN unparseable response (no JSON 'query') "
                      f"-> recorded translated_query=null ({dt:.2f}s)")
            else:
                print(f"  {name}: ok ({dt:.2f}s, in={call['input_tokens']} out={call['output_tokens']}"
                      f" spent=${(in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6:.4f})")

    cost = (in_tok * PRICE_IN_PER_M + out_tok * PRICE_OUT_PER_M) / 1e6
    summary = {
        "prompt": tag,
        "prompt_file": PROMPTS[tag],
        "model": MODEL,
        "n_calls": len(seconds),
        "total_seconds": round(sum(seconds), 3),
        "mean_seconds": round(sum(seconds) / len(seconds), 3) if seconds else 0.0,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "parse_failures": failures,
        "cost_usd": round(cost, 4),
    }
    print(f"  -> {summary['n_calls']} calls, {summary['total_seconds']}s, "
          f"${summary['cost_usd']}, {failures} unparseable")
    return summary


def main() -> None:
    summaries = {tag: run_variant(tag) for tag in PROMPTS}
    grand = {
        "n_calls": sum(s["n_calls"] for s in summaries.values()),
        "total_seconds": round(sum(s["total_seconds"] for s in summaries.values()), 3),
        "input_tokens": sum(s["input_tokens"] for s in summaries.values()),
        "output_tokens": sum(s["output_tokens"] for s in summaries.values()),
        "parse_failures": sum(s["parse_failures"] for s in summaries.values()),
        "cost_usd": round(sum(s["cost_usd"] for s in summaries.values()), 4),
    }
    usage = {
        "model": MODEL,
        "price_in_per_mtok": PRICE_IN_PER_M,
        "price_out_per_mtok": PRICE_OUT_PER_M,
        **summaries,
        "grand_total": grand,
    }
    with open(USAGE, "w", encoding="utf-8") as f:
        json.dump(usage, f, indent=2)
    print(f"\nSaved {USAGE}: {grand['n_calls']} calls, "
          f"{grand['total_seconds']}s, ${grand['cost_usd']}")


if __name__ == "__main__":
    main()
