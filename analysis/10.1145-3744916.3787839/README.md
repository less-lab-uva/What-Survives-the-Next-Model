# Toxicity Ahead

Single-LLM-call recreation of **RQ2** ("Can LLMs predict conversational derailment on
GitHub?") from *Toxicity Ahead* (DOI 10.1145/3744916.3787839). 

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`)

## Run

Initialize the environment.
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

The script refuses to clobber outputs (it fail-fast aborts rather than overwrite). To run
it for yourself, back up the existing output files or delete them if they're not
important, then:

```bash
# back up or remove any existing outputs/oracle-*-our.csv and outputs/log-*-our.csv first
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one of each per prompt variant a/b)

- `outputs/oracle-claude-sonnet-4-6-{a,b}-our.csv` — predictions: `issue_id, pred_score, true_label`
- `outputs/log-claude-sonnet-4-6-{a,b}-our.csv` — raw per-call log: `issue_id, start_time, end_time, input_tokens, output_tokens, model`

## Evaluation

After a run, two processors read `outputs/` (both fail-fast, won't overwrite):

```bash
python3 evaluator.py        # results/metrics.json — P/R/F1 at all thresholds (A vs B)
python3 utils/usage.py      # results/usage.json   — seconds elapsed + cost (A vs B)
```

## `utils/` (run from this directory)

Helper scripts kept separate from the core pipeline (`main.py`, `evaluator.py`). Paths are
fixed relative to this directory, so invoke them as `python3 utils/<script>.py`:

- `utils/prompt_generator.py` — regenerate `prompts/prompt_A.txt` + `prompt_B.txt` from the paper PDF + `prompts/meta_prompt.txt`.
- `utils/estimate_cost.py` — project the run cost via the free `count_tokens` endpoint (no spend).
- `utils/usage.py` — after a run, derive seconds + cost from the per-call logs → `results/usage.json`.