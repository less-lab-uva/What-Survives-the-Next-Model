# Experiment Setup

This directory evaluates argument completion from Python call sites. The pipeline downloads the ETH PY150 source files, preprocesses them into masked call instances, runs one LLM call per sampled instance, and evaluates the predicted arguments against the extracted ground truth.

---

## Prerequisites

- Python 3.10+
- `wget`
- `anthropic`

Install `wget` if it is not already available:

```bash
sudo apt-get update
sudo apt-get install wget
```

Install the Python dependency:

```bash
pip install anthropic
```

Before running `main.py`, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Download the Dataset

First download the ETH PY150 repository:

```bash
git clone https://github.com/google-research-datasets/eth_py150_open.git
```

Then download and extract the PY150 source files:

```bash
cd dataset/py150
bash download_and_extract.sh
cd ../..
```

After these commands, the required local inputs should exist at:

```text
eth_py150_open/eval__manifest.json
dataset/py150/py150_files/data/
```

---

## Step 2 — Prepare Input Instances

Run:

```bash
python3 prepare_input.py
```

This reads Python files listed in:

```text
eth_py150_open/eval__manifest.json
```

and extracts function or method calls from:

```text
dataset/py150/py150_files/data/
```

The output is:

```text
instances.json
```

Each instance contains:

```json
{
  "filepath": "...",
  "preceding_code": "...",
  "call_line": "function_name(/* missing */)",
  "ground_truth": ["arg1", "arg2"],
  "num_args": 2
}
```

The `ground_truth` field is produced during preprocessing by parsing the original Python source code and extracting the actual call arguments before masking them.

---

## Step 3 — Run the LLM

Run either Prompt A or Prompt B:

```bash
python3 main.py A
python3 main.py B
```

`main.py` reads:

```text
instances.json
prompts/prompt_A.txt
prompts/prompt_B.txt
```

The current script randomly samples 400 instances using seed 42. It also checks existing output files and reuses cached rows when the same `(filepath, call_line)` has already been generated.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

Each output row includes both the model prediction and the ground truth:

```json
{
  "filepath": "...",
  "call_line": "...",
  "ground_truth": ["..."],
  "arguments": [{"position": 0, "value": "..."}],
  "raw_output": "..."
}
```

Because the output file already contains `ground_truth`, the evaluator does not need to reload `instances.json`.

---

## Step 4 — Evaluate

Run:

```bash
python3 evaluator.py A
python3 evaluator.py B
```

The evaluator reads:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

It compares each predicted argument in `arguments` against the corresponding value in `ground_truth`.

Results are written to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

---

## Metrics

The evaluator reports:

- **Precision**: correct predicted arguments divided by total predicted arguments.
- **Recall**: correct predicted arguments divided by total ground-truth arguments.
- **MRR**: currently computed as the average of per-prediction correctness scores, where correct predictions receive `1.0` and incorrect predictions receive `0.0`.

The first line of each `results/results_<A|B>.jsonl` file contains the aggregate metrics. The remaining lines contain per-instance evaluation details.

---
