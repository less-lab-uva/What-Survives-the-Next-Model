# Experiment Setup

This project generates code solutions for HumanEval and LiveCodeBench problems using Prompt A or Prompt B, then evaluates the generated code by running test cases.

**Paper:** EnsLLM: Enhancing LLM Code Generation with Ensembles: A Similarity-Based Selection Approach  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3773143

---

## Prerequisites

- Python 3.8+

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Step 1 — Download the Datasets

Download HumanEval and LiveCodeBench into the local `data/` directory:

```bash
python download_dataset.py
```

This saves all files under `./data/`:
```
data/
├── hf_cache/    # HumanEval (164 problems)
└── lcb/         # LiveCodeBench (511 problems)
```

---

## Step 2 — Run the Experiment

Generate code solutions using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --n 450
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across benchmarks |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the generated code, the raw model response, and response time.

---

## Step 3 — Evaluate

Score the generated code by executing it against HumanEval and LiveCodeBench test suites:

```bash
python evaluator.py --variant both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A (includes avg response time)
└── results_B.jsonl    # aggregate + per-instance results for Prompt B (includes avg response time)
```

---

## Metric

We report **Pass@1**: a problem is considered solved if the generated code passes all test cases on the first attempt. This matches the metric used in the paper.
