# Experiment Setup

This project generates TensorFlow API completions for real-world and synthetic code prefixes using Prompt A or Prompt B, then evaluates predictions with exact match (EM@1) against the ground truth API name.

**Paper:** AdapTrack: Constrained Decoding without Distorting LLM's Output Intent  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3773144

---

## Prerequisites

- Python 3.8+

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Dataset

All data is in `data/` 

| File | Description | Size |
|---|---|---|
| `tfv1-function.json` | 419 TFv1 function names — used to build the synthetic samples | 12KB |
| `tfv1-template.py` | Code template for synthetic sample generation | 4KB |

> **Note:** We replicate **RQ1** from the paper, which evaluates on the 419 synthetic TF API completions. The paper also includes a real-world dataset (1000 GitHub samples), but that corresponds to a different research question. We do not use it here and have not included it in the repository.

---

## The v1 / v2 Settings

The paper evaluates the same 419 synthetic samples under two oracle settings to replicate their Table 1 results:

- **v1 setting**: the ground truth is the native TFv1 short path (e.g. `.losses.mean_pairwise_squared_error`), simulating a user on TensorFlow 1.x.
- **v2 setting**: the ground truth requires the `compat.v1.` prefix (e.g. `.compat.v1.losses.mean_pairwise_squared_error`), simulating a TF2 user calling a deprecated v1 API.

The paper enforces these settings via a constrained decoder. We replicate them by injecting a `tensorflow_version` hint into the prompt at generation time (producing separate outputs per setting), and swapping the oracle string at evaluation time to match the required setting.

---

## Step 1 — Run the Experiment

Generate TF API completions using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--setting {v1,v2,both}] [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --setting both --n 419
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--setting` | `both` | TensorFlow version hint injected into the prompt: `v1`, `v2`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across the 419 synthetic samples |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_{A|B}_{v1|v2}.jsonl`. Each line contains the prediction, raw model response, and response time.

---

## Step 2 — Evaluate

Score predictions using EM@1 (exact match against the ground truth API name):

```bash
python evaluator.py --variant {A,B,both} [--setting {v1,v2,both}]
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to evaluate |
| `--setting` | `both` | Oracle setting(s) to evaluate |

Results are saved to `results/results_{A|B}_{v1|v2}.jsonl`.

---

---

## Metric

We report **EM@1**: a prediction is correct if it exactly matches the ground truth API name (including the leading `.`).
