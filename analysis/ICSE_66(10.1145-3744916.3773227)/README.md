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

## Step 2 — Run the Experiment

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

## Step 3 — Set Up ExecEval

The evaluator uses ExecEval as the code execution engine to run generated patches against hidden unit tests. ExecEval runs inside Docker and supports all 11 programming languages used in the benchmark.

Build the ExecEval Docker image. This only needs to be done once.

```bash
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

## Step 5 — Evaluate

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

## Metric

We report **Pass@1**: for each bug, one patch is generated and evaluated. A bug is considered fixed if the generated patch passes all hidden unit tests.

The paper being replicated (LANTERN) reports **Pass@10 with n=20**, where 20 patches are generated per bug and the probability that at least one of the top 10 passes is computed using the unbiased estimator:

```
Pass@10 = 1 - C(n-c, k) / C(n, k)    where n=20, k=10, c=correct patches
```

Our Pass@1 results are therefore a conservative lower bound relative to the paper's Pass@10 numbers. Our approach uses a single API call per bug compared to the paper's multi-agent pipeline with 20 samples and multiple translation iterations.
