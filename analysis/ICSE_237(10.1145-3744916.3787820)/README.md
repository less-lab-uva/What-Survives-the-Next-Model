# Beyond Correctness (MATP)

Single-LLM-call recreation of **RQ1** (reasoning-step verification — Average Macro F1) from
*Beyond Correctness: Exposing LLM-generated Logical Flaws in Reasoning via Multi-step Automated
Theorem Proving* (DOI 10.1145/3744916.3787820).

One call replaces the paper's whole NL → First-Order-Logic → theorem-prover pipeline: given the
premises, the question (conclusion), and a candidate chain of `reasoning_steps`, the oracle returns
a per-step validity judgment `{"step_correctness_label": ["True"|"False"|"Unknown", ...],
"has_valid_proof_path_label": <bool>}`. Run for prompt A (black-box) and prompt B (informed).
Scored the way the paper scores — 3-class (True/False/Unknown) macro-F1 over the step labels,
flattened per (dataset, model) and averaged per dataset.

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`) — for `main.py`

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Data

`inputs/<dataset>/<model>.json` — 30 input files (10 reasoning models × 3 datasets
{prontoqa_ood, proofwriter, folio}, 596 chains total), built by `utils/build_inputs.py` from the
MATP artifact's RQ1_2 baseline files. Each record keeps `{idx, premises, question,
reasoning_steps}`; only those last three fields are sent to the model. The gold lives alongside in
`inputs/<dataset>/<model>_labels.json` and is never sent — the evaluator recovers it by
(dataset, model, idx).

## Run

The script refuses to clobber outputs (fail-fast abort rather than overwrite). Back up or remove
any existing `outputs/output_*.jsonl` / `logs/log_*.jsonl` first, then:

```bash
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one per prompt variant A/B; every row tagged with its `dataset` + `model`)

- `outputs/output_{A,B}.jsonl` — predictions: `dataset, model, idx, step_correctness_label, has_valid_proof_path_label`
- `logs/log_{A,B}.jsonl` — raw per-call log: `dataset, model, idx, start_time, end_time, input_tokens, output_tokens, raw`
- `logs/failures_{A,B}.jsonl` — records whose response couldn't be parsed (logged and skipped)

## Evaluation

After a run, two processors read the outputs/logs:

```bash
python3 evaluator.py        # results/results_{A,B}.json — macro-F1 per (dataset, model) + mean per dataset (one file per prompt)
python3 utils/usage.py      # logs/usage.json            — seconds elapsed + cost (A vs B)
```

An instance whose predicted step count differs from the gold (or whose prediction is missing) can't
be aligned, so it is counted as `unaligned` and reported rather than silently dropped.

## `utils/` (run from this directory)

Helper scripts kept separate from the core pipeline (`main.py`, `evaluator.py`). Paths are
fixed relative to this directory, so invoke them as `python3 utils/<script>.py`:

- `utils/build_inputs.py` — build the `inputs/<dataset>/<model>.json` + `*_labels.json` pairs from the MATP artifact's RQ1_2 baseline + manual-annotation files.
- `utils/prompt_generator.py` — regenerate `prompts/prompt_A.txt` + `prompt_B.txt` from the paper PDF + `prompts/meta_prompt.txt`.
- `utils/estimate_cost.py` — project the run cost via the free `count_tokens` endpoint (no spend).
- `utils/usage.py` — after a run, derive seconds + cost from the per-call logs → `logs/usage.json`.
