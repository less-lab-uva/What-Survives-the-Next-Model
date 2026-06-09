# Experiment Setup

**IntentFix: Automated Logic Vulnerability Repair via LLM-Driven Intent Modeling**
ICSE 2026 · DOI: 10.1145/3744916.3773260

Given a vulnerable code snippet (a logic vulnerability from the CWE-840 family), the LLM generates
a corrected version in a single pass using the **zero-shot** or **CoT** prompt. Generated patches
are then scored for correctness by an AI oracle. This reproduces the **RQ1 baselines** — the
zero-shot and Chain-of-Thought reference points the paper measures IntentFix against.

---

## Prerequisites

- Python 3.8+

Install Python dependencies:
```bash
pip install -r requirements.txt
```

Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY=your_key_here
```

---

## Dataset

The dataset is bundled at `dataset/intentfix_pairs.jsonl` — 1,107 vulnerability-patch pairs derived
from the IntentFix artifact (the same set the paper reports: CWE-770 accounts for 72.6%). Each line
is a JSON record with:

- `pair_id` — pair identifier (`pair_XXXX`)
- `cwe`, `cve` — vulnerability identifiers
- `buggy_code` — the vulnerable file (model input)
- `human_patch` — the maintainer's fix (ground truth, used only by the oracle)

The full set is large; `main.py` draws a **CWE-stratified sample** (default `--n 200`) so a run is
cheap. Pass a larger `--n` to scale up.

**Held-out few-shot examples.** `pair_0010` (PHP, CWE-639) and `pair_1011` (Go, CWE-770) are embedded
as few-shot demonstrations in `prompts/meta_prompt.txt` (and the generated `prompt_A`/`prompt_B`).
They are listed in `dataset/heldout_fewshot_ids.json` and **must be excluded from any evaluation
sample** to avoid train/test leakage. Build the dataset with `python3 utils/produce_dataset.py`
(fetches the artifact + attaches the CWE description from the MITRE CWE API).

---

## Step 1 — Generate patches

```bash
python3 main.py --condition zero_shot --n 200
python3 main.py --condition cot       --n 200
```

For each sampled snippet this fills the prompt (`prompts/zero_shot.txt` / `prompts/cot.txt`) with the
buggy code + CWE/CVE, calls Claude (`claude-sonnet-4-6`, `temperature=0.0`), and extracts the patch.
Results are cached to `outputs/outputs_<condition>.jsonl` (re-running resumes from cache).

---

## Step 2 — Evaluate

```bash
python3 evaluator.py --condition zero_shot
python3 evaluator.py --condition cot
```

The AI oracle is given the **vulnerable code, the generated patch, the ground-truth fix, and the CWE**
(paper section 4.4.1) and judges correctness on two criteria: (1) does it fix the vulnerability, and
(2) does it preserve functionality without new bugs. Results are written to
`results/results_<condition>.jsonl` (aggregate accuracy + per-CWE breakdown + per-instance verdicts).

---

## Metric

**Patch Accuracy** — the fraction of generated patches the AI oracle judges correct. The paper reports
this both via the AI oracle and via manual expert validation (Table 2). We report only the AI-oracle
accuracy.

---

## Differences from the original

This reproduction simplifies and corrects the released artifact:

- **Baselines only.** We reproduce the zero-shot and CoT baselines, not the full multi-phase IntentFix
  pipeline (intent modeling → semantic-gap detection → patch & verify).
- **Single judge model, Claude.** Generation and judging both use `claude-sonnet-4-6`; the paper used
  OpenAI `o4-mini` as an independent oracle. Claude-judging-Claude introduces self-evaluation bias, so
  our absolute numbers are not directly comparable to the paper's.
- **Corrected oracle inputs.** The original artifact's evaluator read `result["inputs"][...]`, a key
  never populated by the generator, so its oracle received an *empty* ground-truth fix and no CWE. Here
  the oracle receives all four inputs the paper describes.
- **Deterministic.** `temperature=0.0` is set explicitly (the artifact's Claude calls left it unset).
- **CoT path added.** The artifact ships a `cot.txt` prompt but no code that runs it; this adds one.
