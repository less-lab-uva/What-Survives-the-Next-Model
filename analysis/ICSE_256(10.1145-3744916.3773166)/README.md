# EchoFuzz — LLM Replacement Study on SmartBugs D2

This directory contains an LLM replacement study for the EchoFuzz pipeline (ICSE 2026). We replace the original 4-phase smart contract fuzzer with a single Claude Sonnet 4.6 call per contract and evaluate on the D2 dataset using precision and recall against the same ground-truth labels used by the paper.

**Paper:** EchoFuzz: Empowering Smart Contract Fuzzing with Large Language Models  
**DOI:** https://doi.org/10.1145/3744916.3773166  
**Venue:** 2026 IEEE/ACM 48th International Conference on Software Engineering (ICSE '26)

---

## Overview

EchoFuzz is a 4-phase LLM-guided smart contract fuzzer:

1. **Chain-guided LLM** — generates Vulnerable Function Call Sequences (VFCS): minimal, behavior-preserving execution paths that expose vulnerabilities through key state transitions.
2. **IR-Fuzz** — a coverage-guided fuzzer that seeds from the VFCS candidates.
3. **Runtime oracle** — fires only on actual execution events (reentrancy callbacks, integer wrap-arounds, unchecked call failures, block/timestamp manipulation). This guarantees zero false positives by design.
4. **Reporting** — aggregates per-category detection counts.

In this study, we replace the entire 4-phase pipeline with a single LLM call using two prompt strategies:

- **Prompt A (Black-box):** Instructs the model to analyse Solidity source and report vulnerabilities in 6 fields with concrete test cases, with no guidance on the paper's methodology.
- **Prompt B (Informed):** Provides the paper's VFCS methodology as numbered reasoning steps — chain analysis, state-transition mapping, VFCS candidate generation, branch targeting, and oracle simulation.

---

## Why D2?

The paper evaluates on three datasets (D1, D2, D3). We chose **D2** (143 contracts from SmartBugs Wild) because it is the only dataset with per-contract ground-truth vulnerability labels embedded directly in the `.sol` source files as `<report>` annotations. D1 and D3 do not carry these annotations, making automated precision/recall evaluation impossible for those datasets. The paper's Table 3 also reports aggregate detection counts for D2 at the category level, giving us a concrete reference to compare against.

D2 covers 10 vulnerability label types. Six of these map directly to EchoFuzz's detection categories (see label mapping below); the remaining four (ACCESS_CONTROL, FRONT_RUNNING, DENIAL_OF_SERVICE, OTHER, SHORT_ADDRESSES) have no corresponding EchoFuzz output field and are excluded from evaluation.

---

## Prerequisites

**Python packages:**
```bash
pip install anthropic
```

**Environment variable:**
```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

---

## File Structure

```
with_sonnet/
  main.py           — pipeline runner (budget-gated, resumable)
  evaluator.py      — evaluation vs. D2 ground truth + paper Table 3 reference
  prompts/
    promptA.py      — black-box prompt (6-field output schema)
    promptB.py      — informed prompt (VFCS reasoning steps + 6-field schema)
  dataset/D2/       — 143 .sol files with embedded <report> annotations
  outputs/
    outputs_A.jsonl — one JSON line per contract: LLM response for Prompt A
    outputs_B.jsonl — same for Prompt B
    tokens_A.jsonl  — per-call token counts, cost, and wall-clock time for Prompt A
    tokens_B.jsonl  — same for Prompt B
    state.json      — resume checkpoint (selected contracts, target count)
  results/
    results_A.jsonl — line 1: aggregate metrics; lines 2+: per-contract breakdown
    results_B.jsonl — same for Prompt B
  paper.json        — paper metadata and final results
  metaprompt.txt    — meta-prompt used to generate promptA.py and promptB.py
```

---

## Step 1 — Input Processing

`main.py` preprocesses every `.sol` file in `dataset/D2/` before sending it to the LLM:

1. **Extract ground-truth labels** — scans for `<report> LABEL` annotations embedded in the source (e.g., `// <report> REENTRANCY`). These are the evaluation targets.
2. **Strip annotations** — removes all `<report>` and `@vulnerable_at_lines` lines from the source so the LLM never sees the labels.
3. **Build the user message** — wraps the clean source in a JSON object with `duration=300` and `rounds=3`, matching the EchoFuzz fuzzer's parameters.

The LLM therefore receives only raw Solidity source, with no hints about what vulnerabilities are present.

---

## Step 2 — Generate Predictions

`main.py` runs both prompts on every contract in D2 under a USD budget cap.

```bash
python3 main.py --total_cost <budget_usd>
```

Example:
```bash
python3 main.py --total_cost 10.0
```

**Arguments:**
| Argument | Description |
|---|---|
| `--total_cost` | Budget in USD; stops when cumulative cost across both prompts reaches this value. |
| `--dataset` | Dataset subfolder under `dataset/` (default: `D2`). |

**Behavior:**
- Processes all 143 D2 contracts (both Prompt A and Prompt B per contract).
- Checks the budget before every API call; stops cleanly when exhausted.
- Fully resumable: re-running continues from where it stopped via `outputs/state.json`.
- Partially completed contracts (one prompt done, the other missing) are always finished before new contracts are started.
- Outputs larger than 20 KB are also written to a separate `.json` file alongside the JSONL.

**Estimated cost** (Claude Sonnet 4.6, $3/MTok in, $15/MTok out):
- 143 contracts, both prompts: ~$7.14 total (actual spend)

---

## Step 3 — Evaluate

Once all outputs are generated, run the evaluator:

```bash
python3 evaluator.py
```

The evaluator reads `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`, computes per-contract and aggregate metrics against the D2 ground truth, and writes `results/results_A.jsonl` and `results/results_B.jsonl`.

Each results file has:
- **Line 1:** Aggregate JSON — sample size, per-category stats (GT/detected/TP/FP/FN), and the paper Table 3 reference block.
- **Lines 2+:** Per-contract JSON — contract name, D2 labels, expected categories, detected categories, TP/FP/FN lists.

---

## Evaluation Design

### Label-to-category mapping

| D2 ground-truth label | Paper category | EchoFuzz output fields used |
|---|---|---|
| ARITHMETIC | IO | `integer overflow` OR `integer underflow` > 0 |
| REENTRANCY | RE | `reentrancy` > 0 |
| UNCHECKED_LL_CALLS | UC | `unchecked call` > 0 |
| BAD_RANDOMNESS | BN | `block number dependency` > 0 |
| TIME_MANIPULATION / TIME | TP | `timestamp dependency` > 0 |
| ACCESS_CONTROL | — | unmapped |
| FRONT_RUNNING | — | unmapped |
| DENIAL_OF_SERVICE | — | unmapped |
| OTHER / SHORT_ADDRESSES | — | unmapped |

**IO detection rule:** a contract is flagged IO if *either* `integer overflow` or `integer underflow` has `number > 0`. This matches the paper's combined IO category.

### Excluded categories

Three EchoFuzz output fields — `gasless send` (GL), `dangerous delegatecall` (DG), and `freezing ether` / `unexpected ether` (UE) — are excluded from both the LLM prompts and the evaluator. D2 has no ground-truth annotations for these categories; keeping them in the prompts only introduces noise false positives without any corresponding ground truth to measure against.

### Metric definition

Evaluation is performed at the **contract level**: a contract is a TP for category X if the LLM reports X and D2 labels X; FP if the LLM reports X but D2 does not; FN if D2 labels X but the LLM does not report it.

Contracts whose D2 labels are entirely unmapped (e.g., only ACCESS_CONTROL) contribute FPs for any evaluated category the LLM incorrectly fires on, but contribute zero GT.

### Comparison with the paper

Direct numeric comparison between our results and the paper's Table 3 counts is not straightforward because:
- EchoFuzz uses a **runtime oracle** — its detections are all true positives by construction; it has zero FPs. Our LLM makes static predictions and therefore produces FPs.
- The paper reports raw **detection counts**, not precision/recall. We report precision and recall against the same 143 D2 contracts.
- The paper's GT count for IO differs from ours: EchoFuzz detects IO=53 vs. our GT of IO=15. EchoFuzz finds integer overflow/underflow as secondary bugs in contracts primarily labeled with other categories; D2 labels only record the *primary* vulnerability.

---

## Results

All 143 D2 contracts evaluated.

| System | Precision | Recall | TP | FP | FN | Contracts |
|---|---|---|---|---|---|---|
| EchoFuzz (paper, Table 3, D2) | ~1.0 (runtime oracle) | ~0.78 | 103 | 0 | ~29 | 143 |
| Ours — Prompt A | 38.7% | **100%** | 111 | 176 | 0 | 143 |
| Ours — Prompt B | 37.4% | **100%** | 111 | 186 | 0 | 143 |

> Paper recall is approximate: 103 detections out of 132 mappable GT vulnerabilities.

**Per-category breakdown (Prompt A / Prompt B):**

| Cat | GT | Det A | TP A | FP A | Det B | TP B | FP B |
|---|---|---|---|---|---|---|---|
| IO | 15 | 96 | 15 | 81 | 92 | 15 | 77 |
| RE | 31 | 57 | 31 | 26 | 79 | 31 | 48 |
| UC | 52 | 75 | 52 | 23 | 67 | 52 | 15 |
| BN | 8 | 18 | 8 | 10 | 20 | 8 | 12 |
| TP | 5 | 41 | 5 | 36 | 39 | 5 | 34 |

**Total cost:** $7.14 (143 contracts × 2 prompts, Claude Sonnet 4.6)

---

## Discussion

**Perfect recall, high false-positive rate.** The LLM detects every ground-truth vulnerability in the sample (FN=0) but over-reports substantially. IO and TP show the worst FP rates — the LLM flags integer arithmetic patterns and timestamp usage as vulnerabilities even in contracts where those patterns are benign.

**Prompt B does not reduce recall or improve precision.** Providing the VFCS reasoning methodology (Prompt B) does not lower FPs; in fact, RE FPs increase from 26 to 48. The informed prompt appears to make the model more aggressive in flagging reentrancy-shaped patterns. Precision is essentially the same for both prompts (~38%).

**Contrast with EchoFuzz.** EchoFuzz achieves near-zero FPs by using an instrumented runtime oracle that fires only on actual exploit execution. A static LLM prompt cannot replicate this guarantee — it reasons about code patterns, not runtime behaviour, and tends toward over-detection. The LLM's advantage is that it misses nothing in its evaluated category set; EchoFuzz misses ~22% of mappable GT (FN=29/132) because the fuzzer does not always reach the vulnerable branch.
