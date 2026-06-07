# Experiment Setup

This project generates LTL (Linear Temporal Logic) formulas from natural language specifications using Prompt A or Prompt B, then evaluates the generated formulas for semantic equivalence against ground truth using the Spot model checker.

**Paper:** ADARULE: LLM-Driven Natural Language to LTL Conversion via Pattern-Adaptive Rule Induction  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3787821

---

## Prerequisites

- Python 3.8+
- Spot LTL model checker: `conda install -c conda-forge spot`

Install remaining Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Dataset

All datasets are in `data/` 

| File | Split | Samples |
|---|---|---|
| `valid_final_100.xlsx` | synthnl | 100 |
| `valid_calibration_AP_100.xlsx` | confonl | 100 |
| `valid_lang2ltl1_100.xlsx` | langnl | 100 |
| `valid_nl2spec_18.xlsx` | specnl | 18 |
| **Total** | | **318** |

---

## Step 1 — Run the Experiment

Generate LTL formulas using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N]
```

To replicate our results, run:

```bash
python main.py --variant both --n 318
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across all 4 datasets |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`.

---

## Step 2 — Evaluate

Score the generated LTL formulas using Spot semantic equivalence:

```bash
python evaluator.py --variant both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A
└── results_B.jsonl    # aggregate + per-instance results for Prompt B
```

---

## Metric

We report **accuracy**: the proportion of generated LTL formulas that are semantically equivalent to the ground truth, verified using the Spot model checker (`spot.are_equivalent`).
