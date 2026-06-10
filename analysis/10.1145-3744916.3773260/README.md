# Experiment Setup

**IntentFix: Automated Logic Vulnerability Repair via LLM-Driven Intent Modeling**
ICSE 2026 · DOI: 10.1145/3744916.3773260

Given a vulnerable code snippet (a logic vulnerability from the CWE-840 family) and a high-level
description of the vulnerability, the LLM generates a corrected version in a single pass — replacing
IntentFix's whole multi-phase intent-modeling pipeline with one call. Generated patches are then
scored by an AI oracle. We run two prompts: **Prompt A** (black-box) and **Prompt B** (informed),
generated from the paper via `utils/prompt_generator.py`.

---

## Prerequisites

- Python 3.8+

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Build the dataset

```bash
python3 utils/produce_dataset.py
```

Fetches the pinned `files.tar.gz` + `metadata.json` from the IntentFix artifact, rebuilds the 1,107
vulnerability-patch pairs, and attaches a `vulnerability_description` looked up from the official
MITRE CWE REST API. Writes `dataset/intentfix_pairs.jsonl`, one record per pair:

- `pair_id` — pair identifier (`pair_XXXX`)
- `cwe`, `cve` — vulnerability identifiers
- `vulnerability_description` — the CWE's standard description (the "high-level description")
- `buggy_code` — the vulnerable file (model input)
- `human_patch` — the maintainer's fix (ground truth, used only by the oracle)

**Held-out few-shot examples.** `pair_0010` (PHP, CWE-639) and `pair_1011` (Go, CWE-770) are embedded
as few-shot demonstrations in the prompts. They are listed in `dataset/heldout_fewshot_ids.json` and
are skipped by `main.py` to avoid evaluating on demonstrations. Exclude them from any further
down-sampling too.

---

## Step 2 — Generate the prompts

```bash
python3 utils/prompt_generator.py
```

Sends `paper.pdf` + `prompts/meta_prompt.txt` to Claude and writes `prompts/prompt_A.txt`
(black-box) and `prompts/prompt_B.txt` (informed). The meta-prompt embeds a two-example few-shot
demonstration whose inputs are exactly `buggy_code` + `vulnerability_description`.

---

## Step 3 — Generate patches

```bash
python3 main.py
```

Runs Prompt A then Prompt B over every (non-held-out) pair. Each call sends only `buggy_code` +
`vulnerability_description` (paper section 4.3) to Claude (`claude-sonnet-4-6`, `temperature=0.0`)
and parses `{"fixed_code": "..."}`. Writes one file per prompt:

```
outputs/output_A.jsonl   outputs/output_B.jsonl      {pair_id, fixed_code}
```

Per-call timing/tokens, a usage summary, and failures go to `logs/` (gitignored). Set `SMOKE`
at the top of `main.py` to a small N for a cheap end-to-end test first.

---

## Step 4 — Evaluate

```bash
python3 evaluator.py
```

The AI oracle (paper section 4.4.1) is given the **vulnerable code, the generated patch, the
ground-truth fix, and the CWE description** (recovered by joining each prediction back to the dataset
by `pair_id`), and judges correctness using the package's **actual AI-oracle prompt** (4 criteria:
same root cause, semantic equivalence to the human patch, handles the vulnerability, no regressions).
Writes the **aggregate only** (accuracy + per-CWE breakdown), one file per prompt:

```
results/result_A.json   results/result_B.json
```

The per-pair verdicts go to `logs/judgements_{A,B}.jsonl` (gitignored), alongside judge
timing/tokens and failures.

---

## Metric

**Patch Accuracy** — the fraction of generated patches the AI oracle judges correct. The paper reports
this both via the AI oracle and via manual expert validation (Table 2); we report the AI-oracle
accuracy.

---

## Differences from the original

This reproduction reproduces the paper's described baselines and corrects defects in the released artifact:

- **Single LLM call, Prompt A / Prompt B.** We replace the multi-phase IntentFix pipeline (intent
  modeling → semantic-gap detection → patch & verify) with one call, under a black-box and an
  informed prompt, matching the sibling reproductions in this collection.
- **Single judge model, Claude.** Generation and judging both use `claude-sonnet-4-6`; the paper used
  OpenAI `o4-mini` as an independent oracle. Claude-judging-Claude introduces self-evaluation bias, so
  absolute numbers are not directly comparable to the paper's.
- **High-level description from the CWE.** The paper's baseline gets "a high-level description of the
  vulnerability" and its oracle gets "the CWE description", but the artifact stores neither (only bare
  CWE/CVE ids; verified across `collect_dataset.py`, `metadata.json`, and the pipeline). We supply the
  official MITRE CWE description for both.
- **Corrected oracle inputs.** The artifact's evaluator read `result["inputs"][...]`, a key never
  populated, so its oracle saw an *empty* ground-truth fix and no CWE. Here the oracle receives all
  four inputs the paper describes.
- **Deterministic.** `temperature=0.0` is set explicitly (the artifact's Claude calls left it unset).
