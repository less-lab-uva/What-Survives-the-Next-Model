# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"InferLog: Accelerating LLM Inference for Online Log Parsing via ICL-oriented Prefix Caching"**. The original paper proposes InferLog, a pipeline that accelerates LLM-based log parsing by maximising KV cache reuse across concurrent requests using prefix-aware ICL reordering (PAIR). This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per log message and evaluates it on the HPC subset of Loghub-2k using PA, PTA, RTA, and GA.

---

## Prerequisites

- Python 3.8+
- The `anthropic` Python package

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Dataset

The dataset is already included in this directory:

```text
data/HPC_2k.log_structured_corrected.csv
```

No download step is required. The file was taken from the original InferLog repository:

```text
https://github.com/wiluen/InferLog
```

The raw log files originally come from the Loghub benchmark:

```text
https://github.com/logpai/loghub
```

Dataset details:

```text
Dataset   HPC (Loghub-2k)
Logs      2000 log messages
```

Each row contains a `LineId`, a `Content` field (raw log message sent to the LLM), and an `EventTemplate` field (ground truth template used by the evaluator).

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd> [dataset_name]
```

Example:

```bash
python3 main.py 16.0 HPC
```

`main.py` reads:

```text
data/HPC_2k.log_structured_corrected.csv
prompts/promptA.py
prompts/promptB.py
```

It processes all 2000 log messages in order, running Prompt A and Prompt B on each. The run checks the budget before every API call and stops when the budget is exhausted. Re-running continues from where it stopped without re-calling the LLM for already completed entries.

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
data/HPC_2k.log_structured_corrected.csv
```

It sorts the output files by `line_id`, joins each predicted template with the ground truth CSV on the `content` field, and computes PA, PTA, RTA, and GA for each prompt. (`correct_single_template` postprocessing is applied by `main.py` before writing outputs; the evaluator reads `log_template` as-is.)

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate metrics. Subsequent lines contain per-dataset breakdowns with the paper's Table 2 numbers for comparison.

---

## Metrics

The main metrics are:

```text
PA   -> Parsing Accuracy: fraction of logs whose predicted template exactly matches ground truth
PTA  -> Precision Template Accuracy: correctly identified templates / total predicted templates
RTA  -> Recall Template Accuracy: correctly identified templates / total oracle templates
GA   -> Grouping Accuracy: logs in correctly grouped clusters / total logs in dataset
```

PA and GA require a full 2000-log run to match the paper's evaluation conditions. PTA and RTA are also most meaningful on a full run. The evaluator records all four metrics per dataset and in aggregate in each result file.

---
