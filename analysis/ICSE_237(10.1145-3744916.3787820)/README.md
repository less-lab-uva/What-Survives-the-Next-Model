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
{prontoqa_ood, proofwriter, folio}, 596 chains total), derived from the MATP artifact's RQ1_2
baseline files. Each record keeps `{idx, premises, question,
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

After a run, the evaluator reads the outputs/logs:

```bash
python3 evaluator.py        # results/results_{A,B}.json — macro-F1 per (dataset, model) + mean per dataset (one file per prompt)
```

An instance whose predicted step count differs from the gold (or whose prediction is missing) can't
be aligned, so it is counted as `unaligned` and reported rather than silently dropped.

## TSE rerun: Sonnet 5.5, prompt B only

`main.py` is now configured for the TSE generality rerun: prompt B on `claude-sonnet-5-5`, over the
same 596 chains. The Sonnet 4.6 files described above are the paper's run and are unchanged.

| Step | Command | Writes |
|---|---|---|
| 1. Paid run (~$7.44, stops at `BUDGET_USD`) | `python3 main.py` | `outputs/output_B_claude-sonnet-5-5.jsonl` (committed); `logs/{log,failures,tokens}_B_claude-sonnet-5-5.jsonl` (gitignored) |
| 2. Score (no API calls) | `python3 evaluator.py` | `results/results_<variant>.json` for every `outputs/output_<variant>.jsonl`, i.e. `results_A.json`, `results_B.json` (Sonnet 4.6, reproduced unchanged) and `results_B_claude-sonnet-5-5.json` (committed) |

Differences from the Sonnet 4.6 run:
- Sonnet 5.5 rejects `temperature`, so none is sent (API default; 4.6 used 0.0).
- It sometimes thinks before answering (119/596 calls), so only text blocks are read.
- In 4/596 responses it gave a JSON answer, then revised it with a second one. The parser now falls
  back to the last JSON object. Those 4 rows were re-parsed from the logged responses, not re-called.
  Only `has_valid_proof_path_label` changed, so macro-F1 is unaffected.

Mean macro-F1, prompt B (PrOntoQA / ProofWriter / FOLIO): Sonnet 4.6 0.7774 / 0.8428 / 0.6666,
Sonnet 5.5 0.8414 / 0.9341 / 0.6920.
