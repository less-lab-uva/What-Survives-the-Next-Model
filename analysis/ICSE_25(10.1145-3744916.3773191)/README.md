# Experiment Setup

**SecureReviewer: LLM-Based Automated Security Code Review**  
ICSE 2026 · DOI: 10.1145/3744916.3773191

Given a code patch, the LLM classifies the vulnerability type and generates a structured review using Prompt A and Prompt B, evaluated on detection accuracy and BLEU.

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

The dataset is included at `dataset/test.jsonl`. Each line is a JSON record with a code `patch` and ground-truth fields: `security_type`, `description`, `impact`, and `advice`.

---

## Step 1 — Run the Experiment

Run the LLM on the test set using Prompt A or Prompt B:

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
├── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `patch`, `predicted` (parsed JSON review), `reference` (ground truth), `prompt_sent`, `raw_response`, and `llm_response_time`.

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
├── results_B.jsonl    # aggregate + per-instance results for Prompt B
```

---

## Metrics

Three groups of metrics are reported:

**Issue Detection** (all examples, including `Non-Issue`):
- `accuracy`, `precision_macro`, `recall_macro`, `f1_macro` — computed via `sklearn` over the predicted vs. reference `Security Type` labels.

**Comment Generation** (security issues only — `Non-Issue` references excluded):
- **BLEU-4**: corpus-level BLEU over the concatenated `Description + Impact + Advice` fields.
- **SecureBLEU**: a weighted combination of per-field BLEU (30% security type match, 30% description, 20% impact, 20% advice) blended with a security keyword overlap ratio.
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.

