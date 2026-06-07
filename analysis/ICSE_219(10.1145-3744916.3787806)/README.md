# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"Modeling Like Peeling an Onion: Layerwise Analysis-Driven Automatic Behavioral Model Generation"**. The original paper proposes LATO, a multi-step layerwise pipeline that identifies activities, extracts nested relations, constructs UML activity diagrams, and validates syntax. This reproduction directly asks Claude to generate one PlantUML activity diagram for each requirement instance.

---

## Prerequisites

- Python 3.10+
- The `anthropic`, `numpy`, and `sentence-transformers` Python packages
- PlantUML for the intended syntax check

Install Python dependencies:

```bash
pip install anthropic numpy sentence-transformers
```

Install PlantUML on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y default-jre graphviz plantuml
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

The evaluator uses the sentence-transformer model:

```text
sentence-transformers/all-MiniLM-L6-v2
```

The first evaluation run may download this model into the local Hugging Face cache.

---

## Step 1 — Dataset

The datasets are stored locally in:

```text
dataset/bp.jsonl
dataset/fsd.jsonl
dataset/lmc.jsonl
dataset/pure.jsonl
dataset/rac.jsonl
dataset/us.jsonl
```

Each row contains:

```text
content   -> natural-language requirement text
plantuml  -> reference PlantUML activity diagram
```

Dataset sizes:

```text
bp     30
fsd    116
lmc    56
pure   100
rac    20
us     220
total  542
```

The paper states that its source code and datasets are available at:

```text
https://github.com/reg-repo/LATO
```

For this reproduction, the needed compact JSONL files are already present in `dataset/`.

---

## Step 2 — Run the LLM

Run Prompt A or Prompt B for each dataset:

```bash
python3 main.py A bp
python3 main.py A fsd
python3 main.py A lmc
python3 main.py A pure
python3 main.py A rac
python3 main.py A us

python3 main.py B bp
python3 main.py B fsd
python3 main.py B lmc
python3 main.py B pure
python3 main.py B rac
python3 main.py B us
```

`main.py` reads:

```text
prompts/prompt_A.txt
prompts/prompt_B.txt
dataset/<dataset>.jsonl
```

It runs the full selected dataset with seed 42. Cached rows are loaded from the existing output file by `task_id`, so rerunning the same prompt and dataset does not call the LLM again for already generated rows.

Outputs are saved to:

```text
outputs/outputs_A_<dataset>.jsonl
outputs/outputs_B_<dataset>.jsonl
```

Token reports are saved to:

```text
outputs/tokens_A_<dataset>.txt
outputs/tokens_B_<dataset>.txt
```

---

## Step 3 — Evaluate Each Dataset

Run:

```bash
python3 evaluator.py A bp
python3 evaluator.py A fsd
python3 evaluator.py A lmc
python3 evaluator.py A pure
python3 evaluator.py A rac
python3 evaluator.py A us

python3 evaluator.py B bp
python3 evaluator.py B fsd
python3 evaluator.py B lmc
python3 evaluator.py B pure
python3 evaluator.py B rac
python3 evaluator.py B us
```

The evaluator reads:

```text
outputs/outputs_<A|B>_<dataset>.jsonl
```

Per-dataset results are written to:

```text
results/results_A_<dataset>.jsonl
results/results_B_<dataset>.jsonl
```

---

## Step 4 — Aggregate Results

After all six datasets have been evaluated for both prompts, run:

```bash
python3 aggregate_results.py
```

This writes:

```text
results/aggregated_results_A.json
results/aggregated_results_B.json
```

The aggregate score is a macro-average over the six datasets. These aggregated result files are the main comparison files for the paper-level summary: they combine the six per-dataset evaluator outputs into one Prompt A score and one Prompt B score for `R-F1`, `N-F1`, and `pass_rate`.

---

## Metrics

The main metrics are:

```text
N-F1       -> F1 over behavioral node/activity extraction
R-F1       -> F1 over behavioral relation/control-flow extraction
pass_rate  -> proportion of generated diagrams that pass syntax and structural checks
```

The evaluator also records node precision/recall, relation precision/recall, syntax pass rate, and structural pass rate in each per-dataset result file.

---
