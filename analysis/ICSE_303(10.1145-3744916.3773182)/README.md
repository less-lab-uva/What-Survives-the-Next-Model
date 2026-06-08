# Experiment Setup

**Repair Ingredients Are All You Need: Improving Large Language Model-Based Program Repair via Repair Ingredients Search**  
ICSE 2026 · DOI: 10.1145/3744916.3773182

Given a GitHub commit diff and message, the LLM classifies it as bug-introducing (BIC) or bug-fixing (BFC) using Prompt A and Prompt B, evaluated on precision, recall, and F1.

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

The dataset is included at `dataset/`. It contains:
- `dataset.jsonl` — pre-fetched commit diffs with BIC/BFC labels 

---

## Step 1 — Run the Experiment

Run the LLM on a random sample of commits using Prompt A or Prompt B:

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
- `--n`: number of commits to process
- `--seed`: random seed for sampling
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed commits are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `owner_repo`, `sha`, `split`, `true_label`, `pred_label`, `skipped`, `commit_message`, `diff_chars`, `prompt_sent`, `raw_response`, and `predicted`.

---

## Step 2 — Evaluate

Compute classification metrics from the outputs generated in Step 1:

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

- **Precision**: fraction of predicted BICs that are true BICs.
- **Recall**: fraction of true BICs that were correctly identified.
- **F1**: harmonic mean of precision and recall.
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.
