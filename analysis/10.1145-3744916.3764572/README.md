# Specine

Single-LLM-call recreation of **RQ1** (code-generation effectiveness — Pass@1 / AvgPassRatio)
from *Aligning Requirement for Large Language Model's Code Generation* (Specine, DOI
10.1145/3744916.3764572).

One call replaces Specine's whole specification-alignment pipeline: given a programming
problem, the oracle returns a full stdin->stdout program. Run for prompt A (black-box) and
prompt B (informed). Scored the way the paper scores — by running the generated program
against the problem's test cases.

## Prerequisites

- Python 3
- An Anthropic API key (`ANTHROPIC_API_KEY`) — for `main.py`

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Data

`inputs/<dataset>.jsonl` — the three benchmarks (apps, code_contests, xCodeEval) and their
`$15` down-sampled versions (`*.down_sampled_15usd.jsonl`). `main.py` reads the down-sampled
files (329 problems). Each record keeps `all_test_cases` — the gold for scoring, never sent
to the model.

**Reassemble the inputs first.** The `apps` and `code_contests` downsampled files are too large
for GitHub, so they're committed as split `*.part-*` chunks. Stitch them back into whole files
once after cloning:

```bash
python3 utils/assemble_inputs.py
```

(The full, non-downsampled benchmarks aren't committed; regenerate them with
`utils/build_inputs.py` + `utils/sample_to_budget.py` only if you need to re-sample.)

## Run

The script refuses to clobber outputs (fail-fast abort rather than overwrite). Back up or
remove any existing `outputs/output_*.jsonl` first, then:

```bash
ANTHROPIC_API_KEY=<your key> python3 main.py
```

## Outputs (one per prompt variant A/B)

- `outputs/output_{A,B}.jsonl` — predictions: `dataset, problem_id, code`
- `logs/log_{A,B}.jsonl` — raw per-call log: `dataset, problem_id, start_time, end_time, input_tokens, output_tokens, raw`
- `logs/failures_{A,B}.jsonl` — problems whose response couldn't be parsed (skipped)

## Evaluation

`evaluator.py` runs each generated program against its problem's `all_test_cases`
(stdin -> stdout) and reports Pass@1 / AvgPassRatio per dataset and overall.

⚠️ It **executes untrusted, LLM-generated code** as subprocesses — run it inside a
container/sandbox.

```bash
python3 evaluator.py        # results/results_{A,B}.json — Pass@1 / AvgPassRatio (A vs B)
python3 utils/usage.py      # logs/usage.json            — seconds elapsed + cost (A vs B)
```

## `utils/` (run from this directory)

Helper scripts kept separate from the core pipeline (`main.py`, `evaluator.py`). Paths are
fixed relative to this directory, so invoke them as `python3 utils/<script>.py`:

- `utils/sample_to_budget.py` — down-sample the benchmarks to a ~`$15` run → `*.down_sampled_15usd.jsonl`.
- `utils/estimate_cost.py` — project the run cost via the free `count_tokens` endpoint (no spend).
- `utils/prompt_generator.py` — regenerate `prompts/prompt_A.txt` + `prompt_B.txt` from the paper PDF + `prompts/meta_prompt.txt`.
- `utils/usage.py` — after a run, derive seconds + cost from the per-call logs → `logs/usage.json`.
