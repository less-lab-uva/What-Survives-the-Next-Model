# Experiment Setup

This project generates LTL formulas from natural-language requirements using Prompt A or Prompt B, then evaluates them by semantic equivalence against reference formulas via the Spot model checker.

**Paper:** Automating Requirements Formalization: Using LLMs and Low-Complexity Distinguishing Traces for Semantic Validation  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3787815

---

## Prerequisites

- Python 3.8+
- [Spot](https://spot.lre.epita.fr/) LTL model checker with Python bindings (`import spot`)

Install Python dependencies:
```bash
pip install -r requirements.txt
```

Spot is **not** available via pip. Install it via conda:
```bash
conda install -c conda-forge spot
```
or follow the [Spot installation guide](https://spot.lre.epita.fr/install.html).

---

## Datasets

The benchmark data is included in this repository under `data/`:

```
data/
├── fret_specs/          # per-benchmark FRETish requirement specs
│   ├── deepstl-test/
│   ├── FSM-AP/
│   ├── FSM-S/
│   ├── REG/
│   ├── RobotExplain/
│   └── Ventilator/
└── metadata/            # LTL templates and proxy dictionaries
```

---

## Step 1 — Run the Experiment

Generate LTL formulas using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --n 50
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across benchmarks |
| `--seed` | `42` | Random seed for stratified sampling |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the generated LTL formula, the raw model response, and response time.

---

## Step 2 — Evaluate

Score the generated formulas via Spot semantic equivalence:

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

We report **pass@10**: a requirement is considered solved if any of its 10 generated LTL formulas is semantically equivalent to a plausible reference label, checked via Spot automaton equivalence. This matches the paper's evaluation protocol.
