# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"What to Retrieve for Effective Retrieval-Augmented Code Generation? An Empirical Study and Beyond"**. The original paper proposes AllianceCoder, a three-stage retrieval-augmented generation pipeline for repository-level code generation that processes repository APIs, decomposes queries into implementation steps, and generates code from retrieved context. This reproduction replaces that pipeline with a single Claude Sonnet 4.6 call per task and evaluates it on the CoderEval benchmark using Pass@k.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package
- Apptainer 1.4.5+ (for Step 3 evaluation only)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

**For evaluation (Step 3):** `evaluator.py` runs the CoderEval test harness inside an Apptainer container. Load Apptainer before running the evaluator:

```bash
module load apptainer/1.5.0   # on HPC clusters with Lmod
# — or —
apptainer --version            # verify >= 1.4.5 is already on your PATH
```

Download `CoderEval.tar` from the [CoderEval GitHub repository](https://github.com/CoderEval/CoderEval) and extract it into a sandbox directory:

```bash
mkdir -p CoderEval-Docker/codereval_sandbox
tar -xf CoderEval-Docker/CoderEval.tar -C CoderEval-Docker/codereval_sandbox/
chmod -R o+rx CoderEval-Docker/codereval_sandbox/home/
chmod -R u+w CoderEval-Docker/codereval_sandbox/home/travis/builds/
```

> **Note:** `CoderEval.tar` is a `docker export` dump (flat filesystem), not a `docker save` archive. Do not use `docker-archive://` with Apptainer — it will fail with "manifest.json not found".

---

## Step 1 — Dataset

Run the download script to fetch `CoderEval4Python.json` from the CoderEval GitHub repository and process it into the format expected by `main.py`:

```bash
python3 download_dataset.py
```

This creates:

```text
input/CoderEval4Python.json
input/input_codereval.jsonl
```

Each row of `input/input_codereval.jsonl` contains:

```text
prompt        -> function signature and docstring
current_file  -> file content preceding the target function
metadata      -> ground truth, function name, task ID, line number
```

Dataset details:

```text
Full dataset   230 Python tasks
```

The paper states that its source code and dataset are available at:

```text
https://github.com/Elendil3703/AllianceCoder
```

The raw dataset is sourced from:

```text
https://github.com/CoderEval/CoderEval
```

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 5.0
```

`main.py` reads:

```text
input/input_codereval.jsonl
prompts/promptA.py
prompts/promptB.py
```

It runs Prompt A and Prompt B on all tasks in the dataset, generating 1 prediction per prompt per task. The run checks the budget before every API call and stops when the budget is exhausted. Re-running continues from where it stopped — already completed tasks are not re-submitted to the LLM.

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

Once the Apptainer sandbox is ready (see Prerequisites), run:

```bash
module load apptainer
python3 evaluator.py
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

It converts the outputs to CoderEval's input format, sets up a writable workspace, runs `GroundTruth.py` inside the container to validate the test environment, and then runs `PythonExec.py` inside the container for each prompt to inject each generated function into the project test harness and record pass/fail per attempt.

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate summary (`pass_at_1`, `total_tasks`). Subsequent lines contain per-task pass/fail details.

---

## Metrics

The main metrics are:

```text
Pass@1  -> probability that the single prediction passes all tests
```

Pass@1 is computed using the unbiased estimator from the original CoderEval paper. The evaluator records per-task pass counts and aggregate Pass@1 in each result file.

---
