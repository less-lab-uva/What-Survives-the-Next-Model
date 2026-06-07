# Experiment Setup

**VulTrial: LLM-Based Vulnerability Detection via Prosecution-Defense Reasoning**  
ICSE 2026 · DOI: 10.1145/3744916.3773256

Given a C/C++ function, the LLM predicts whether it contains a security vulnerability using Prompt A and Prompt B, evaluated on accuracy, F1, and pair-level metrics.

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

The dataset is already included at `dataset/primevul_test_paired.jsonl`. Each line is a JSON record with a C/C++ `func`, a binary `target` label (1 = vulnerable, 0 = clean), and paired metadata.

---

## Step 1 — Run the Experiment

Run the LLM on the dataset using Prompt A or Prompt B:

```bash
# Run with Prompt A
python3 main.py --prompt A --n 300

# Run with Prompt B
python3 main.py --prompt B --n 300

# Run with both prompts
python3 main.py --prompt both --n 300
```

Key options:
- `--prompt`: `A`, `B`, or `both`
- `--n`: number of examples to process
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed examples are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `idx`, `commit_id`, `target`, `predicted`, `verdict_str`, `match`, `prompt_sent`, `raw_response`, and `llm_response_time`.

---

## Step 2 — Evaluate

Compute all metrics from the outputs generated in Step 1:

```bash
python3 evaluator.py --prompt A
python3 evaluator.py --prompt B
python3 evaluator.py --prompt both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A
└── results_B.jsonl    # aggregate + per-instance results for Prompt B
```

---

## Metrics

**Instance-level**: accuracy, precision, recall, F1, FPR, MCC.

**Pair-level** (paired vulnerable/clean functions from the same commit):
- **PC**: both functions correctly classified.
- **PV**: both functions predicted vulnerable.
- **PB**: both functions predicted benign.
- **PR**: predictions are reversed: the vulnerable function is predicted benign, and the benign function is predicted vulnerable.
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.
