# Experiment Setup

This directory evaluates API argument completion. The pipeline preprocesses source code into masked call-site instances, runs one LLM call per sampled instance, and evaluates predicted arguments against the extracted ground truth.

The paper uses Eclipse/NetBeans as the Java dataset for comparison with ARist, and PY150 as the Python dataset for cross-language evaluation. This reproduction currently supports PY150 and NetBeans.

---

## Prerequisites

- Python 3.10+
- `wget`
- `git`
- `anthropic`
- `javalang`

Install `wget` if it is not already available:

```bash
sudo apt-get update
sudo apt-get install wget
```

Install the Python dependencies:

```bash
pip install anthropic javalang
```

Before running `main.py`, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Download Datasets

### PY150

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

### NetBeans

Create the Java dataset directory and clone NetBeans:

```bash
mkdir -p dataset-java
git clone https://github.com/apache/netbeans.git dataset-java/netbeans
```

The expected local input path is:

```text
dataset-java/netbeans/
```

---

## Step 2 — Prepare Input Instances

### PY150

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

### NetBeans

Run:

```bash
python3 prepare_input_java.py netbeans
```

This reads Java source files from:

```text
dataset-java/netbeans/
```

The output is:

```text
instances_netbeans.json
```

For a smaller preprocessing test run, use:

```bash
python3 prepare_input_java.py netbeans --max-files 100 --max-instances 500
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

The `ground_truth` field is produced during preprocessing by parsing the original source code and extracting the actual call arguments before masking them.

---

## Step 3 — Run the LLM

Run either Prompt A or Prompt B with the dataset name.

For PY150:

```bash
python3 main.py A py150
python3 main.py B py150
```

For NetBeans:

```bash
python3 main.py A netbeans
python3 main.py B netbeans
```


`main.py` reads:

```text
instances.json
instances_netbeans.json
prompts/prompt_A.txt
prompts/prompt_B.txt
```

The current script randomly samples 400 instances using seed 42. It also checks existing output files and reuses cached rows when the same `(filepath, call_line)` has already been generated.

Outputs are saved to:

```text
outputs/outputs_A_py150.jsonl
outputs/outputs_B_py150.jsonl
outputs/outputs_A_netbeans.jsonl
outputs/outputs_B_netbeans.jsonl
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

Because the output file already contains `ground_truth`, the evaluator does not need to reload the instance file.

---

## Step 4 — Evaluate

For PY150:

```bash
python3 evaluator.py A py150
python3 evaluator.py B py150
```

For NetBeans:

```bash
python3 evaluator.py A netbeans
python3 evaluator.py B netbeans
```


The evaluator reads:

```text
outputs/outputs_A_py150.jsonl
outputs/outputs_B_py150.jsonl
outputs/outputs_A_netbeans.jsonl
outputs/outputs_B_netbeans.jsonl
```


Results are written to:

```text
results/results_A_py150.jsonl
results/results_B_py150.jsonl
results/results_A_netbeans.jsonl
results/results_B_netbeans.jsonl
```

---

## Metrics

The evaluator reports:

- **Precision**: correct predicted arguments divided by total predicted arguments.
- **Recall**: correct predicted arguments divided by total ground-truth arguments.

The first line of each `results/results_<A|B>_<dataset>.jsonl` file contains the aggregate metrics. The remaining lines contain per-instance evaluation details.

