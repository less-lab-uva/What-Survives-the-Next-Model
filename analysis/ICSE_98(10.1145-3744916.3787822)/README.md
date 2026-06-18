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

## Step 1 — Load the Dataset

This experiment uses the paper's held-out **MultiPL-E Java test subset**:

```text
HumanEval Java   40 tasks
MBPP Java        64 tasks
Total           104 tasks
```

The exact held-out task IDs are stored in:

```text
dataset/id_split.json
```

This file comes from the paper's replication package and contains its
training, validation, and test IDs. `main.py` reads the `Test Ids` list and
automatically selects the 40 HumanEval and 64 MBPP tasks. The 41 CoderEval
test IDs in the same file are not used because they require CoderEval's
project-level evaluation infrastructure.

The task prompts and executable tests are loaded from Hugging Face:

```text
nuprl/MultiPL-E, config humaneval-java, split test
nuprl/MultiPL-E, config mbpp-java, split test
```

The first run may download these datasets into the local Hugging Face cache.
Later runs reuse that cache.

---

## Step 2 — Run the LLM

Run either Prompt A or Prompt B:

```bash
python3 main.py A
python3 main.py B
```

`main.py` reads:

```text
prompts/prompt_A.txt
prompts/prompt_B.txt
```

`main.py` automatically loads both MultiPL-E configurations and selects only
the 104 task names listed in the paper's test split. Cached rows are matched
by `instance_name`. It checks the current combined output first and can also
reuse matching rows from the older HumanEval and MBPP output files.

Outputs are saved to:

```text
outputs/outputs_A.json
outputs/outputs_B.json
```

---

## Step 3 — Evaluate

Run:

```bash
python3 evaluator.py A
python3 evaluator.py B
```

The evaluator reads:

```text
outputs/outputs_A.json
outputs/outputs_B.json
```

Results are written to:

```text
results/results_A.json
results/results_B.json
```

---

## Metric

The evaluator reports **Pass@1**:

```text
Pass@1 = passed / evaluated
```

A solution passes if the assembled Java program compiles and all benchmark assertions execute successfully.

---
