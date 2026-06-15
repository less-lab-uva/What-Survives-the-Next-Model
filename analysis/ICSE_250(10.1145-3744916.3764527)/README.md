# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"Testora: Regression Testing with a Natural Language Oracle"**. The original paper proposes Testora, a three-stage pipeline that detects behavioral regressions in Python PRs: it generates test cases using an LLM, executes them against pre-PR and post-PR commits in Docker containers, and classifies the behavioral change as intended or unintended using a second LLM call. This reproduction replaces the full pipeline with a single Claude Sonnet 4.6 call per PR and evaluates it on the Testora benchmark using Precision, Recall, F1 (RQ3, 46 PRs) and Detection Recall (RQ1, 30 real-world regressions).

---

## Prerequisites

- Python 3.10+
- The `anthropic` and `PyGithub` Python packages
- A GitHub personal access token (for `pull_prs.py`)

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

Run the download script from this directory:

```bash
python3 download_dataset.py
```

This downloads the dataset archive from:

```text
https://github.com/michaelpradel/Testora/releases/download/data_03_2025/data_03_2025.tar.gz
```

and extracts it one level above this directory, creating:

```text
../data/ground_truth/             46 PR subdirectories with human-verified labels (RQ3)
../data/real-world_problems.csv   30 real-world unintended behavioral changes (RQ1)
```

Dataset details:

```text
RQ3   46 PRs labeled as intended or unintended (23 unintended, 23 intended)
RQ1   30 real-world PRs, all unintended (20 overlap with RQ3; 10 RQ1-exclusive)
```

The original paper is available at:

```text
https://arxiv.org/abs/2503.18597
```

---

## Step 2 — Pull PR data

`main.py` reads PR content (diff, title, description, commit messages, discussion comments) from:

```text
../data/pulled_prs/ground_truth/{project}/{pr_number}.json
```

Populate this directory by running:

```bash
python3 pull_prs.py
```

`pull_prs.py` requires a GitHub personal access token with `public_repo` scope. Create the token file in this directory:

```bash
echo "ghp_YOUR_TOKEN_HERE" > .github_token
```

The script fetches all 56 PRs (46 RQ3 + 10 RQ1-exclusive) via the GitHub API and saves each to:

```text
../data/pulled_prs/ground_truth/{project}/{pr_number}.json
```

The script is resumable — already-fetched PRs are skipped.

---

## Step 3 — Run the LLM

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 5.0
```

`main.py` reads:

```text
../data/pulled_prs/ground_truth/
../data/ground_truth/
../data/real-world_problems.csv
prompts/promptA.py
prompts/promptB.py
```

It runs Prompt A and Prompt B on every PR found in `../data/pulled_prs/ground_truth/`, annotating each PR with its dataset membership (`rq3`, `rq1`, or both). The budget is checked before every API call. Re-running continues from where it stopped without re-calling the LLM for already completed PRs.

If a `.github_token` file is present when `main.py` runs, any still-missing PRs are pulled automatically before inference begins.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

PRs whose serialised output exceeds 50 KB are saved to separate files instead:

```text
outputs/{project}_{pr_number}_promptA.json
outputs/{project}_{pr_number}_promptB.json
```

Token logs are saved to:

```text
outputs/tokens_A.jsonl
outputs/tokens_B.jsonl
```

---

## Step 4 — Evaluate

```bash
python3 evaluator.py
```

`evaluator.py` reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
outputs/{project}_{pr_number}_prompt{A|B}.json   (for large-output PRs)
../data/ground_truth/
../data/real-world_problems.csv
```

It computes RQ3 and RQ1 metrics for both prompts and prints a summary.

Results are saved to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

Line 1 of each file contains the RQ3 aggregate. Line 2 contains the RQ1 aggregate. Subsequent lines contain per-PR results.

---

## Metrics

RQ3 (classification of 46 PRs as intended or unintended):

```text
Precision  -> TP / (TP + FP)   unintended = positive class
Recall     -> TP / (TP + FN)
F1         -> harmonic mean of Precision and Recall
Accuracy   -> (TP + TN) / total
```

A PR is a true positive if the model predicts `unintended` and the ground-truth label is `unintended` or `coincidental fix`.

RQ1 (detection of unintended behaviors across up to 30 real-world PRs):

```text
Detection Recall  -> correctly identified unintended PRs / total available PRs
```

All 30 RQ1 PRs are unintended by definition, so only Recall is evaluated; Precision is always 1.0.

---
