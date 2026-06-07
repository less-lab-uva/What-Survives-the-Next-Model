# Experiment Setup

**TestWeaver: Execution-aware, Feedback-driven Regression Testing Generation with Large Language Models**  
ICSE 2026 · DOI: 10.1145/3744916.3787805

Given a Python module name and its source code, the LLM generates pytest tests using Prompt A and Prompt B, evaluated on line coverage, branch coverage, and combined line+branch coverage.

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

The dataset (382 MB — not included in this folder) is the CodaMOSA `test-apps` corpus from the TestWeaver repository. Download and extract it from Zenodo with:

```bash
python3 download_dataset.py <zenodo_url>
```

This places it at `dataset/TestWeaver/codamosa/replication/test-apps/`, which is where `main.py` and `evaluator.py` expect to find it.

---

## Step 1 — Run the Experiment

Run the LLM on a random sample of Python modules using Prompt A or Prompt B:

```bash
# Run with Prompt A
python3 main.py --prompt A --n 425

# Run with Prompt B
python3 main.py --prompt B --n 425

# Run with both prompts
python3 main.py --prompt both --n 425
```

Key options:
- `--prompt`: `A`, `B`, or `both`
- `--n`: number of modules to process
- `--seed`: random seed for sampling
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed modules are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `id`, `source_file`, `source_file_abs`, `d`, `tests`, `n_tests_generated`, `prompt_sent`, `raw_response`, and `llm_response_time`.

---

## Step 2 — Evaluate

Measure line, branch, and line+branch coverage for each set of generated tests:

```bash
python3 evaluator.py --prompt A
python3 evaluator.py --prompt B
python3 evaluator.py --prompt both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-module results for Prompt A
└── results_B.jsonl    # aggregate + per-module results for Prompt B
```

---

## Metrics

- **line_coverage**: fraction of source lines executed.
- **branch_coverage**: fraction of branches covered via.
- **line_branch_coverage**: combined metric.

All three are also reported stratified by file size (low: 0–150 lines, mid: 151–500, high: 501–1100).
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.
