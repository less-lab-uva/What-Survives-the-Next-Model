# Experiment Setup

This project generates JUnit test suites for Defects4J Java classes using Prompt A or Prompt B, then evaluates the generated tests with Maven + JaCoCo to measure line and branch coverage.

**Paper:** LLM Test Generation via Iterative Hybrid Program Analysis  
**Venue:** ICSE 2026  
**DOI:** 10.1145/3744916.3764553

---

## Prerequisites

- Python 3.8+
- Java 8 and Maven 3.9+ (required for Step 2 — evaluation only)

**Install Java and Maven:**

```bash
# Ubuntu/Debian
sudo apt install openjdk-8-jdk maven

# macOS (Homebrew)
brew install openjdk@8 maven
```

JaCoCo is declared as a plugin in each project's `pom.xml` — no separate install needed; Maven downloads it automatically on first run.

Install Python dependencies:
```bash
pip install -r requirements.txt
```

---

## Dataset

All data is in `data/` 

```
data/
├── defects4j-codefiles/        # JSON class lists for all 14 Defects4J projects
└── defects4j-subjects/        
    ├── Cli-40f/
    ├── Codec-18f/
    ├── Collections-28f/
    ├── Compress-47f/
    ├── Csv-16f/
    ├── Gson-16f/
    ├── JacksonCore-26f/
    ├── JacksonDatabind-112f/
    ├── JacksonXml-5f/
    ├── Jsoup-93f/
    ├── JxPath-22f/
    ├── Lang-4f/
    ├── Math-2f/
    └── Time-13f/
```

**Coverage note:** The paper evaluates 130 classes from all 14 projects. Classes are selected as public non-abstract with at least one method of cyclomatic complexity (CYC) > 10 and max CYC ≤ 40. Applying this filter programmatically yields 197 classes across 14 projects, but the paper's exact 130 involves undisclosed manual exclusions (e.g., inheritance-heavy classes) that cannot be reproduced. We restrict to the 4 projects where the automated filter exactly matches the paper's class counts — Codec-18f (7), Collections-28f (5), Csv-16f (3), Jsoup-93f (8) — giving **23 verified classes**. The remaining 10 projects are included in `data/` for reference.

---

## Step 1 — Run the Experiment

Generate JUnit test suites using Prompt A (black-box) or Prompt B (informed-technique).

```bash
export ANTHROPIC_API_KEY=your_key_here

python main.py --variant {A,B,both} [--n N] [--workers W]
```

To replicate our results, run:

```bash
python main.py --variant both --n 23
```

| Argument | Default | Description |
|---|---|---|
| `--variant` | `both` | Prompt(s) to run: `A`, `B`, or `both` |
| `--n` | entire dataset | Number of samples to process in total (already-processed ones are skipped), stratified across projects |
| `--workers` | `4` | Parallel threads |

Output is saved to `outputs/outputs_A.jsonl` and `outputs/outputs_B.jsonl`. Each line contains the generated tests, raw model response, and response time.

---

## Step 2 — Evaluate

Run Maven + JaCoCo on the generated tests. Java 8 and Maven must be on PATH.


```bash
module load maven/3.9.0 java/8
```

Then run:
```bash
python evaluator.py
```

Results are saved to:
```
results/
├── results_A.jsonl    # aggregate + per-class coverage for Prompt A
└── results_B.jsonl    # aggregate + per-class coverage for Prompt B
```

---

## Metrics

- **Line coverage** and **branch coverage** (%): measured by JaCoCo after compiling and running the generated tests
- **Pass rate** (%): proportion of generated test methods that pass (from Surefire XML reports)

---

## Notes

- Maven downloads project dependencies on first run — internet access required for `mvn test`.
