# Experiment Setup

This project generates ML-like functional programs for benchmark synthesis problems using Prompt A or Prompt B, then evaluates correctness by running the generated programs through the Trio synthesizer.

**Paper:** Distance-Guided Search in Program Synthesis with Imperfect LLM Solutions  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3787779

---

## Prerequisites

- Python 3.8+
- Linux x86_64 (required for the `trio` binary — see below)

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Trio Binary

The `trio` binary is included in this repository (pre-built Linux x86_64 ELF executable). It is the Trio program synthesizer used to check whether a generated solution satisfies the benchmark specification.

```
trio    # pre-built Linux x86_64 — run as ./trio
```

<<<<<<< Updated upstream
<<<<<<< HEAD
=======
>>>>>>> Stashed changes
> **Non-Linux platforms:** `trio` will not run on macOS or Windows. To evaluate on a non-Linux machine, build Trio from source for your platform, then replace the `trio` binary in this directory with your build:
> ```bash
> git clone https://github.com/jmct/trio
> cd trio
> # follow the build instructions in the repo, then copy the binary here
> cp trio /path/to/this/repo/trio
> ```
<<<<<<< Updated upstream
=======
> To build Trio from scratch, follow the instructions at https://github.com/pslhy/trio, then copy the resulting binary here.
>>>>>>> ebf85110d51bb1a2f9db30f10e56a25dd830ffab
=======
>>>>>>> Stashed changes

The binary is already marked executable. If needed:
```bash
chmod +x trio
```

---

## Datasets

<<<<<<< Updated upstream
<<<<<<< HEAD
The benchmark problems are included in this repository under `data/` (80 `.mls` files, ~320 KB total):
=======
The benchmark problems are included in this repository under `data/` (80 `.mls` files):
>>>>>>> ebf85110d51bb1a2f9db30f10e56a25dd830ffab
=======
The benchmark problems are included in this repository under `data/` (80 `.mls` files, ~320 KB total):
>>>>>>> Stashed changes

```
data/
├── automata_visited_states.mls
├── automata_visited_sum.mls
├── bool_always_false.mls
└── ...   # 80 benchmark files in total
```

---

## Step 1 — Run the Experiment

Generate synthesized programs using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --n 80
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset (80) | Number of problems to process in total (already-processed ones are skipped), stratified across benchmarks |
| `--seed` | `42` | Random seed for stratified sampling |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the generated program, the raw model response, and response time.

---

## Step 2 — Evaluate

Score the generated programs by running them through `trio`:

```bash
python evaluator.py --variant both
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-instance results for Prompt A (includes avg response time)
└── results_B.jsonl    # aggregate + per-instance results for Prompt B (includes avg response time)
```

---

## Metric

We report **% solved**: a problem is considered solved if the generated program passes the Trio correctness check. This matches the LLM-Only baseline metric used in the paper.
