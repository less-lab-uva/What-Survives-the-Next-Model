# Ripple — LLM Replacement Study on CIA Benchmark

This repository extends the original [Ripple](https://github.com/se-doubleblind/ripple) pipeline with an LLM replacement study. We replace the full two-phase Ripple pipeline with a single Claude Sonnet 4.6 call and evaluate it on the same 100-instance CIA benchmark used in the original paper, using the same Macro Precision, Recall, F1, and Hit@k metrics.

---

## Overview

Ripple is an intent-aware change impact analysis (CIA) tool that, given a bug report and a seed edit location, predicts which methods in a Java repository must be co-modified to fully resolve the described bug. The original pipeline operates in two phases:

1. **Recall-Focused phase**: expands the seed location into a dependence-enhanced impact set using evolutionary coupling (commit history) and structural dependence coupling (call/class-member dependencies).
2. **Precision-Focused phase**: a Planner LLM generates a change plan via Chain-of-Thought; a Reasoner LLM independently predicts impacted methods for each dependence cluster, applying sample-and-marginalize (intersection across 5 candidates per cluster, union across clusters) to produce the final impact set.

In this study, we replace both phases with a single LLM call using two prompt strategies:

- **Prompt A (Black-box):** Provides the bug report, seed method source, full repository structure (as XML with method summaries and source), and commit history. Asks the model to directly return the list of impacted methods with no methodology guidance.
- **Prompt B (Informed):** Extends Prompt A with an explicit 10-step reasoning process that walks through commit history mining, dependence-enhanced set expansion (direct/indirect call and class-member dependencies), three-pass repository slicing, internal change plan generation, and intersection-based aggregation with change-plan tie-breaking — replicating the structure of the original Ripple reasoning without the static analysis preprocessing.

Both prompts use the same few-shot example (instance-00050, apache/ant-ivy, seed=`getConflictManager`).

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

**Git** must be available on `PATH` (used to clone repos and check out parent commits).

---

## Step 1 — Generate Predictions

`main.py` is fully self-contained. It identifies the 100 paper instances from `assets/all-outputs.zip`, samples a 10% pool (10 instances), automatically clones the required repos and prepares input files, then runs both Prompt A and Prompt B on each instance.

```bash
python3 main.py <budget_usd>
```

Example:
```bash
python3 main.py 15.0
```

**What it does automatically:**
1. Reads `assets/all-outputs.zip` to identify the 100 instances the paper evaluated.
2. Selects a pool of 10 instances (10% of 100):
   - Already-touched instances from prior runs are always kept.
   - Remaining slots are filled randomly from untouched candidates.
3. For each pool instance missing input files, clones the Apache repo into `repos/<project>/` and checks out the parent commit, then runs `extract_methods.py` to produce three input files.
4. Runs Prompt A and Prompt B on each instance in the pool, stopping when the budget is exhausted.

**Budget and resumability:**
- Re-running with a new budget picks up exactly where the previous run stopped.
- Partial instances (one prompt done, the other not) are always completed before new instances are started.
- Cost is tracked in `tokens_A.jsonl` / `tokens_B.jsonl`; `main.py` reads these on startup to compute remaining budget.

**Token size handling:**
- Instances are pre-checked: estimated tokens = `(sys_chars + user_chars) / 3.5`. Instances exceeding 950,000 tokens are discarded from the pool.
- A `BadRequestError` catch handles cases where the estimate was too optimistic.

**Outputs** (under `outputs/`):

| File | Description |
|---|---|
| `outputs_A.jsonl` | One JSON line per instance: `instance_id`, `impacted_methods` (list of `"ClassName,methodName"` strings), and metadata |
| `outputs_B.jsonl` | Same for Prompt B |
| `tokens_A.jsonl` | Token counts, cost, and wall-clock time per API call for Prompt A |
| `tokens_B.jsonl` | Same for Prompt B |

If the model's response cannot be parsed as JSON, a `parse_failed: true` entry is written to the outputs JSONL and the raw response is saved to `outputs/<instance_id>_prompt<L>_raw_<timestamp>.txt`. If you delete a `parse_failed` entry from `outputs_*.jsonl`, also delete its corresponding line from `tokens_*.jsonl` to avoid double-counting cost on the next run.

**Estimated cost** (Claude Sonnet 4.6, $3/MTok input, $15/MTok output):
- Typical instance: 200K–900K input tokens → $0.60–$2.75 per prompt call
- Both prompts on 10 instances: ~$25–30 total

---

## Step 2 — Prepare Inputs (Standalone, Optional)

`main.py` prepares inputs automatically. If you need to prepare a specific instance manually:

```bash
python3 extract_methods.py <instance_id> <repo_dir> [output_dir]
```

Example:
```bash
python3 extract_methods.py instance-00270 repos/commons-math input/instance-00270
```

This produces three files under `input/<instance_id>/`:

| File | Description |
|---|---|
| `issue.json` | Instance metadata: `instance_id`, `repo`, `commit`, `parent_commit`, `seed_file`, `seed_method`, `focal_method_id`, `issue_summary`, `issue_description`, `seed_method_source`. No ground-truth fields. |
| `repo_structure.xml` | All non-test Java methods in the repo (at parent commit) as XML: `<package>` → `<class>` → `<method>` with `<summary>` (Javadoc or auto-generated) and `<source>` (full method body). |
| `commit_history.json` | Git log up to the parent commit: `{"{commit}<sep>{parent_commit}": {hash: [files], ...}}` |

**Non-test Java files**: path parts not containing `test`/`tests` (case-insensitive) and stem not ending in `test`/`tests`.

The repo must already be cloned and checked out at the parent commit. `main.py` handles cloning automatically; for standalone use, clone manually:

```bash
git clone https://github.com/<org>/<project>.git repos/<project>
git -C repos/<project> checkout <parent_commit>
```

---

## Step 3 — Evaluate

Once `outputs_A.jsonl` / `outputs_B.jsonl` exist, run the evaluator:

```bash
python3 evaluator.py          # evaluate both prompts
python3 evaluator.py A        # evaluate prompt A only
python3 evaluator.py B        # evaluate prompt B only
```

**What it does:**
1. Extracts ground-truth method names from the commit diff stored in `cia-dataset.json`:
   - Primary: scans `+/-` diff lines and `@@` context lines for method signatures.
   - Fallback: when a file yields no signatures (body-only change), checks out the source from `repos/` at the parent commit and maps `@@` hunk line numbers to the enclosing method via brace-walking.
2. Normalizes LLM predictions: converts `"ClassName,methodName"` → `"ClassName.methodName"` and removes the seed method.
3. Computes per-instance Precision, Recall, F1.
4. Aggregates into Table 1 (macro mean P/R/F1 + Hit@5 + Hit@10 + Hit@custom).
5. Evaluates the original Ripple pipeline (claude/gpt/gemini) on the same instances from `all-outputs.zip` using numeric ID-space ground truth from `impact-set-methods` in `cia-dataset.json`.

**Results** (under `results/`):

| File | Description |
|---|---|
| `results_A.jsonl` | Line 1: aggregate `{type, prompt, n_instances, table1, original_pipeline}`. Lines 2+: per-instance details. |
| `results_B.jsonl` | Same for Prompt B |

---

## Evaluation Metrics

Ground truth (AIS) is the set of method names changed in the commit (excluding the seed method), extracted from the diff.

- **Precision** = |predicted ∩ AIS| / |predicted|
- **Recall** = |predicted ∩ AIS| / |AIS|
- **F1** = 2 × Precision × Recall / (Precision + Recall)
- **Macro** = mean over all instances
- **Hit@k** = probability that at least one ground-truth method appears in a random sample of k predicted methods (averaged over 100 random trials, seed=42)
- **Hit@custom** = same as Hit@k but k = |predicted| per instance

---

## Results

Both tables below cover the same 5 instances that our pipeline has evaluated so far, enabling a direct comparison. The original pipeline numbers here differ from the paper's Table 1 (which covers all 100 instances) for two reasons: (1) we score only on our 5-instance subset, and (2) the original pipeline predictions are evaluated in numeric ID-space (method IDs from `impact-set-methods` in `cia-dataset.json` matched against predictions in `all-outputs.zip`), while our predictions are evaluated in name-space (method names extracted from the commit diff) — an inherent limitation because the `all-methods.json` ID-to-name mapping is unavailable.

**Original Ripple on the same 5 instances (ID-space GT):**

| System | Hit@custom | Macro P | Macro R | Macro F1 |
|---|---|---|---|---|
| Ripple w/ GPT-4o | 80.0% | 39.9% | 41.7% | 35.6% |
| Ripple w/ Claude-3.5 Sonnet | 80.0% | 35.7% | 47.3% | 37.8% |
| Ripple w/ Gemini-2.0 Flash | 60.0% | 36.3% | 25.2% | 29.6% |

**Ours — single Claude Sonnet 4.6 call (same 5 instances, name-space GT):**

| Prompt | Hit@custom | Macro P | Macro R | Macro F1 | 
|---|---|---|---|---|
| Prompt A (Black-box) | 40.0% | 20.0% | 22.0% | 20.9% | 
| Prompt B (Informed CoT) | 40.0% | 16.7% | 18.0% | 17.3% |

> Results will update as the remaining 5 instances complete (10 total planned). For reference, the paper's Table 1 reports Ripple w/ GPT-4o at F1=25.0% on all 100 instances.

---

## Analysis

### Comparison with Paper Results

The table below places our 5-instance results alongside the original Ripple pipeline evaluated on those same 5 instances (ID-space GT) and the paper's full-benchmark Table 1 (100 instances, ID-space GT).

| System | Eval space | n | Macro P | Macro R | Macro F1 | Hit@custom |
|---|---|---|---|---|---|---|
| Ripple w/ GPT-4o (paper Table 1) | ID-space | 100 | — | — | 25.0% | — |
| Ripple w/ GPT-4o (our 5 instances) | ID-space | 5 | 39.9% | 41.7% | 35.6% | 80.0% |
| Ripple w/ Claude-3.5 Sonnet (our 5 instances) | ID-space | 5 | 35.7% | 47.3% | 37.8% | 80.0% |
| Ripple w/ Gemini-2.0 Flash (our 5 instances) | ID-space | 5 | 36.3% | 25.2% | 29.6% | 60.0% |
| **Ours — Prompt A (Black-box)** | name-space | 5 | 20.0% | 22.0% | 20.9% | 40.0% |
| **Ours — Prompt B (Informed CoT)** | name-space | 5 | 16.7% | 18.0% | 17.3% | 40.0% |

Two evaluation-space caveats apply before reading these numbers:

1. The original pipeline is scored in numeric ID-space (method IDs from `impact-set-methods` matched against predictions in `all-outputs.zip`), while our pipeline is scored in name-space (method names extracted from the commit diff). These are not identical metrics; the name-space extractor can miss body-only changes, and the LLM can use slightly different name formats. The comparison is directional, not exact.
2. The original pipeline numbers on our 5 instances (35–38% F1) are substantially higher than the paper's full-100 number (25% F1), which suggests our 5-instance sample happens to be easier than average. Our results are therefore evaluated on a relatively favorable subset and still fall far short.

**Per-instance results (Prompt A / Prompt B):**

| Instance | Repo | GT methods | GT files | Prompt A F1 | Prompt B F1 |
|---|---|---|---|---|---|
| 00111 | ant-ivy | 2 | 1 | 0.500 | 0.500 |
| 00632 | commons-net | 10 | 14 | 0.545 | 0.364 |
| 00270 | commons-math | 6 | 8 | 0.000 | 0.000 |
| 00717 | giraph | 3 | 2 | 0.000 | 0.000 |
| 00070 | ant-ivy | 9 | 6 | 0.000 | 0.000 |

Three of five instances score zero under both prompts. Only the two instances where the model happened to correctly name at least one impacted method contribute any score. Hit@custom (40%) means the model includes at least one correct prediction in only 2 of 5 instances.

### Why Our Results Are Poor

**1. No static analysis preprocessing — the fundamental gap.**
The original Ripple pipeline never asks its LLM to search a raw repository. Phase 1 runs static analysis (evolutionary coupling via git history, call/class-member dependence graphs) to pre-compute a small, structured neighborhood around the seed method. The LLM in Phase 2 reasons over this pre-filtered candidate set, not over thousands of methods. We give Claude the entire repository as a flat XML structure and ask it to identify the right methods cold. This is a fundamentally harder problem: the model must simultaneously perform the static analysis reasoning that Phase 1 handles deterministically and the intent-reasoning that Phase 2 handles with a focused candidate list.

**2. Severe under-prediction.**
The model consistently predicts far fewer methods than the ground truth contains. Instance 00070 has 9 GT methods but both prompts predict only 3, with zero overlap. Instance 00270 has 6 GT methods but Prompt A predicts 2 (zero overlap) and Prompt B predicts 1 (zero overlap). The original pipeline's recall-focused Phase 1 guarantees broad coverage by construction; without it, the model is conservative and misses the bulk of the impact set.

**3. Long-context degradation.**
Input sizes for these instances run 200K–900K tokens. At that scale, LLMs suffer well-documented quality degradation: relevant methods scattered across a multi-thousand-line XML are easily overlooked, and the model's attention over the middle of the context is weakest. The original pipeline sidesteps this by feeding the LLM only a pre-filtered, compact candidate set per dependence cluster.

**4. Correct class, wrong method.**
Instance 00717 illustrates a failure mode where the model correctly identifies the affected classes (`EdgeReaderWrapper`, `VertexReaderWrapper`) but predicts the wrong methods within them (`initialize` for both), while the GT is `getCurrentSourceId`, `nextEdge`, and `nextVertex`. The model appears to use a coarse heuristic — "which class is most likely involved?" — but cannot pinpoint *which specific method* inside that class was co-modified without the fine-grained dependency graph that Ripple's Phase 1 provides. Correct class attribution yields no partial credit under exact-match F1, so the result is a hard zero despite the model reasoning in the right direction at the class level.

**5. Prompt B underperforms Prompt A.**
The informed Chain-of-Thought prompt (Prompt B) was designed to replicate Ripple's reasoning structure in 10 explicit steps — commit history mining, dependency expansion, three-pass slicing, intersection-based aggregation. Instead of helping, it slightly worsens F1 (17.3% vs 20.9%). Committing the model to intermediate reasoning steps that require precise symbol-level tracking (e.g., "enumerate all direct call-graph neighbors of the seed method") over thousands of methods in a 900K-token context leads to cascading errors: wrong intermediate sets propagate into the final prediction. The black-box prompt at least lets the model use its own implicit reasoning strategy without being forced into steps it cannot execute reliably at this scale.
