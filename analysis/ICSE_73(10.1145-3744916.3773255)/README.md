# Experiment Setup

This directory evaluates a simplified single-LLM version of the MGDebugger paper on code-generation benchmarks. The original paper uses hierarchical, multi-granularity debugging; this reproduction asks the LLM to directly produce a corrected solution for each benchmark problem.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package
- The Hugging Face `datasets` package

Install dependencies:

```bash
pip install anthropic datasets
```

Before running `main.py`, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Load the Datasets

No local dataset directory is required. Both `main.py` and `evaluator.py` load benchmark data through Hugging Face using the `datasets` library.

This reproduction uses:

```text
humaneval -> openai_humaneval, split test
mbpp      -> mbpp, split test
```

The first run may download the datasets into the local Hugging Face cache. Later runs can reuse that cache.

---

## Step 2 — Run the LLM

Run either Prompt A or Prompt B on HumanEval or MBPP:

```bash
python3 main.py A humaneval
python3 main.py B humaneval

python3 main.py A mbpp
python3 main.py B mbpp
```

`main.py` reads:

```text
prompts/prompt_A.txt
prompts/prompt_B.txt
```

It loads the selected dataset from Hugging Face, randomly samples 10% of the dataset with seed 42, and sends each sampled problem to Claude.

The script also uses existing output files as a cache by `task_id`, so repeated runs skip already-generated completions.

Outputs are saved to:

```text
outputs/outputs_A_humaneval.jsonl
outputs/outputs_B_humaneval.jsonl
outputs/outputs_A_mbpp.jsonl
outputs/outputs_B_mbpp.jsonl
```

Token reports are saved to:

```text
outputs/tokens_A_humaneval.txt
outputs/tokens_B_humaneval.txt
outputs/tokens_A_mbpp.txt
outputs/tokens_B_mbpp.txt
```

---

## Step 3 — Evaluate

Run:

```bash
python3 evaluator.py A humaneval
python3 evaluator.py B humaneval

python3 evaluator.py A mbpp
python3 evaluator.py B mbpp
```

The evaluator reads the generated output file:

```text
outputs/outputs_<A|B>_<dataset>.jsonl
```

It then reloads the same dataset from Hugging Face to get the official tests and entry points. For each task, it executes the generated completion together with the benchmark tests.

Results are written to:

```text
results/results_A_humaneval.jsonl
results/results_B_humaneval.jsonl
results/results_A_mbpp.jsonl
results/results_B_mbpp.jsonl
```

---

## Metric

The evaluator reports **accuracy**:

```text
accuracy = passed / total
```

A generated solution is counted as passed if it executes successfully against the benchmark tests.

---

