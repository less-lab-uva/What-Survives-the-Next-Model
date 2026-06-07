# Experiment Setup

**Input Reduction Enhanced LLM-based Program Repair**  
ICSE 2026 · DOI: 10.1145/3744916.3787760

Given a buggy C++ submission and failing input, the LLM generates a corrected program using Prompt A and Prompt B, evaluated on compilation and test pass rate.

---

## Prerequisites

- Python 3.8+
- `g++` (C++ compiler, for compiling submissions during dataset loading)

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

The LFTBench dataset (~1.8 GB) is hosted on Zenodo. Download and extract it with:

```bash
python download_dataset.py <zenodo_url>
```

`<zenodo_url>` can be any of:
- A Zenodo record URL: `https://zenodo.org/records/<id>`
- A DOI URL: `https://doi.org/10.5281/zenodo.<id>`
- A direct file link: `https://zenodo.org/records/<id>/files/lftbench.zip`

The script places the dataset at `dataset/lftbench/` (next to this file). Both `main.py` and `evaluator.py` read from that path automatically.

---

## Step 1 — Run the Experiment

Run the LLM on a random sample of eligible submissions using Prompt A or Prompt B:

```bash
# Run with Prompt A
python3 main.py --prompt A --n 50

# Run with Prompt B
python3 main.py --prompt B --n 50

# Run with both prompts
python3 main.py --prompt both --n 50
```

Key options:
- `--prompt`: `A`, `B`, or `both`
- `--n`: number of submissions to process
- `--seed`: random seed for sampling
- `--model`: override the default model name
- `--sleep`: seconds to wait between requests
- `--threads`: number of parallel worker threads

The script supports resuming — already-completed submissions are skipped on re-run.

Output is saved to:
```
outputs/
├── outputs_A.jsonl    # per-example records for Prompt A
└── outputs_B.jsonl    # per-example records for Prompt B
```

Each line contains: `submission_id`, `problem_id`, `failing_input`, `wa_output`, `expected_output`, `all_samples`, `fixed_code`, `prompt_sent`, `raw_response`, and `llm_response_time`.

---

## Step 2 — Evaluate

Compile and test each generated fix against the full LFTBench test suite:

```bash
python3 evaluator.py --prompt A
python3 evaluator.py --prompt B
python3 evaluator.py --prompt both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A
└── results_B.jsonl    # aggregate + per-instance results for Prompt B
```

---

## Metrics

- **compiled**: fraction of generated fixes that compile successfully.
- **fully_passed**: fraction of fixes that pass all test cases in the LFTBench test suite (Pass@1).
- **avg_sample_pass_rate**: average fraction of test cases passed per submission.
- **total_llm_time**: total LLM API response time in seconds, summed across all processed examples.
