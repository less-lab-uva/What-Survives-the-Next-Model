# Experiment Setup

**HoarePrompt: Structural Reasoning About Program Correctness in Natural Language**  
ICSE 2026 · DOI: 10.1145/3744916.3773206

Given a programming problem and candidate solution, the LLM classifies correctness using Prompt A and Prompt B, evaluated on accuracy and MCC.

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

The dataset is included at `dataset/CoCoClaNeL_experiments.json`. It contains 645 examples, each with a problem `description`, `generated_code`, ground-truth fields: `correct`, `test_passed`, `counterexample`, and metadata: `task_id`, `task_name`, `dataset`, `model`, `depth`, `hard`, `unique_id`.

---

## Step 1 — Run the Experiment

Run the LLM on the dataset using Prompt A or Prompt B:

```bash
# Run with Prompt A
python3 main.py --prompt A --n 645

# Run with Prompt B
python3 main.py --prompt B --n 645
```

Key options:
- `--prompt`: `A` or `B`
- `--n`: number of examples to process
- `--dataset`: dataset filename to use
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

Each line contains: `id`, `source_file`, `ground_truth`, `predicted`, `match`, `prompt_sent`, `raw_response`, and `llm_response_time`.

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

- **Accuracy**: overall fraction of correct verdicts.
- **Balanced Accuracy**: average of true positive rate and true negative rate — accounts for class imbalance.
- **MCC** (Matthews Correlation Coefficient): a single balanced metric ranging from −1 to +1 that accounts for all four confusion matrix cells.
- **avg_response_time**: mean LLM API response time in seconds, averaged across all processed examples.
