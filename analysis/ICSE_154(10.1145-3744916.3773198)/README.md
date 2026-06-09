# LASiR — LLM Replacement Study

This folder contains an LLM replacement study for [LASiR](https://doi.org/10.1145/3744916.3773198) (ICSE 2026). We replace the original three-phase, three-LLM-call pipeline with a single Claude Sonnet 4.6 call and evaluate on the same benchmark using the same metrics reported in the paper.

---

## Overview

### Original LASiR Pipeline (three phases)

LASiR detects **Signature Replay Vulnerabilities (SRVs)** in Solidity smart contracts — cases where a cryptographic signature that authorized one transaction can be replayed to authorize a different, unintended transaction. The paper identifies five SRV types:

| ID | Name | Root Cause |
|---|---|---|
| X-CRA | Cross-chain Replay Attack | No `block.chainid` in signed hash |
| X-PRA | Cross-project Replay Attack | No `address(this)` in signed hash |
| CASR | Contract Account Signature Replay | No contract-specific account address in hash |
| SSMI | Signature State Management Issue | No nonce, usage record, or deadline |
| SMA | Signature Malleability Attack | `v` and `s` not restricted per secp256k1 |

The pipeline proceeds in three phases:

1. **Slicing** — Compiles the Solidity contract to AST, builds an Interprocedural Program Dependence Graph (I-PDG) via Slither, then uses an LLM to identify key signature-related variables and extract relevant code slices.
2. **Inspection** — A second LLM call analyzes the sliced code to identify which variables are sanitized (e.g., nonces, chain IDs, `address(this)`) against domain-specific SRV patterns, generating structured warnings.
3. **Path Reachability** — A third LLM call generates vulnerable function call sequences, which are then verified via symbolic execution (Z3) to confirm exploitability.

### Our Approach (single LLM call)

We collapse all three phases into one Claude Sonnet 4.6 call. Given only the raw Solidity source code, the model is asked to classify whether an SRV exists and identify which vulnerability types are present. No AST, no I-PDG, no symbolic execution.

Output format matches LASiR's external interface exactly:
```json
{"Exist": true, "Vuln_type": ["X-CRA", "SSMI"]}
```

Two prompt strategies are compared:

- **Prompt A (Black-box):** States the task, defines the five SRV types, and requests the JSON output. No reasoning guidance.
- **Prompt B (Step-by-step):** Adds explicit reasoning steps — identify signature operations, check each SRV type's sanitization conditions, compile verdict.

---

## Why This Dataset?

**DB2 (RQ2 labeled set):** 500 Solidity contracts manually labeled by the paper's authors: 72 positive (contain at least one SRV) and 428 negative. These contracts were drawn from the DB1 large-scale dataset of 15,383 contracts that use `ecrecover()`, then manually verified to establish ground truth. This is the only dataset with binary (positive/negative) labels, making it the appropriate benchmark for precision/recall evaluation.

We use a **10% stratified sample** (50 contracts: ~7 positive + ~43 negative) to keep inference cost manageable (~$5.62 vs ~$56.20 for the full set). The sample is drawn once at first run and persisted in `outputs/sample_ids.json` for reproducibility.

We use DB2 only (RQ2). The RQ3 ablation dataset is byte-for-byte identical to RQ2 but the ablation groups (LLM-only, static-only, etc.) cannot be replicated with a single-call approach, so RQ3 is out of scope.

---

## Prerequisites

```bash
pip install anthropic
```

Set the Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

---

## Step 1 — Get the Dataset

The `Dataset/` folder is not included in the repository. It contains the labeled CSV files and Solidity contract source files.

### 1a — Labels (CSV)

The labeled data CSVs (`Dataset/RQ2/Labeled_Data.csv`, etc.) and the DB2 chain CSVs are part of the paper's artifact, available from the [ACM Digital Library](https://doi.org/10.1145/3744916.3773198) supplemental materials or the authors' repository.

Place the extracted artifact under the project root so the directory structure is:

```
LASIR/
├── Dataset/
│   ├── RQ2/Labeled_Data.csv
│   └── RQ1/DB1/Ethereum.csv   (needed for fetch_contracts.py)
└── src/
    └── ...
```

### 1b — Contract Source Files

The `.sol` source files are fetched from the public [smart-contract-sanctuary](https://github.com/tintinweb/smart-contract-sanctuary-ethereum) repository at a pinned commit. A dedicated script in the project root handles this:

```bash
# From the LASIR/ root directory:
python3 fetch_contracts.py          # Ethereum only — covers 94% of DB2 (recommended)
python3 fetch_contracts.py --all    # All 4 chains: Ethereum, Polygon, BSC, Arbitrum
```

This saves `.sol` files to `Dataset/contracts/Ethereum/` (and other chains if `--all`). The script is resumable — already-downloaded files are skipped. Ethereum alone (~4,514 files) covers 470 of the 500 DB2 contracts.

---

## Step 2 — Run Inference

```bash
python3 main.py <budget_usd>
```

Example:

```bash
python3 main.py 7.0
```

**Behavior:**

- On first run, draws a stratified 10% sample (50 contracts) and saves the selection to `outputs/sample_ids.json`. Subsequent runs reload the same sample.
- Runs Prompt A and Prompt B on each sampled contract.
- Stops when the budget is exhausted. Re-running resumes automatically — completed contracts are skipped, partially completed ones (one prompt done) are finished first before new ones are started.
- Contracts exceeding the token limit (~190K tokens) are skipped and logged.

**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per contract: `contract_id`, `label`, `Exist`, `Vuln_type`, `dataset` |
| `outputs_B.jsonl` | Same for Prompt B |
| `tokens_A.jsonl` | Token counts, cost, and wall-clock time per API call |
| `tokens_B.jsonl` | Same for Prompt B |
| `sample_ids.json` | Persisted sample selection for reproducibility |

**Estimated cost** (Claude Sonnet 4.6, $3/M input tokens, $15/M output tokens):

| Scope | Estimated cost |
|---|---|
| 10% sample (50 contracts), both prompts | ~$5.62 |
| Full 500 contracts, both prompts | ~$56.20 |

---

## Step 3 — Evaluate

```bash
python3 evaluator.py
```

Computes Precision, Recall, F1, and Accuracy against the ground truth labels from `Labeled_Data.csv`. Prints the confusion matrix and lists false positives and false negatives.

Results are written to `results/results_A.jsonl` and `results/results_B.jsonl`. Line 1 of each file is the aggregate metrics; subsequent lines are per-contract results.

---

## Results Comparison

Paper baseline (LASiR full pipeline, Table 2 RQ2, 500 contracts):

| Metric | Paper (500 contracts) | Ours Prompt A (50) | Ours Prompt B (50) |
|---|---|---|---|
| **Precision** | 0.8214 | 0.25 | 0.1628 |
| **Recall** | 0.9583 | **1.0** | **1.0** |
| **F1** | 0.8846 | 0.40 | 0.28 |
| TP | 69 | 7 | 7 |
| FP | 15 | 21 | 36 |
| TN | 413 | 22 | 7 |
| FN | 3 | 0 | 0 |

### Why our precision is poor

The results show the opposite pattern from typical LLM classification failures: **recall is perfect (1.0) but precision is very low**. The model never misses a vulnerable contract (FN=0) but flags a large fraction of negative contracts as positive. Several factors explain this:

**1. No static analysis — the core of LASiR's precision.**
LASiR's precision comes from Phase 2 (Inspection), which identifies exactly which variables ARE sanitized before classifying. The LLM in Phase 2 receives a sliced view of signature-related code and checks for the presence of nonces, `block.chainid`, `address(this)`, and similar guards. Without this structured evidence, our model sees contracts that use `ecrecover` and reasons about what *could* be missing rather than what is definitively *not* present.

**2. Pre-filtered dataset biases toward ambiguity.**
All 500 DB2 contracts were pre-selected from contracts that use `ecrecover()` — they all have the surface appearance of signature verification. Many contracts that are negative simply delegate signature checking to a utility library or use it in a context where replay is harmless. Without the I-PDG to trace data flow, the model cannot distinguish these cases from genuine vulnerabilities.

**3. Security conservatism bias.**
When a model is uncertain about whether a security vulnerability exists, it tends to report it rather than dismiss it. This is the right behavior in practice (miss a vulnerability = real harm), but it drives precision down in a balanced evaluation against a pre-labeled dataset.

**4. Prompt B performs worse than Prompt A.**
The step-by-step reasoning in Prompt B makes the model more methodical about checking every SRV type, which increases false positives further. Prompt A's under-specification leads to slightly more conservative predictions.

In summary, the multi-phase pipeline is not just an engineering convenience — the I-PDG slicing and sanitization inspection in Phases 1 and 2 provide the structured signal that distinguishes positive from negative cases. A single LLM call reading raw source code cannot replicate this without running static analysis.
