# PrePA / ΛMDA — LLM Replacement Study on StatType-SO

This folder contains a single-call LLM replacement study for the ΛMDA (PrePA) pipeline from the ICSE 2026 paper *"Large Language Model-Aided Partial Program Dependence Analysis"* (DOI: [10.1145/3744916.3773119](https://doi.org/10.1145/3744916.3773119)).

---

## What the Original Pipeline Does

ΛMDA analyses partial Java programs (snippets that cannot be compiled due to missing imports, types, or context) to produce Program Dependence Graphs (PDGs). It works in two phases:

1. **Context Augmentation**: an LLM receives the partial snippet and compiler error messages iteratively. It produces an approximately-complete program P_AC that compiles. Two prompts are used in sequence — an initial approximation prompt and a self-correction prompt that receives the compiler errors as feedback. This loop runs until the code compiles or a maximum number of iterations is reached.
2. **PDG Analysis**: Joern runs on P_AC to extract a PDG. Edges are then pruned to keep only those whose both endpoints are statements present in the original partial snippet, giving a PDG anchored to the original code.

**Key claim:** high recall (LLM fills in missing context allowing Joern to succeed) combined with high precision (Joern guarantees structural soundness of the extracted edges).

---

## What This Study Does

We replace Phase 1 with a **single Claude Sonnet 4.6 call** per snippet. Phase 2 (Joern + pruning) is kept identical. Two prompt strategies are compared:

- **Prompt A (Black-box):** Describes the output format only — produce an approximately-complete compilable Java class wrapping the snippet — with no guidance on methodology.
- **Prompt B (Informed):** Describes a 6-step methodology: resolve imports, infer types, generate stubs for unresolved symbols, wrap in a compilable class, and format the output.

Both prompts ask the model to also return `type_information` (variable-to-type mappings) mirroring the paper's input to its Joern step.

---

## Why StatType-SO

The paper evaluates on two datasets: StatType-SO (172 Java snippets from StackOverflow) and COSTER-SO (274 snippets). We chose StatType-SO because:

- It is the smaller dataset, reducing cost (~$3.28 vs ~$6 for COSTER-SO).
- It is the paper's primary dataset and the one used in Table 1.
- The average partial snippet length is short (~364 chars), keeping input tokens low.

---

## Dataset Preprocessing

The dataset file `dataset/Stattype_res.json` contains 172 entries. Of these:

| Count | Reason |
|---|---|
| 172 | Total entries in dataset |
| −3 | No ground-truth PDG (`Android14`, `gwt_class_39`, `xstream_class_35`) → excluded |
| = **169** | Entries `main.py` processes |
| −60 | Ground truth exists but has **0 valid DDG edges inside `partial_code`** → evaluator skips Joern entirely |
| = **109** | Entries that contribute to evaluation metrics |

The 60 skipped entries have a ground-truth PDG, but none of its DDG edges have both endpoints as lines present in the partial snippet. Running Joern on them would produce undefined precision and recall (0/0), so they are excluded from aggregate metrics.

Each entry has one variant (numbered 1–5), giving a `partial_code` (the incomplete snippet sent to the LLM) and `PrePA_code` (the paper's LLM-generated approximation, pre-stored for comparison).

**Input to LLM:** only `partial_code` — the raw partial Java snippet. No ground truth, no complete code, no compiler output.

---

## Environment Setup

### 1. Python version

Python 3.10 or later is required. `evaluator.py` uses `dict | str` union type hints (PEP 604) that require Python 3.10+.

```bash
python3 --version   # should be >= 3.10
```

### 2. Install Python dependencies

All required packages are listed in `requirements.txt`. Install them with:

```bash
pip install -r requirements.txt
```

| Package | Version | Used by | Purpose |
|---|---|---|---|
| `anthropic` | >=0.40.0 | `main.py` | Claude API client |
| `pydot` | >=1.4.2 | `evaluator.py` | Parse Joern `.dot` graph files |
| `beautifulsoup4` | >=4.9.0 | `evaluator.py` | Parse HTML node labels in PDG output |

`main.py` and the prompt files use only Python standard library modules beyond `anthropic`.

### 3. Set the API key

`main.py` reads the Anthropic API key from the environment:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

To persist it across sessions, add the line above to your `~/.bashrc` or `~/.bash_profile`.

### 4. Joern (for evaluation only)

`evaluator.py` invokes Joern to extract PDGs from the LLM-generated Java code. This is only needed for Step 2 — you can run `main.py` without it.

Joern is expected at `/project/lesslab/nm8tm/joern-cli/joern-cli/bin`. If your installation is elsewhere, update `JOERN_PATH` at the top of `evaluator.py`:

```python
JOERN_PATH = "/path/to/your/joern-cli/bin"
```

To install Joern, download the pre-built CLI bundle from [joern.io](https://joern.io) and extract it. The evaluator uses `joern-parse` and `joern-export` — both are included in the standard Joern CLI release.

---

## Dataset

The `dataset/` directory is **already included** in this repository. No download step is required.

The file `dataset/Stattype_res.json` (169 entries) comes from the original PrePA / ΛMDA paper artefact:

> **PrePA (ΛMDA)** — [https://anonymous.4open.science/r/PrePA-7157/](https://anonymous.4open.science/r/PrePA-7157/) (anonymous review artifact)

It contains 172 Java partial-code snippets from StackOverflow (the StatType-SO benchmark), each with pre-stored ground-truth PDG results and the original pipeline's LLM-generated approximations (`PrePA_code_res`). The 3 entries without a valid ground-truth PDG (`Android14`, `gwt_class_39`, `xstream_class_35`) are excluded by `main.py` at load time, leaving 169 eligible entries.

---

## Step 1 — Generate Approximated Code

```bash
python3 main.py <budget_usd> [dataset_name]
```

Example:
```bash
python3 main.py 6.0 stattype
```

**Behavior:**
- Loads all 169 valid entries from `dataset/Stattype_res.json`.
- Runs Prompt A and Prompt B on each entry using Claude Sonnet 4.6.
- Checks the budget before every API call and stops when exhausted.
- Resumable: re-running skips already-completed entries. Partially completed entries (one prompt done, the other not) are always finished before new entries are started.

**Cost estimate (Sonnet 4.6, $3/MTok in, $15/MTok out):**
- 169 entries, both prompts: ~$3.87 (Prompt A ~$1.60, Prompt B ~$2.27)
- Recommended budget: `$6.0` (leaves margin for token variance)

**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per entry: `entry_name`, `variant`, `partial_code`, `approximated_code`, `type_information`, `dataset`, `timestamp` |
| `outputs_B.jsonl` | Same for Prompt B |

---

## Step 2 — Evaluate

```bash
python3 evaluator.py [dataset_name]
```

Example:
```bash
python3 evaluator.py stattype
```

**What it does:**
1. Loads `outputs_A.jsonl` and `outputs_B.jsonl`.
2. For each entry, computes `valid_edges`: DDG edges from the ground-truth PDG whose both endpoints appear in `partial_code`. If `valid_edges` is empty, Joern is **not invoked** for that entry and it is excluded from metrics.
3. Runs Joern on the LLM's `approximated_code` to obtain its PDG. Results are cached per-prompt in `outputs/joern_cache_A.json` and `outputs/joern_cache_B.json` (keyed by MD5 of the code), so rerunning is fast.
4. Calls `calculate_fp_tp_fn` (verbatim from the paper's `RQ3_eval.py`) to compute TP, FP, FN.
5. Also computes the same metrics for the **Original PrePA pipeline** using the pre-stored `PrePA_code_res` PDGs from the dataset JSON, on the same evaluated entries.
6. Prints per-entry Joern output (discovered DDG edges, line text) and per-entry TP/FP/FN for inspection.

**Outputs** (under `results/`):

| File | Description |
|---|---|
| `results_A.jsonl` | Line 1: aggregate JSON (our metrics + Original PrePA metrics). Lines 2+: per-entry JSON. |
| `results_B.jsonl` | Same for Prompt B |

---

## Evaluation Metric

Precision, Recall, and F1 are computed over **DDG (data dependence) edges only**. This corresponds to the **"Data" column** in the paper's Table 1, **not** the headline "Data+Control" column. The `calculate_fp_tp_fn` function is reproduced verbatim from the paper's `RQ3_eval.py`.

Note: TP+FP is not a direct count of predicted edges. The FP logic in `calculate_fp_tp_fn` may count the same edge multiple times (once per similar GT edge), and edges whose source or destination line is not a substring of `partial_code` are silently excluded from FP counting (though they may still count as TP if they match a GT edge exactly).

---

## Results

All numbers below are for the **"Data" (DDG-only) column**, evaluated on **n=109 entries** (those with at least one valid DDG edge in `partial_code`).

| Pipeline | Precision | Recall | F1 | n |
|---|---|---|---|---|
| **Ours — Prompt A** (Sonnet 4.6, single call) | 78.7% | 85.4% | 81.9% | 109 |
| **Ours — Prompt B** (Sonnet 4.6, single call) | 75.4% | 85.2% | 80.0% | 109 |
| **Original PrePA** (paper, pre-stored PDGs, compatible to Data column) | 95.9% | 92.0% | 93.9% | 109 |

**Total cost:** $3.28 (Sonnet 4.6, 169 entries × 2 prompts)

---

## Comparison and Caveats

**Precision gap (~17–20%):** The paper's iterative compiler feedback loop is the main driver. Without it, the LLM's single-call approximation occasionally introduces incorrect types, wrong method signatures, or phantom variables. Joern faithfully extracts edges from these incorrect lines, producing FP edges that are not in the GT.

**Recall gap (~7%):** Recall is more similar because the LLM generally captures the structural data flow of the snippet correctly in a single call, even without compiler verification.

**Why our n=109 differs from the paper's n=164:**
The paper reports results over 164 of 172 entries (8 excluded: 3 no-GT + 1 Joern-fail + 4 empty PDGs). Our evaluation skips 60 additional entries where the GT PDG has no DDG edges whose both endpoints are inside `partial_code`. These entries would produce undefined precision/recall (0/0) and are excluded to avoid distorting the aggregate. The paper likely includes them differently or uses a different pruning definition.


**Joern cache is prompt-specific:** `joern_cache_A.json` and `joern_cache_B.json` are separate so that re-running one prompt never reuses the other's cached Joern results.
