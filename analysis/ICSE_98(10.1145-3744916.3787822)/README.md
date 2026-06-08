# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"Improving Code Generation via Small Language Model-as-a-judge"**. The original paper generates multiple Java candidate solutions with small code models and uses one or more small language models as judges to rank/select the final answer. This reproduction directly asks Claude to generate one Java solution and evaluates it with the benchmark tests.

---

## Prerequisites

- Python 3.10+
- Java JDK with `javac` and `java`
- The `anthropic` Python package
- The Hugging Face `datasets` package
- `wget`, only needed if `javatuples-1.2.jar` is missing

Install Java and `wget` on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk wget
```

Install Python dependencies:

```bash
pip install anthropic datasets
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

Check Java:

```bash
javac -version
java -version
```

The evaluator needs `javatuples-1.2.jar` in this directory. If it is missing, download it:

```bash
wget https://repo1.maven.org/maven2/org/javatuples/javatuples/1.2/javatuples-1.2.jar -P .
```

---

## Step 1 — Load the Datasets

`main.py` loads Java benchmark tasks from Hugging Face through the `datasets` library.

Supported datasets:

```text
humaneval -> nuprl/MultiPL-E, config humaneval-java, split test
mbpp      -> nuprl/MultiPL-E, config mbpp-java, split test
```

The first run may download the datasets into the local Hugging Face cache. Later runs reuse that cache.

---

## Step 2 — Run the LLM

Run either Prompt A or Prompt B on one dataset:

```bash
python3 main.py A humaneval
python3 main.py B humaneval

python3 main.py A mbpp
python3 main.py B mbpp
```

`main.py` reads:

```text
prompts/prompt_A.txt
prompts/prompt_B.txt
```

It runs the full selected test split with seed 42:

```text
humaneval  158 instances
mbpp       386 instances
```

Cached rows are loaded from previous output/result files by `instance_index`, so rerunning the same prompt and dataset does not call the LLM again for already generated instances.

Outputs are saved to:

```text
outputs/outputs_A_humaneval.json
outputs/outputs_B_humaneval.json
outputs/outputs_A_mbpp.json
outputs/outputs_B_mbpp.json
```

Token reports are saved to:

```text
outputs/tokens_A_humaneval.txt
outputs/tokens_B_humaneval.txt
outputs/tokens_A_mbpp.txt
outputs/tokens_B_mbpp.txt
```

---

## Step 3 — Evaluate

Run:

```bash
python3 evaluator.py A humaneval
python3 evaluator.py B humaneval

python3 evaluator.py A mbpp
python3 evaluator.py B mbpp
```

The evaluator reads:

```text
outputs/outputs_<A|B>_<humaneval|mbpp>.json
```

Results are written to:

```text
results/results_A_humaneval.json
results/results_B_humaneval.json
results/results_A_mbpp.json
results/results_B_mbpp.json
```

---

## Metric

The evaluator reports **Pass@1**:

```text
Pass@1 = passed / evaluated
```

A solution passes if the assembled Java program compiles and all benchmark assertions execute successfully.

---

