# Testora — LLM Replacement Study

This folder contains an LLM replacement study for [Testora](https://arxiv.org/abs/2503.18597) (ICSE 2026). We replace the original three-stage regression-detection pipeline with a single Claude Sonnet 4.6 call and evaluate on the same benchmark using the same metrics reported in the paper.

---

## Overview

### Original Testora Pipeline (three stages)

1. **Test generation** — An LLM generates Python test cases that exercise the code changed by the pull request, running against the pre-PR and post-PR commits.
2. **Test execution** — Generated tests are executed inside isolated Docker containers for each target project, collecting actual console output from both versions.
3. **Classification** — A second LLM call compares the actual execution outputs and classifies the behavioral difference as *intended* (expected consequence of the PR) or *unintended* (regression or side effect not mentioned by the developer).

The paper uses GPT-4o-mini with a multi-question prompting strategy and evaluates across 46 manually labeled PRs (RQ3) and 30 real-world regressions detected in the wild (RQ1).

### Our Approach (single LLM call)

We collapse all three stages into one Claude Sonnet 4.6 call. Given the PR metadata (title, description, unified diff, commit messages, discussion comments), the model is asked to:

1. Generate a self-contained Python test case that exposes the behavioral difference.
2. Predict the test's console output before the PR is applied.
3. Predict the test's console output after the PR is applied.
4. Classify the behavioral difference as `"intended"` or `"unintended"`.
5. Explain the verdict in one to three sentences.

No Docker, no code execution, no multi-step pipeline. The model reasons about behavior purely from the diff and natural language context.

Two prompt strategies are compared:

- **Prompt A (Black-box):** States the task and output schema; no reasoning guidance. The model is free to approach the problem however it chooses.
- **Prompt B (Step-by-step):** Adds a `### Steps` section with 7 explicit reasoning steps — parse the diff, characterize each change semantically, construct a targeted test, predict outputs for both versions, classify, explain, and compile the JSON output.

---

## Why These Datasets?

**RQ3 — Classification accuracy (46 PRs):**  
The 46 PRs come from the paper's ground truth, where human annotators verified each differentiating test and labelled the behavioral change as `intended`, `unintended`, or `coincidental fix`. This is the only dataset with human-verified labels, making it the appropriate benchmark for classification accuracy.

We treat `coincidental fix` as `unintended` (positive class), consistent with the paper's intent: a coincidental fix is a behavioral change that the developer did not plan for, regardless of whether it happens to be correct. 23 of the 46 PRs are unintended, 23 are intended — a balanced split.

**RQ1 — Real-world detection rate (30 PRs):**  
These 30 PRs were identified by running the original Testora pipeline on real repositories and then manually verifying by the authors that the behavioral change was indeed unintended. All 30 are unintended by definition. Since there are no true negatives in this set, only Recall is meaningful (Precision is always 1.0). This dataset tests whether our single-call approach can replicate the original pipeline's 100% detection rate in practice.

**Overlap:** All 20 currently available RQ1 PRs are a subset of the 46 RQ3 PRs. We process each PR only once and tag it with its membership list (`["rq3"]`, `["rq1"]`, or `["rq3", "rq1"]`). The evaluator routes each record to the correct metric section.

---

## Prerequisites

```bash
pip install anthropic PyGithub
```

Set the Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

---

## Step 1 — Get the Dataset

The `data/` folder is not included in the repository. It must be downloaded from the official Testora GitHub release.

### Option A — Automated (recommended)

```bash
python3 download_dataset.py
```

This downloads and extracts `data_03_2025.tar.gz` from the Testora GitHub releases into `../data/`, then verifies the extraction. It provides:

- `../data/ground_truth/` — 46 JSON files with human-verified differentiating-test labels (RQ3)
- `../data/real-world_problems.csv` — 30 real-world unintended behavioral changes (RQ1)

### Option B — Manual

Run these commands from the **project root** (`Testora/`):

```bash
wget https://github.com/michaelpradel/Testora/releases/download/data_03_2025/data_03_2025.tar.gz
tar -xf data_03_2025.tar.gz
```

---

## Step 2 — Provide a GitHub Token (optional but recommended)

`main.py` automatically pulls any missing PR data before starting inference via `ensure_data_available()`. To enable this, create a GitHub personal access token (free, requires only `public_repo` scope) and save it:

```bash
echo "ghp_YOUR_TOKEN_HERE" > .github_token
```

**Without a token:** `main.py` proceeds with the 46 RQ3 PRs already on disk and warns about the 10 missing RQ1-only PRs. RQ1 evaluation will then cover 20/30 PRs instead of 30/30.

If you prefer to pre-fetch all PR data before running inference, you can also run `pull_prs.py` directly:

```bash
python3 pull_prs.py
```

---

## Step 3 — Run Inference

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 5.0
```

**Behavior:**

- Processes all 56 PRs (46 RQ3 + 10 RQ1-only) in a single run.
- Runs Prompt A and Prompt B on each PR.
- Each PR is processed exactly once; its output record is tagged with all applicable dataset memberships.
- Stops when the budget is exhausted. Re-running resumes automatically — completed PRs are skipped, partially completed PRs (one prompt done) are finished first before new ones are started.
- If JSON parsing fails, a `_fix_json_newlines` repair step is attempted, followed by a regex fallback that extracts the verdict directly. Only if no verdict can be extracted at all is a `parse_failed` sentinel written, which excludes the record from evaluation without corrupting metrics.

**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per PR: `project`, `pr_number`, `datasets`, `verdict`, `test_case`, `predicted_output_before_pr`, `predicted_output_after_pr`, `explanation` |
| `outputs_B.jsonl` | Same for Prompt B |

Records that exceeded the 50 KB threshold are saved as individual files: `{project}_{pr_number}_promptA.json`.

**Estimated cost** (Claude Sonnet 4.6, $3/M input tokens, $15/M output tokens):

| Scope | Estimated cost |
|---|---|
| 46 RQ3 PRs, both prompts | ~$2.71 |
| 10 RQ1-only PRs, both prompts | ~$0.48 |
| All 56 PRs, both prompts | ~$3.19 |

---

## Step 4 — Evaluate

```bash
python3 evaluator.py
```

Reads all output records, splits them by dataset membership, and computes:

- **RQ3:** Precision, Recall, F1 (unintended as positive class), Accuracy
- **RQ1:** Detection Recall (detected / available), with paper coverage noted

Results are written to `results/results_A.jsonl` and `results/results_B.jsonl`. Line 1 of each file is the RQ3 aggregate, line 2 is the RQ1 aggregate, followed by per-PR detail rows.

---

## Ground Truth Details

**RQ3 labels** come from `../data/ground_truth/{project}/{pr_number}.json`. Each file lists `differentiating_tests`, each with a `label` field:

- `"unintended"` — a regression or side effect not aligned with the PR's stated purpose
- `"coincidental fix"` — a pre-existing bug that happened to be fixed as a side effect; treated as **unintended** (positive class) in our evaluation, consistent with the paper
- `"intended"` — a behavioral change that is a direct and expected consequence of the PR

A PR is classified as **unintended** if **any** of its differentiating test labels is `"unintended"` or `"coincidental fix"`.

**RQ1 labels** come from `../data/real-world_problems.csv`. All 30 entries are unintended by definition (either Regression or Coincidental fix), so only Recall is evaluated; Precision is always 1.0 since there are no intended PRs in this set.

---

## Results Comparison

Paper baseline (GPT-4o single-question, Table 5 / Table 2):

| Metric | Paper (46 PRs) | Ours Prompt A | Ours Prompt B |
|---|---|---|---|
| **RQ3 Precision** | 0.80 | 0.54 | 0.52 |
| **RQ3 Recall** | 0.64 | 0.08 | 0.04 |
| **RQ3 F1** | 0.71 | 0.16 | 0.08 |
| **RQ1 Recall** | 1.00 (30/30) | 0.10 (3/30) | 0.06(2/30) |


### Why our results are poor

The results reveal a consistent pattern: precision is moderate (~0.53) but recall is near zero (0.04–0.08 for RQ3, 0.06–0.10 for RQ1). The model is almost always predicting `"intended"` and rarely flagging anything as `"unintended"`. Several factors explain this:

**1. No code execution — the fundamental gap.**
The original Testora pipeline actually runs the generated tests against the pre-PR and post-PR commits, then hands the LLM a concrete pair of observed outputs to compare. The classification task becomes: "given that the output changed from X to Y, was that change intended?" — a much simpler question backed by direct evidence. Our model must both predict what the outputs would be and classify the difference, all from the diff alone. When it cannot confidently determine what changed at runtime, it defaults to `"intended"` rather than making an uncertain claim.

**2. Bias toward developer intent.**
Given a PR title and description explaining a clear goal, the model tends to interpret all observable behavioral changes as serving that goal. Coincidental fixes — 12 of the 23 unintended RQ3 PRs — are particularly affected: the PR is doing something legitimate, the diff looks purposeful, and the model classifies accordingly. The unintended side effect is invisible without running the code.

**3. Subtle regressions are prediction-hard.**
Many unintended changes involve edge cases: a previously accepted input type now raises an exception, a floating-point result shifts slightly, or a deprecated code path is silently removed. Detecting these requires calling the function with specific inputs and observing the difference. A model reasoning statically from the diff will miss them.

**4. RQ1 recall (0.06–0.10) is especially low.**
RQ1 PRs were originally detected by running the full pipeline on real repositories — cases where a behavioral change exists but is not obvious from reading the PR description. These are precisely the cases where execution evidence is most decisive and textual reasoning alone is weakest.

In summary, our single-call approach cannot replicate the execution-grounded signal that makes the original Testora classification reliable. Replacing the pipeline with static LLM reasoning eliminates the Docker infrastructure but sacrifices nearly all recall.
