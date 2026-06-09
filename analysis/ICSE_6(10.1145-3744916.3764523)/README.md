# InferLog — LLM Replacement Study on HPC (Loghub-2k)

This folder contains a single-call LLM replacement study for the InferLog pipeline from the ICSE 2026 paper *"InferLog: Accelerating LLM Inference for Online Log Parsing via ICL-oriented Prefix Caching"* (Artifact: [github.com/wilhew/InferLog](https://github.com/wilhew/InferLog)).

---

## What the Original Pipeline Does

InferLog accelerates LLM-based online log parsing by maximising KV cache reuse across concurrent API requests. The pipeline works as follows:

1. **Preprocessing**: For each log message query, 5 in-context learning (ICL) examples are selected using a combination of DPP (Determinantal Point Process) diversity and kNN similarity on pre-computed embeddings.
2. **PAIR (Prefix-Aware ICL Refinement)**: The selected ICL examples are reordered to maximise shared prompt prefixes across simultaneous requests. This increases the KV cache hit rate in vLLM, reducing p95 end-to-end latency and improving throughput — without changing the accuracy of the parser itself.
3. **vLLM Serving**: 100 requests are dispatched concurrently using Qwen2.5-14B-Instruct served via a local vLLM instance.
4. **Postprocessing**: The LLM output is normalised by `correct_single_template()`, which handles whitespace, digit/hex/bool → `<*>` substitution, and multi-token consolidation.
5. **Configuration Tuning**: An AttMAML + SMBO loop (not part of log parsing itself) finds optimal vLLM scheduling hyperparameters per workload.

**Task**: Given a raw log `Content` string, produce a `log_template` by replacing all dynamic/variable tokens with `<*>`, leaving static text intact.

**Benchmark**: Loghub-2k — 16 datasets, 2000 logs each, ground truth in `{dataset}_2k.log_structured_corrected.csv`.

---

## What This Study Does

We replace the entire LLM inference pipeline (Qwen2.5-14B-Instruct + vLLM + PAIR + DPP/kNN ICL selection) with a **single Claude Sonnet 4.6 API call** per log message. Postprocessing (`correct_single_template`) is kept identical. Two prompt strategies are compared:

- **Prompt A (Black-box):** Describes only the output format and substitution rule — replace dynamic tokens with `<*>` — with 3 static few-shot examples. No guidance on methodology.
- **Prompt B (Informed):** Provides a step-by-step tokenisation and classification methodology: tokenise by delimiters, classify each token as static or dynamic (based on digit/IP/hex content, positional variance, and contextual stability), and apply the template. Includes the same 3 static few-shot examples.

Both prompts include 3 examples drawn from the HPC dataset (confirmed against the CSV ground truth).

---

## Why HPC

HPC is the shortest-average-message dataset in Loghub-2k (24.9 characters, ~6.2 tokens per log message). Running both prompts over all 2000 logs costs ~$13–15 with Sonnet 4.6, the lowest of all 16 datasets. This matters because:

- PTA, RTA, and GA require a full 2000-log run to be meaningful (partial runs give misleading template-level metrics).
- A full-dataset run is necessary to match the paper's evaluation conditions.

---

## Input Processing

The CSV file `data/HPC_2k.log_structured_corrected.csv` contains columns including `Content` (raw log message) and `EventTemplate` (ground truth template).

- **Input to LLM:** only the `Content` field — the raw log message text. The `EventTemplate` (ground truth) is never shown to the model.
- **JSON format sent to API:** `{"log_message": "<content>"}`
- **Post-processing:** after every LLM response, `correct_single_template()` is applied inline (same function as `src/prefix_cache_reusing/postprocess.py` in the original repo). This handles whitespace normalisation, digit/hex/boolean → `<*>` substitution, and multi-`<*>` consolidation.

---

## Environment Setup

### 1. Python version

Python 3.8 or later is required. Both `main.py` and `evaluator.py` use only standard library modules (`csv`, `json`, `pathlib`, `re`, etc.) plus the Anthropic SDK.

```bash
python3 --version   # should be >= 3.8
```

### 2. Install Python dependencies

All required packages are listed in `requirements.txt`. Install them with:

```bash
pip install -r requirements.txt
```

The only external dependency is the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python):

| Package | Version | Purpose |
|---|---|---|
| `anthropic` | >=0.40.0 | Claude API client used by `main.py` |

> **Note:** `pandas` is **not** required. The README previously listed it, but both `main.py` and `evaluator.py` read CSVs using Python's built-in `csv.DictReader`.

### 3. Set the API key

`main.py` reads the Anthropic API key from the environment. Export it before running:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

To persist it across sessions, add the line above to your `~/.bashrc` or `~/.bash_profile`.

---

## Dataset

The `data/` directory is **already included** in this repository. No download step is required.

The file `data/HPC_2k.log_structured_corrected.csv` was taken directly from the original InferLog repository:

> **InferLog** — [https://github.com/wiluen/InferLog](https://github.com/wiluen/InferLog) (`benchmark/dataset/HPC/HPC_2k.log_structured_corrected.csv`)

The original InferLog repo bundles all 16 Loghub-2k datasets (Android, Apache, BGL, HDFS, HPC, Hadoop, HealthApp, Linux, Mac, OpenSSH, OpenStack, Proxifier, Spark, Thunderbird, Windows, Zookeeper) under `benchmark/dataset/`. This study uses only the **HPC** subset (2 000 log lines), which has the shortest average message length (~25 chars) and therefore the lowest API cost for a full-dataset run.

The raw log files originally come from the **Loghub** benchmark:
> [https://github.com/logpai/loghub](https://github.com/logpai/loghub)

---

## Step 1 — Generate Templates

```bash
python3 main.py <budget_usd> [dataset_name]
```

Example:
```bash
python3 main.py 16.0 HPC
```


**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per log: `line_id`, `log_message`, `log_template`, `dataset`, `timestamp` |
| `outputs_B.jsonl` | Same for Prompt B |

---

## Step 2 — Evaluate

```bash
python3 evaluator.py
```

**What it does:**
1. Calls `sort_output_files()` — rewrites `outputs_A.jsonl` and `outputs_B.jsonl` in place sorted by `int(line_id)` ascending. This ensures correct ordering before evaluation.
2. Loads and joins each output file with the ground truth CSV on the `Content` / `log_message` field (content-based join, not positional — correct for any ordering).
3. Computes PA (per-message exact match), PTA (precision template accuracy), RTA (recall template accuracy), GA (grouping accuracy) per dataset.
4. Prints a comparison table against the paper's Table 2 HPC numbers.

**Notes:**
- Do NOT run `evaluator.py` on a partial run if you care about PTA/RTA/GA — these metrics require all 2000 logs.
- GA denominator = 2000 for a full run (matching the paper's hardcoded `/2000`); = number of evaluated logs for a partial run.
- The evaluator fixes two bugs present in the original `inferlog.py` evaluator: positional indexing for PTA/RTA (replaced with content-based join) and hardcoded `/2000` for GA on partial runs.

**Outputs** (under `results/`):

| File | Description |
|---|---|
| `results_A.jsonl` | Line 1: aggregate metrics JSON. Lines 2+: per-dataset metrics with paper comparison. |
| `results_B.jsonl` | Same for Prompt B |

---

## Prompts

The prompts in `prompts/promptA.py` and `prompts/promptB.py` were generated via `prompts/metaprompt.txt`. The metaprompt instructs a meta-model to produce a log parsing prompt using three HPC examples. Each file defines a `prompt` variable (a string) that `main.py` imports directly.

The three static few-shot examples used in both prompts are drawn directly from the HPC CSV:
```
{"log_message": "normal"}           → {"log_template": "normal"}
{"log_message": "ambient=30"}       → {"log_template": "ambient=<*>"}
{"log_message": "boot  (command 1911)"}  → {"log_template": "boot (command <*>)"}
```
The double space in the last example is real data from the CSV; it normalises to single space in the template (demonstrating the whitespace normalisation rule in `correct_single_template`).

---

## Results

All numbers below are for the **HPC dataset, n=2000 logs (full run)**.

| Pipeline | PA | PTA | RTA | GA |
|---|---|---|---|---|
| **Ours — Prompt A** (Sonnet 4.6, single call, $4.99) | 90.5% | 72.9% | 76.1% | 90.0% |
| **Ours — Prompt B** (Sonnet 4.6, single call, $9.56) | 90.5% | 78.3% | 78.3% | 90.5% |
| **Paper w/o InferLog** (DivLog + Qwen2.5-14B, no PAIR) | 98.4% | 75.0% | 84.8% | 94.9% |
| **Paper w/ InferLog** (DivLog + Qwen2.5-14B + PAIR) | 99.3% | 71.7% | 82.6% | 93.4% |

**Total cost:** $13.23 (both prompts, 2000 logs each).

---

## Comparison and Caveats

**What Table 2 actually compares:** Both "w/o InferLog" and "w/ InferLog" columns in the paper are the **same system** (DivLog + Qwen2.5-14B-Instruct with ascending ICL permutation). The table's purpose is to show that PAIR reordering does not degrade parsing accuracy. There is no accuracy comparison against external log parsers (DivLog, LILAC, LogBatcher, etc.) in the paper — all such baselines are compared only on **p95-latency** and **throughput**, not on PA/PTA/RTA/GA.

**Primary comparison target:** "w/o InferLog" (no PAIR reordering) is the most comparable to our pipeline, since our pipeline also applies no prefix-aware reordering.

**PA gap (~8%):** Our PA is 90.5% vs 98.4%. The main causes are: (1) our model (Sonnet 4.6) vs paper's (Qwen2.5-14B-Instruct locally fine-tuned to log parsing context); (2) no iterative refinement.

**PTA/RTA gap:** Our PTA (73–78%) is close to the paper's (75%), suggesting our template grouping is competitive. Our RTA (76–78%) trails the paper (85%), indicating we miss some rare templates.

**GA gap (~4–5%):** GA measures grouping correctness at the message level. Our 90% vs paper's 95% reflects the same factors as PA.

**Prompt B improves PTA/RTA/GA vs Prompt A:** The informed methodology prompt produces slightly more consistent template abstraction (78.3% PTA vs 72.9%), at ~2× the cost.

**p95-latency and throughput are not computable from our data:** Our pipeline processes one log at a time sequentially; the paper dispatches 100 concurrent requests via vLLM. The `duration_seconds` per call in `tokens_A.jsonl` / `tokens_B.jsonl` reflects sequential API latency and is not comparable to the paper's concurrent batch measurements.
