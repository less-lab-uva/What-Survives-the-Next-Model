# Experiment Setup

This directory evaluates a simplified single-LLM version of the paper **"Small Changes, Big Trouble: Demystifying and Parsing License Variants for Incompatibility Detection in the PyPI Ecosystem"**. The original paper proposes LV-Parser, which combines license-variant analysis, diff-based processing, similar examples, and LLM parsing. This reproduction directly asks Claude to parse each license text into the paper's license-term schema.

---

## Prerequisites

- Python 3.10+
- The `anthropic` Python package

Install dependencies:

```bash
pip install anthropic
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Step 1 — Prepare the Dataset

The current runnable dataset is already stored in:

```text
dataset/eval_instances_with_text.jsonl
dataset/eval_label_term.jsonl
```

`eval_instances_with_text.jsonl` is the file used by `main.py`. Each row contains:

```text
project_name
license_name
license_file
license_text
term
```

`term` is the ground-truth license-term annotation. `main.py` copies this into the output as `gt_term`, so the evaluator can score predictions without reopening the original license archive.

`eval_label_term.jsonl` is the standalone ground-truth label file from the paper's dataset. The current run path does not read it directly because the same labels are already embedded in `eval_instances_with_text.jsonl`; it is kept for transparency.

If you want to regenerate the dataset, download the paper's dataset/code artifact from Figshare:

```text
https://figshare.com/s/4fbaedbeb120d1940f12
```

After downloading and extracting the artifact, place the extracted `icse-lv` directory under:

```text
ICSE_R186/icse-lv/
```

It must contain:

```text
icse-lv/Annotation/eval_label_term.jsonl
icse-lv/pkg_license.tar.gz
```

Then build the compact dataset:

```bash
python3 create_eval_dataset.py
```

This creates:

```text
dataset/eval_instances_with_text.jsonl
```

After that, the large `icse-lv` directory is not needed for running `main.py` or `evaluator.py`.

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
dataset/eval_instances_with_text.jsonl
```

It runs the full 74-license evaluation set with seed 42. Cached rows are loaded from the existing output file by `(project_name, license_name)`, so rerunning the same prompt does not call the LLM again for already generated rows.

Outputs are saved to:

```text
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

Token reports are saved to:

```text
outputs/tokens_A.txt
outputs/tokens_B.txt
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
outputs/outputs_A.jsonl
outputs/outputs_B.jsonl
```

It compares each row's `pred_term` against `gt_term`.

Numeric fields are evaluated with exact-match accuracy:

```text
copyright
copyleft
modification
patent
trademark
interaction
retain_attr
acceptance
enhance_attr
patent_term
```

Open-ended fields are evaluated with recall over the ground-truth labels:

```text
Usage Limitation
exception
compatible_version
secondary_license
gpl_combine
```

Results are written to:

```text
results/results_A.jsonl
results/results_B.jsonl
```

---

## Metrics

The evaluator reports:

```text
numeric_accuracy  = micro-average exact-match accuracy over numeric fields
open_field_recall = micro-average recall over open-ended fields
overall_mean      = micro-average over all evaluated fields
```

The first line of each result file contains the aggregate scores. The remaining lines contain per-instance scores and the predicted/ground-truth terms.

---
