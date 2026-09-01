# dataFromPaper

Aggregated, repository-wide tables summarizing results across all 35 papers
studied in this repo. These are summary tables built from the per-paper
artifacts under `analysis/`, not raw paper data.

- [`results_summary.md`](results_summary.md): one row per paper, comparing the
  paper's originally reported result against the two single-prompt variants
  (`P_b`: black-box prompt, `P_w`: white-box prompt) on the same metric(s) the
  paper used. The best value in each row is bolded.
- [`categorized_analysis.md`](categorized_analysis.md): one row per paper,
  giving its task category, strategy category, and outcome symbol (`+`
  outperforms, `-` underperforms, `+-` mixed) from comparing the single-prompt
  replacements to the paper's technique. See the root
  [`README.md`](../README.md#categories-and-outcomes) for how these categories
  and outcomes are defined.

The `ID` column in both tables identifies the paper and corresponds to the
paper directories under `analysis/ICSE_<id>(<doi>)/`.
