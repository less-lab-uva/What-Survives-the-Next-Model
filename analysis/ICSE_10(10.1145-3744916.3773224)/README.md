# AllianceCoder — LLM Replacement Study on CoderEval

This repository extends the original [AllianceCoder](https://github.com/AllianceCoder/AllianceCoder) pipeline with an LLM replacement study. We replace the full multi-stage RAG pipeline with a single Claude Sonnet 4.6 call and evaluate it on the CoderEval benchmark using the same Pass@k metric reported in the original paper.

---

## Overview

AllianceCoder is a repository-level code generation system using retrieval-augmented generation (RAG). Given a function stub and its file context, it generates completed function bodies through three stages: repository API processing, query processing, and context-integrated code generation.

In this study, we replace that pipeline with a single LLM call using two prompt strategies:

- **Prompt A (Black-box):** Instructs the model to produce 5 distinct implementations with no guidance on methodology.
- **Prompt B (Informed):** Provides a 6-step methodology (catalogue symbols → decompose spec → match APIs → expand candidates → generate 5 implementations → format output).

Both prompts use the same two few-shot examples drawn from CoderEval tasks.

---

## Prerequisites

**Python packages:**
```bash
pip install anthropic
```

**Environment variable:**
```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

**Apptainer** (for running the CoderEval evaluation container):
```bash
module load apptainer   # or install apptainer >= 1.4.5 on your system
```

---

## Step 1 — Prepare the Input Dataset

The input file `input/input_codereval.jsonl` contains all 230 CoderEval Python tasks. If it does not exist, generate it from the raw dataset:

```bash
cd input/
python3 "handle_input+CoderEval+Context.py"
```

This reads `CoderEval4Python.json` and produces `input_codereval.jsonl` with one JSON record per task containing the function stub, file context, and metadata.

---

## Step 2 — Generate Predictions

`main.py` samples 10% of the dataset (23 tasks) and runs both Prompt A and Prompt B on each task.

```bash
python3 main.py <budget_usd>
```

Example:
```bash
python3 main.py 5.0
```

**Behavior:**
- Samples 23 tasks at random (10% of 230).
- Runs Prompt A and Prompt B on each task, generating 5 predictions per prompt per task.
- Checks the budget before every API call and stops when the budget is exhausted.
- Is resumable: re-running continues from where it stopped, preserving already-completed tasks.
- Partially completed tasks (one prompt done, the other not) are always finished before new tasks are started.

**Outputs** (under `outputs/`):
| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per task: `_id`, `function_name`, `input`, `predictions` (list of 5) |
| `outputs_B.jsonl` | Same for Prompt B |
| `tokens_A.jsonl` | Token counts, cost, and wall-clock time per API call for Prompt A |
| `tokens_B.jsonl` | Same for Prompt B |

**Estimated cost** (Claude Sonnet 4.6, $3/MTok in, $15/MTok out):
- 23 tasks, both prompts: ~$0.76 total
- Full 230 tasks, both prompts: ~$7.60 total

---

## Step 3 — Set Up the CoderEval Evaluation Environment

CoderEval requires a pre-built Docker image with all 43 project environments installed. We run it via Apptainer (no root access needed).

### 3.1 Download the Docker image

Go to the [CoderEval GitHub repository](https://github.com/CoderEval/CoderEval) and follow the link in the README to download `CoderEval.tar` from their Google Drive. Place it under:

```
AllianceCoder/CoderEval-Docker/CoderEval.tar
```

> **Note:** The tar file is a `docker export` dump (flat filesystem), not a `docker save` archive. Do not use `docker-archive://` with Apptainer — it will fail with "manifest.json not found".

### 3.2 Extract to a sandbox directory

```bash
mkdir -p CoderEval-Docker/codereval_sandbox
tar -xf CoderEval-Docker/CoderEval.tar -C CoderEval-Docker/codereval_sandbox/
```

This extracts the full container filesystem (~7 GB). Extraction takes a few minutes.

### 3.3 Fix directory permissions

The sandbox directories need to be readable by Apptainer:

```bash
chmod -R o+rx CoderEval-Docker/codereval_sandbox/home/
chmod -R u+w CoderEval-Docker/codereval_sandbox/home/travis/builds/
```

### 3.4 Verify the sandbox works

```bash
module load apptainer
apptainer exec CoderEval-Docker/codereval_sandbox/ python --version
# Expected: Python 3.10.12
```

---

## Step 4 — Run the Evaluation

Once the sandbox is set up, run the evaluation end-to-end with a single command:

```bash
module load apptainer
python3 evaluator.py
```

**What it does automatically:**
1. Converts `outputs_A.jsonl` / `outputs_B.jsonl` to the JSONL format expected by CoderEval's runner.
2. Sets up a writable workspace directory with the CoderEval scripts (`PythonExec.py`, `GroundTruth.py`, etc.).
3. Runs `GroundTruth.py` inside the container to validate the test environment before each prompt.
4. Runs `PythonExec.py` inside the container for each prompt, which injects each generated function into the project test harness and records pass/fail per attempt.
5. Computes Pass@1, Pass@3, and Pass@5 using the unbiased estimator and saves results to `results/`.

**Results** (under `results/`):
| File | Description |
|---|---|
| `results_A.jsonl` | Line 1: aggregate `{pass_at_1, pass_at_3, pass_at_5, total_tasks}`. Lines 2+: per-task pass/fail details. |
| `results_B.jsonl` | Same for Prompt B |

---

## Evaluation Metric

Pass@k is computed using the unbiased estimator from the original paper:

$$\text{Pass@}k = \mathbb{E}\left[1 - \frac{\binom{n-c}{k}}{\binom{n}{k}}\right]$$

where $n = 5$ (predictions per task) and $c$ is the number of passing predictions for a given task.

**Baseline** (from AllianceCoder paper, Table 8):

| System | Pass@1 | Pass@3 | Pass@5 |
|---|---|---|---|
| AllianceCoderGPT (230 tasks) | 36.52% | 40.0% | 41.30% |
|---|---|---|---|
| AllianceCoderGemini (230 tasks) | 24.78% | 46.52% | 27.82% |
|---|---|---|---|
| Ours PromptA (23 tasks) | 60.0% | 60.87% | 60.87% |
|---|---|---|---|
| Ours PromptB (23 tasks) | 60.87% | 60.87% | 60.87% |

> Our evaluation covers a 10% random sample (23 tasks). Results are computed with the correct denominator (23), reflecting the same metric definition.


