# ConfuGuard

Single-LLM-call recreation of **EQ5 / Table 5** ("baseline comparison": package-confusion /
typosquat detection accuracy) from *ConfuGuard* (DOI 10.1145/3744916.3773229).

One call replaces ConfuGuard's whole pipeline: given a suspected package (name + registry
[+ namespace]), the oracle returns a binary `{"is_typosquat": true|false}`. Run for prompt A
(black-box) and prompt B (informed). Scored per dataset {ConfuDB, NeupaneDB} × per category
{active, stealthy, benign} + overall, positive class = threat.

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Data

`inputs/` holds the three full datasets **and** their `$15`-budget down-sampled versions:

- `inputs/{ConfuDB,NeupaneDB_real_malware,NeupaneDB_no_malware}.csv` — full (2361 / 1239 / 626)
- `inputs/*.down_sampled_15usd.csv` — stratified random sample produced by `utils/sample_to_budget.py`

`main.py` and `evaluator.py` read the **down-sampled** files (the budget run). Ground-truth /
target / provenance columns are dropped before the row is sent to the model (see the comment in
`main.py`); gold is recovered later by joining back on the kept columns.

## Run

The scripts refuse to clobber outputs (fail-fast abort rather than overwrite). Clear or back up
any existing `outputs/oracle-*.csv` / `outputs/log-*.csv` first, then:

```bash
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one of each per prompt variant a/b × dataset; names mirror the down-sampled inputs)

- `outputs/oracle-claude-sonnet-4-6-{a,b}-<dataset>.down_sampled_15usd.csv` — predictions (kept input columns + `is_typosquat`)
- `outputs/log-claude-sonnet-4-6-{a,b}-<dataset>.down_sampled_15usd.csv` — raw per-call log (`package, start_time, end_time, input_tokens, output_tokens, model, raw`)

## Evaluation

After a run, two processors read `outputs/` (both fail-fast, won't overwrite):

```bash
python3 evaluator.py        # results/metrics.json — Table 5 (A vs B, per dataset/category)
python3 utils/usage.py      # results/usage.json   — seconds elapsed + cost (A vs B)
```

## `utils/` (run from this directory)

Helper scripts kept separate from the core pipeline (`main.py`, `evaluator.py`). Paths are
fixed relative to this directory, so invoke them as `python3 utils/<script>.py`:

- `utils/prompt_generator.py` — generate `prompts/prompt_A.txt` + `prompt_B.txt` from the paper PDF + `prompts/meta_prompt.txt`.
- `utils/estimate_cost.py` — project the full-run cost via the free `count_tokens` endpoint (no spend).
- `utils/sample_to_budget.py` — down-sample the datasets to a ~$15 run; writes the `*.down_sampled_15usd.csv` files + `results/down_sample_report.json` (% kept, flags if < 10%).
- `utils/usage.py` — after a run, derive seconds + cost from the per-call logs → `results/usage.json`.
