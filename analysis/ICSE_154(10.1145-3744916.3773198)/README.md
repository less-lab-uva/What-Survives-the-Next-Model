# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"LASiR: LLM-Aided Signature Replay Vulnerability Detection in Smart Contracts"**. The original paper proposes LASiR, a three-phase pipeline that uses Slither to build a Program Dependence Graph, then applies three sequential LLM calls (slicing, inspection, path reachability) combined with symbolic execution to detect Signature Replay Vulnerabilities (SRVs) in Solidity contracts. This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per contract and evaluates it on a 10% stratified sample of the DB2 dataset using Precision, Recall, F1, and Accuracy.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package
- `git` on PATH (used by `fetch_contracts.py` to download contract source files)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Dataset

The dataset files are not included in this directory. Obtain them from the LASiR artifact:

```text
https://anonymous.4open.science/r/LASiR-B207/README.md
```

Two items are required from that artifact:

**1. Labeled CSV** — copy `Dataset/RQ2/Labeled_Data.csv` into this directory:

```text
Dataset/RQ2/Labeled_Data.csv
```

**2. Contract source files** — `fetch_contracts.py` downloads the Solidity `.sol` files from a pinned commit of the smart-contract-sanctuary GitHub repository:

```text
https://github.com/tintinweb/smart-contract-sanctuary-ethereum
```

To use it, first copy `Dataset/RQ1/DB1/Ethereum.csv` from the artifact into this directory:

```text
Dataset/RQ1/DB1/Ethereum.csv
```

Then run:

```bash
python3 fetch_contracts.py
```

This downloads the Ethereum contracts (covers 470 of the 500 DB2 contracts) and saves them to:

```text
Dataset/contracts/Ethereum/
```

The script is resumable — already-downloaded files are skipped. For full chain coverage (all 4 chains, ~450 MB), first copy all four chain CSV files from the artifact:

```text
Dataset/RQ1/DB1/Ethereum.csv
Dataset/RQ1/DB1/Polygon.csv
Dataset/RQ1/DB1/BSC.csv
Dataset/RQ1/DB1/Arbitrum.csv
```

Then run:

```bash
python3 fetch_contracts.py --all
```

Dataset details:

```text
DB2 (RQ2)   500 Solidity contracts: 72 positive (SRV present), 428 negative
Sample      50 contracts (10% stratified: ~7 positive, ~43 negative)
```

The sample is drawn once on first run and saved to `outputs/sample_ids.json` for reproducibility.

---

## Step 2 — Run the LLM

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 7.0
```

`main.py` reads:

```text
Dataset/RQ2/Labeled_Data.csv
Dataset/contracts/Ethereum/
prompts/promptA.py
prompts/promptB.py
```

It draws a stratified 10% sample (50 contracts) on the first run and runs Prompt A and Prompt B on each. Re-running continues from where it stopped without re-calling the LLM for already completed contracts.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
outputs/sample_ids.json
```

Token logs are saved to:

```text
outputs/tokens_A.jsonl
outputs/tokens_B.jsonl
```

---

## Step 3 — Evaluate

```bash
python3 evaluator.py
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

It computes Precision, Recall, F1, and Accuracy against the ground-truth labels embedded in the output files, prints a confusion matrix, and lists false positives and false negatives.

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the aggregate metrics and confusion matrix. Subsequent lines contain per-contract results.

---

## Metrics

The main metrics are:

```text
Precision  -> TP / (TP + FP)
Recall     -> TP / (TP + FN)
F1         -> harmonic mean of Precision and Recall
Accuracy   -> (TP + TN) / total
```

A contract is a true positive if the model predicts `"Exist": true` and the ground-truth label is `positive`. Evaluation is at the binary contract level — the five SRV sub-types (`X-CRA`, `X-PRA`, `CASR`, `SSMI`, `SMA`) are recorded but not evaluated against sub-type ground truth.

---
