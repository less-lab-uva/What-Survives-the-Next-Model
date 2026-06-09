# Toxicity Ahead

Single-LLM-call recreation of **RQ2** ("Can LLMs predict conversational derailment on
GitHub?") from *Toxicity Ahead* (DOI 10.1145/3744916.3787839).

One call per thread (collapsing the paper's two-stage pipeline) takes the pre-toxicity
transcript and returns a derailment probability. Run for prompt A (black-box) and prompt B
(informed). Scored by precision / recall / F1 at decision thresholds (headline F1@0.3).

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`) — for `main.py`

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Data

`inputs/our-dataset.csv` — the curated GitHub-thread dataset (RQ2). `main.py` builds each
thread's pre-toxicity transcript (up to the first toxic comment, newest-first, capped at 3000
words) and forecasts on that; the toxic label is the gold and is never sent to the model.

## Run

The script refuses to clobber outputs (fail-fast abort rather than overwrite). Back up or
remove any existing `outputs/output_*.jsonl` / `logs/log_*.jsonl` first, then:

```bash
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one per prompt variant A/B)

- `outputs/output_{A,B}.jsonl` — predictions: `issue_id, pred_score, true_label`
- `logs/log_{A,B}.jsonl` — raw per-call log: `issue_id, start_time, end_time, input_tokens, output_tokens, model`

## Evaluation

After a run, two processors read the outputs/logs (both fail-fast, won't overwrite):

```bash
python3 evaluator.py        # results/results_{A,B}.json — P/R/F1 at all thresholds (one file per prompt)
python3 utils/usage.py      # logs/usage.json            — seconds elapsed + cost (A vs B)
```

## `utils/` (run from this directory)

Helper scripts kept separate from the core pipeline (`main.py`, `evaluator.py`). Paths are
fixed relative to this directory, so invoke them as `python3 utils/<script>.py`:

- `utils/prompt_generator.py` — regenerate `prompts/prompt_A.txt` + `prompt_B.txt` from the paper PDF + `prompts/meta_prompt.txt`.
- `utils/estimate_cost.py` — project the run cost via the free `count_tokens` endpoint (no spend) → `logs/cost_estimate.json`.
- `utils/usage.py` — after a run, derive seconds + cost from the per-call logs → `logs/usage.json`.
