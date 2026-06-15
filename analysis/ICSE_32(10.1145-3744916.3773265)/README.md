# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"From Seed to Scope: Reasoning to Identify Change Impact Sets"**. The original paper proposes Ripple, a two-phase intent-aware change impact analysis pipeline that combines static analysis preprocessing with LLM-based reasoning to predict co-modified methods in Java repositories. This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per instance and evaluates it on the CIA benchmark using Macro Precision, Recall, F1, and Hit@custom.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package
- `git` on PATH (used to clone repositories and check out parent commits)

Install the Python dependency:

```bash
pip install anthropic
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Dataset

Two asset files must be placed in the `assets/` directory before running:

```text
assets/all-outputs.zip
assets/cia-dataset.json
```

Both files are available from the original Ripple repository:

```text
https://github.com/se-doubleblind/ripple
```

- `all-outputs.zip` contains the original Ripple pipeline predictions for all 100 paper-evaluated instances (used to identify the instance pool and compare against the original pipeline).
- `cia-dataset.json` contains the CIA benchmark instances with metadata, repository information, commit diffs, and ground-truth impact sets.

Dataset details:

```text
Full benchmark   100 instances across 25 Apache Java repositories
Sample (10%)     10 instances
```

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 15.0
```

`main.py` reads:

```text
assets/all-outputs.zip
assets/cia-dataset.json
prompts/promptA.py
prompts/promptB.py
```

It selects a pool of 10 instances (10% of 100), automatically clones the required Apache repositories into `repos/`, checks out the parent commit for each, runs `extract_methods.py` to build input files under `input/<instance_id>/`, and then runs Prompt A and Prompt B on each instance. The run is resumable: re-running continues from where it stopped without re-calling the LLM for already completed instances.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

Token logs are saved to:

```text
outputs/tokens_A.jsonl
outputs/tokens_B.jsonl
```

---

## Step 3 — Evaluate

```bash
python3 evaluator.py
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
assets/cia-dataset.json
assets/all-outputs.zip
repos/              (optional — used for body-only-change ground truth fallback)
```

It extracts ground-truth method names from the commit diffs in `cia-dataset.json`, normalises LLM predictions, computes per-instance Precision, Recall, and F1, and aggregates into macro averages and Hit@custom. It also evaluates the original Ripple pipeline predictions on the same instances for direct comparison.

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate metrics. Subsequent lines contain per-instance breakdowns.

---

## Metrics

The main metrics are:

```text
Macro Precision  -> mean per-instance precision (predicted ∩ GT) / |predicted|
Macro Recall     -> mean per-instance recall (predicted ∩ GT) / |GT|
Macro F1         -> mean per-instance F1
Hit@custom       -> fraction of instances where at least one GT method appears
                    in the predicted set (k = |predicted| per instance)
```

The evaluator records per-instance and aggregate Macro Precision, Macro Recall, Macro F1, and Hit@custom in each result file.

---
