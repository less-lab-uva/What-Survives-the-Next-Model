# Experiment Setup

This project generates APR patches for xCodeEval instances using Prompt A or Prompt B, then evaluates the generated patches with [ExecEval](https://github.com/ntunlp/ExecEval).

---

## Prerequisites

- Docker (verified with Docker 29.1.4)
- Python 3.8+
- The following Python packages: `anthropic`, `requests`, `huggingface_hub`

Install Python dependencies:
```bash
pip install anthropic requests huggingface_hub
```

---

## Step 1 — Download the Dataset

Download the xCodeEval validation split, problem descriptions, and unit test database:

```bash
python3 download_dataset.py
```

This saves all files under `./xCodeEval/`:
```
xCodeEval/
├── apr/
│   └── validation/       # 11 language JSONL files (one per language)
├── problem_descriptions.jsonl
└── unittest_db.json
```

---

## Step 2 — Run the Pass@1 Experiment

Generate fixed patches using either Prompt A (black-box) or Prompt B (informed-technique). The script uses a stratified 5% random sample from each language with seed 42.

```bash
# Set your Anthropic API key first
export ANTHROPIC_API_KEY=your_key_here

# Run with Prompt A
python3 main.py A

# Run with Prompt B
python3 main.py B
```

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the generated fix alongside the original bug metadata.

The current script does not take start/end indices from the command line. To change the sample size, edit the sampling line in `main.py`.

---

## Step 2b — Run the Pass@5 Experiment

Because the original paper reports Pass@10 with multiple samples per bug, we also ran a smaller multi-sample setting. We used **Pass@5** instead of Pass@10 to control API cost while still checking whether additional candidates improve the single-prompt baseline.

The Pass@5 experiment uses `main_pass5.py`, which generates five candidate repairs per selected bug.

```bash
python3 main_pass5.py A
python3 main_pass5.py B
```

Note: the checked-in `main_pass5.py` and `evaluator_pass5.py` are currently configured with `RUN_SUFFIX = "csharp_cpp_java"` and `LANGUAGES = ["C#", "C++", "Java"]` for the final follow-up run. The canonical checked-in `outputs_*_pass5.jsonl` and `results_*_pass5.jsonl` files already include the merged follow-up results.

The Pass@5 runs were selected as follows:

- First, we ran Pass@1 for all languages and both prompt variants.
- For languages where Pass@1 already outperformed the paper baseline, we did not prioritize additional Pass@5 runs. These were Go, Javascript, PHP, Ruby, and Rust.
- For Prompt A, then we ran pass@5 on the rest of the languages.
- For Prompt B, no language outperformed the paper baseline under Pass@1. Therefore, we evaluated Prompt B with Pass@5 on all 11 languages.

The Pass@5 outputs are saved under:

```
outputs/
├── outputs_A_pass5.jsonl
└── outputs_B_pass5.jsonl
```


---

## Step 3 — Set Up ExecEval

The evaluator uses ExecEval as the code execution engine to run generated patches against hidden unit tests. ExecEval runs inside Docker and supports all 11 programming languages used in the benchmark.

Build the ExecEval Docker image. This only needs to be done once.

```bash
git clone https://github.com/ntunlp/ExecEval.git ExecEval
cd ExecEval
docker build . -t exec-eval:1.0
```

The build may take several minutes as it installs all language runtimes inside the container.

---

## Step 4 — Start ExecEval

Before running the evaluator, start the ExecEval container. Keep this terminal open, then run `evaluator.py` from a separate terminal.

```bash
docker run -it -p 5000:5000 -e NUM_WORKERS=5 exec-eval:1.0
```

Wait until you see:
```
[INFO] Listening at: http://0.0.0.0:5000
```
---

## Step 5 — Evaluate Pass@1

Make sure ExecEval is running (Step 4), then open a separate terminal and run the evaluator:

```bash
python3 evaluator.py A
python3 evaluator.py B
```

The evaluator sends each generated patch to ExecEval, runs it against all hidden unit tests, and computes **Pass@1** — the proportion of bugs where the generated fix passes all test cases.

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A
├── results_B.jsonl    # aggregate + per-instance results for Prompt B
```

---

## Step 5b — Evaluate Pass@5

With ExecEval running, evaluate the multi-candidate outputs:

```bash
python3 evaluator_pass5.py A
python3 evaluator_pass5.py B
```

The Pass@5 evaluator groups five candidate repairs by bug. A bug is counted as fixed if at least one of its five candidates passes all hidden unit tests.

The Pass@5 results are saved to:

```
results/
├── results_A_pass5.jsonl
└── results_B_pass5.jsonl
```


---

## Metrics

We report both **Pass@1** and **Pass@5**.

**Pass@1**: for each bug, one patch is generated and evaluated. A bug is considered fixed if the generated patch passes all hidden unit tests.

**Pass@5**: for each selected bug, five candidate patches are generated. A bug is considered fixed if any one of the five candidates passes all hidden unit tests.

The paper being replaced (LANTERN) reports **Pass@10 with n=20**, where 20 patches are generated per bug and the probability that at least one of the top 10 passes is computed using the unbiased estimator:

```
Pass@10 = 1 - C(n-c, k) / C(n, k)    where n=20, k=10, c=correct patches
```

Our Pass@1 results are therefore a conservative lower bound relative to the paper's Pass@10 numbers. If a language already outperforms the paper baseline with only one generated candidate, then generating 10 or 20 candidates is unnecessary for showing that the single-prompt approach is competitive on that language. Pass@5 is a cost-aware intermediate setting for the remaining cases: it tests whether a small number of additional candidates is enough to close the gap without paying the much higher cost of the paper's multi-agent pipeline with 20 samples and multiple translation/refinement iterations.

---

## Current Result Files

The current repository contains:

```
results/
├── results_A.jsonl                         # Prompt A Pass@1
├── results_B.jsonl                         # Prompt B Pass@1
├── results_A_pass5.jsonl                   # Prompt A Pass@5
├── results_B_pass5.jsonl                   # Prompt B Pass@5
```

The corresponding outputs are:

```
outputs/
├── outputs_A.jsonl
├── outputs_B.jsonl
├── outputs_A_pass5.jsonl
├── outputs_B_pass5.jsonl
```
