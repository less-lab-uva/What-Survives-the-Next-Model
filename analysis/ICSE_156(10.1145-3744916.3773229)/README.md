# ConfuGuard

Single-LLM-call recreation of **EQ5 / Table 5** (package-confusion / typosquat detection
accuracy) from *ConfuGuard* (DOI 10.1145/3744916.3773229).

One call replaces ConfuGuard's whole pipeline: given a suspected package (name + registry
[+ namespace]), the oracle returns a binary `{"is_typosquat": true|false}`. Run for prompt A
(black-box) and prompt B (informed). Scored per dataset {ConfuDB, NeupaneDB} × per category
{active, stealthy, benign} + overall, positive class = threat.

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`) — for `main.py`

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Data

`inputs/` holds the three full datasets **and** their `$15`-budget down-sampled versions:

- `inputs/{ConfuDB,NeupaneDB_real_malware,NeupaneDB_no_malware}.csv` — full (2361 / 1239 / 626)
- `inputs/*.down_sampled_15usd.csv` — stratified `$15`-budget sample

`main.py` reads the **down-sampled** files. Ground-truth / target / provenance columns are
dropped before the row is sent to the model (see the comment in `main.py`); gold is recovered
at scoring time by joining back to the source CSV.

## Run

The script refuses to clobber outputs (fail-fast abort rather than overwrite). Back up or remove
any existing `outputs/output_*.jsonl` / `logs/log_*.jsonl` first, then:

```bash
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one per prompt variant A/B; every row tagged with its `dataset`)

- `outputs/output_{A,B}.jsonl` — predictions: `dataset, <kept input columns>, is_typosquat`
- `logs/log_{A,B}.jsonl` — raw per-call log: `dataset, package, start_time, end_time, input_tokens, output_tokens, model, raw`

## Evaluation

After a run, the evaluator reads the outputs/logs (fail-fast, won't overwrite):

```bash
python3 evaluator.py        # results/results_{A,B}.json — Table 5 per dataset/category (one file per prompt)
```
