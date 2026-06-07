# Experiment Setup

**FoundRoot: Towards Foundation Model for Root Cause Analysis via Structured Deep Thinking**  
ICSE 2026 · DOI: 10.1145/3744916.3787814

Given microservice monitoring metrics and a dependency graph, the LLM ranks candidate root causes using Prompt A and Prompt B, evaluated on Top-1/Top-3 accuracy and MRR.

---

## Prerequisites

- Python 3.8+

Install Python dependencies:
```bash
pip install -r requirements.txt
```

Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Dataset

The dataset is included at `dataset/`. It contains test cases for datasets A, B, C, and D, each with microservice failure scenarios and ground-truth root causes.

---

## Step 1 — Run the Experiment

Run the LLM on the test cases using Prompt A or Prompt B:

```bash
# Run with Prompt A on all four datasets
python3 main.py --prompt A --n 100 --datasets A,B,C,D

# Run with Prompt B
python3 main.py --prompt B --n 100 --datasets A,B,C,D

# Run with both prompts
python3 main.py --prompt both --n 100 --datasets A,B,C,D
```

Key options:
- `--prompt`: `A`, `B`, or `both`
- `--n`: number of cases to process
- `--datasets`: comma-separated dataset letters to use
- `--seed`: random seed for sampling
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed cases are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `dataset`, `case_idx`, `ground_truth`, `all_components`, `predicted`, `prompt_sent`, `raw_response`, and `llm_response_time`.

---

## Step 2 — Evaluate

Compute ranking metrics from the outputs generated in Step 1:

```bash
python3 evaluator.py --prompt A
python3 evaluator.py --prompt B
python3 evaluator.py --prompt both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-dataset results for Prompt A
└── results_B.jsonl    # aggregate + per-dataset results for Prompt B
```

---

## Metrics

- **Top-1 Accuracy**: fraction of cases where the predicted top-ranked component matches the ground-truth root cause.
- **Top-3 Accuracy**: fraction of cases where the ground-truth root cause appears in the top 3 predicted components.
- **MRR** (Mean Reciprocal Rank): average of 1/rank for the ground-truth root cause across all cases.

All metrics are reported per dataset (A–D) and overall.
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.
