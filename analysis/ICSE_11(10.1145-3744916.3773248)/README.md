# Experiment Setup

This project generates anomaly-detection predictions for log datasets using Prompt A or Prompt B, then evaluates them by F1-score on the anomaly class.

**Paper:** Knowledge-Augmented Log Anomaly Detection with Large Language Models  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3773248

---

## Prerequisites

- Python 3.8+

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Step 1 — Download the Datasets


Download the datasets from [Zenodo](https://doi.org/10.5281/zenodo.XXXXXXX) *(placeholder — link to be updated)* and place them under `data/` with the following structure:

```
data/
├── BGL/
│   └── 100l_BGL.csv
├── Spirit/
│   └── 100l_Spirit.csv
├── Thunderbird/
│   └── 200l_Thunderbird.csv
├── HDFS/
│   └── HDFS.csv
├── hadoop2/
│   └── hadoop2.csv
├── hadoop3/
│   └── hadoop3.csv
├── spark/
│   └── spark2.csv
└── spark3/
    └── spark3.csv
```


---

## Step 2 — Run the Experiment

Generate anomaly predictions using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --n 500
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across sub-datasets |
| `--seed` | `42` | Random seed for stratified sampling |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the predicted label, the raw model response, and response time.

---

## Step 3 — Evaluate

Score the predictions against ground-truth labels:

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

We report **F1-score** on the anomaly class, computed per sub-dataset and overall. This matches the metric used in the paper.
