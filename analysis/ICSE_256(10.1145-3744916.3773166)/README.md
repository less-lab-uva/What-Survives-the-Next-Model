# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"EchoFuzz: Empowering Smart Contract Fuzzing with Large Language Models"**. The original paper proposes EchoFuzz, a 4-phase LLM-guided smart contract fuzzer that generates Vulnerable Function Call Sequences, seeds a coverage-guided fuzzer, and applies a runtime oracle for zero-false-positive vulnerability detection. This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per contract and evaluates it on the D2 dataset using precision and recall.

---

## Prerequisites

- Python 3.10+
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

The dataset consists of 143 Solidity smart contract files (`.sol`) from the SmartBugs Wild benchmark. Each file contains embedded `<report>` annotations that mark the ground-truth vulnerability category (e.g., `// <report> REENTRANCY`). `main.py` strips these annotations before sending any contract to the LLM; `evaluator.py` reads them back to compute precision and recall.

The dataset must be placed at:

```text
dataset/D2/
```

The paper states that its source code and dataset are available at:

```text
https://github.com/iceray00/EchoFuzz
```

Copy the `dataset/D2/` folder from that repository into this directory.

Dataset details:

```text
contracts   143 .sol files
labels      REENTRANCY, ARITHMETIC, UNCHECKED_LL_CALLS, BAD_RANDOMNESS,
            TIME_MANIPULATION, TIME, ACCESS_CONTROL, FRONT_RUNNING,
            DENIAL_OF_SERVICE, OTHER, SHORT_ADDRESSES
```

---

## Step 2 — Run the LLM

```bash
python3 main.py --total_cost <budget_usd>
```

Example:

```bash
python3 main.py --total_cost 10.0
```

`main.py` reads:

```text
dataset/D2/          (all .sol files)
prompts/promptA.py
prompts/promptB.py
```

It processes all 143 D2 contracts under the given USD budget, running Prompt A and Prompt B on each. The run is resumable: re-running continues from where it stopped via `outputs/state.json` without re-calling the LLM for already completed contracts.

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
dataset/D2/          (ground-truth <report> labels)
```

It computes per-contract and aggregate precision and recall against the D2 ground truth and writes:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate summary (total TP/FP/FN, per-category breakdown, and the paper Table 3 reference block). Subsequent lines contain per-contract breakdowns.

---

## Metrics

The main metrics are:

```text
Precision  -> TP / (TP + FP) across all evaluated contracts
Recall     -> TP / (TP + FN) across all evaluated contracts
```

Evaluation is at the contract level: a contract is a TP for category X if the LLM reports X and the D2 label is X; FP if the LLM reports X but D2 does not; FN if D2 labels X but the LLM does not report it. Only the five categories with D2 ground-truth labels are evaluated (IO, RE, UC, BN, TP). The evaluator records per-category and aggregate precision and recall in each result file.

---
