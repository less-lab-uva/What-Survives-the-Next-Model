# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"Large Language Model-Aided Partial Program Dependence Analysis"**. The original paper proposes ΛMDA (PrePA), a two-phase pipeline that uses an LLM iteratively to produce an approximately-complete compilable Java program from a partial snippet, then runs Joern on that program to extract a Program Dependence Graph (PDG). This reproduction replaces the iterative LLM phase with a single Claude Sonnet 4.6 call per snippet and evaluates it on the StatType-SO dataset using Precision, Recall, and F1 over DDG edges.

---

## Prerequisites

- Python 3.10+
- The `anthropic`, `pydot`, and `beautifulsoup4` Python packages
- Joern (for Step 3 evaluation only)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

**For evaluation (Step 3):** `evaluator.py` invokes Joern to extract PDGs from the LLM-generated Java code. Joern is expected at:

```text
/project/lesslab/nm8tm/joern-cli/joern-cli/bin
```

If your installation is elsewhere, update `JOERN_PATH` at the top of `evaluator.py`:

```python
JOERN_PATH = "/path/to/your/joern-cli/bin"
```

Joern can be downloaded from:

```text
https://joern.io
```

The evaluator uses `joern-parse` and `joern-export`, both included in the standard Joern CLI release.

---

## Step 1 — Dataset

The dataset is already included in this directory:

```text
dataset/Stattype_res.json
```

No download step is required. The file comes from the original PrePA artifact:

```text
https://anonymous.4open.science/r/PrePA-7157/README.md
```

Dataset details:

```text
Total entries     172 Java partial-code snippets from StackOverflow (StatType-SO)
Excluded at load  3 entries with no valid ground-truth PDG
Eligible          169 entries processed by main.py
Evaluated         109 entries that contribute to metrics (the remaining 60 have
                  no DDG edges whose both endpoints appear in partial_code)
```

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd> [dataset_name]
```

Example:

```bash
python3 main.py 6.0 stattype
```

`main.py` reads:

```text
dataset/Stattype_res.json
prompts/promptA.py
prompts/promptB.py
```

It loads the 169 eligible entries, runs Prompt A and Prompt B on each, and checks the budget before every API call. Re-running continues from where it stopped — already completed entries are not re-submitted to the LLM.

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
python3 evaluator.py [dataset_name]
```

Example:

```bash
python3 evaluator.py stattype
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
dataset/Stattype_res.json
```

For each entry it runs Joern on the LLM-generated `approximated_code` to extract a PDG, computes valid DDG edges against the ground truth, and calls `calculate_fp_tp_fn` (reproduced verbatim from the paper's `RQ3_eval.py`). Joern results are cached per prompt in:

```text
outputs/joern_cache_A.json
outputs/joern_cache_B.json
```

so re-running the evaluator is fast. It also computes the same metrics for the original PrePA pipeline using the pre-stored `PrePA_code_res` PDGs in the dataset JSON.

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate metrics (our pipeline + original PrePA on the same entries). Subsequent lines contain per-entry breakdowns.

---

## Metrics

The main metrics are:

```text
Precision  -> TP / (TP + FP) over DDG edges
Recall     -> TP / (TP + FN) over DDG edges
F1         -> harmonic mean of Precision and Recall
```

Only DDG (data dependence) edges are evaluated — this corresponds to the **Data** column in the paper's Table 1, not the Data+Control headline. Entries with no valid DDG edges inside `partial_code` are excluded from all metrics.

---
