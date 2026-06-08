# Experiment Setup

**Repair Ingredients Are All You Need: Improving Large Language Model-Based Program Repair via Repair Ingredients Search**  
ICSE 2026 · DOI: 10.1145/3744916.3764534

Given a buggy Java function and failing test from Defects4J, the LLM generates a fix using Prompt A and Prompt B, evaluated on patch plausibility.

---

## Prerequisites

- Python 3.8+
- Java 8
- [Defects4J](https://github.com/rjust/defects4j) CLI on `PATH`

Install Python dependencies:
```bash
pip install -r requirements.txt
```

Install Defects4J and ensure `defects4j` is on your `PATH`:
```bash
# Follow https://github.com/rjust/defects4j#requirements
```

Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Dataset

The dataset is included in `dataset/` with single-function and multi-function Defects4J cases.

---

## Step 1 — Run the Experiment

Run the LLM on the dataset using Prompt A or Prompt B:

```bash
# Run with Prompt A
python3 main.py --prompt A --n 100

# Run with Prompt B
python3 main.py --prompt B --n 100

# Run with both prompts
python3 main.py --prompt both --n 100
```

Key options:
- `--prompt`: `A`, `B`, or `both`
- `--n`: number of bugs to process
- `--seed`: random seed for sampling
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed bugs are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `bug_id`, `file_path`, `predicted_fix`, `prompt_sent`, `raw_response`, and `llm_response_time`.

---

## Step 2 — Evaluate

Validate each generated patch against Defects4J's relevant test suites:

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

Each patch receives one of: `PLAUSIBLE` (passes all trigger and relevant tests), `UNCOMPILABLE`, `TRIGGER_ERROR`, `RELEVANT_ERROR`, `TRIGGER_TIMEOUT`, `RELEVANT_TIMEOUT`, or `NO_D4J` (Defects4J not available).

The primary metric is **plausible patches**: the number of bugs for which the generated fix is `PLAUSIBLE`.
