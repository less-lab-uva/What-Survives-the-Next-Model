# Experiment Setup

This directory evaluates a simplified single-LLM version of the TraceCoder paper. The original paper uses a trace-driven multi-agent debugging workflow; this reproduction directly asks one LLM call to generate a completed Python function or class solution.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package
- The Hugging Face `datasets` package
- Runtime libraries used by the BigCodeBench and ClassEval official tests

Install dependencies:

```bash
pip install -r requirements.txt
```

BigCodeBench and ClassEval include tests that import external libraries. If these packages are missing, `evaluator.py` may count a generated solution as failed because the local test environment cannot import the required module.

Before running `main.py`, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Load the Datasets

Both `main.py` and `evaluator.py` load benchmark data through Hugging Face using the `datasets` library.

Supported datasets:

```text
humanevalplus -> evalplus/humanevalplus, split test
humaneval     -> openai/openai_humaneval, split test
bigcodebench  -> bigcode/bigcodebench, split v0.1.2
classeval     -> FudanSELab/ClassEval, split test
```

The first run may download the datasets into the local Hugging Face cache. Later runs can reuse that cache.

---

## Step 2 — Run the LLM

Run either Prompt A or Prompt B on one dataset:

```bash
python3 main.py A humaneval
python3 main.py B humaneval

python3 main.py A humanevalplus
python3 main.py B humanevalplus

python3 main.py A bigcodebench
python3 main.py B bigcodebench

python3 main.py A classeval
python3 main.py B classeval
```

`main.py` reads:

```text
prompts/prompt_A.txt
prompts/prompt_B.txt
```

It loads the selected dataset from Hugging Face, randomly samples 10% of the dataset with seed 42, and asks Claude to produce output in the required JSON format.

With the current dataset sizes, the sampled runs are:

```text
humaneval      16 instances
humanevalplus  30 instances
bigcodebench   114 instances
classeval      10 instances
```

Outputs are saved to:

```text
outputs/outputs_A_humaneval.jsonl
outputs/outputs_B_humaneval.jsonl
outputs/outputs_A_humanevalplus.jsonl
outputs/outputs_B_humanevalplus.jsonl
outputs/outputs_A_bigcodebench.jsonl
outputs/outputs_B_bigcodebench.jsonl
outputs/outputs_A_classeval.jsonl
outputs/outputs_B_classeval.jsonl
```

Token reports are saved to:

```text
outputs/tokens_A_<dataset>.txt
outputs/tokens_B_<dataset>.txt
```

---

## Step 3 — Evaluate

Run:

```bash
python3 evaluator.py A humaneval
python3 evaluator.py B humaneval

python3 evaluator.py A humanevalplus
python3 evaluator.py B humanevalplus

python3 evaluator.py A bigcodebench
python3 evaluator.py B bigcodebench

python3 evaluator.py A classeval
python3 evaluator.py B classeval
```

The evaluator reads:

```text
outputs/outputs_<A|B>_<dataset>.jsonl
```

It then reloads the same dataset from Hugging Face to get the official tests. For HumanEval and HumanEval+, it executes the generated function with the benchmark `check(entry_point)` test. For BigCodeBench and ClassEval, it uses a unittest-based runner; ClassEval completions are wrapped into the original class skeleton when needed.

Results are written to:

```text
results/results_A_humaneval.jsonl
results/results_B_humaneval.jsonl
results/results_A_humanevalplus.jsonl
results/results_B_humanevalplus.jsonl
results/results_A_bigcodebench.jsonl
results/results_B_bigcodebench.jsonl
results/results_A_classeval.jsonl
results/results_B_classeval.jsonl
```

---

## Metric

The evaluator reports **Pass@1**:

```text
Pass@1 = passed / total evaluated
```

A generated solution is counted as passed if it executes successfully against the benchmark tests.

---
