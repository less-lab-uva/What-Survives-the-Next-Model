# dataFromPaper

Aggregated, repository-wide tables summarizing results across all 35 papers
studied in this repo. These are summary tables built from the per-paper
artifacts under `analysis/`, not raw paper data.

- [`single_prompt_sonnet46_results.md`](single_prompt_sonnet46_results.md): one row per paper, comparing the
  paper's originally reported result against the two single-prompt variants
  (`P_b`: black-box prompt, `P_w`: white-box prompt) on the same metric(s) the
  paper used. The best value in each row is bolded.
- [`categorized_analysis.md`](categorized_analysis.md): one row per paper,
  giving its task category, strategy category, and outcome symbol (`+`
  outperforms, `-` underperforms, `+-` mixed) from comparing the single-prompt
  replacements to the paper's technique. See the root
  [`README.md`](../README.md#categories-and-outcomes) for how these categories
  and outcomes are defined.
- [`original_with_sonnet46_results.md`](original_with_sonnet46_results.md):
  for six papers, compares the original technique, the single-prompt variants,
  and the original technique with its LLM replaced by Claude Sonnet 4.6.
- [`single_prompt_sonnet55_results.md`](single_prompt_sonnet55_results.md): for 13 papers, compares the
  original result with our single-prompt result on Claude Sonnet 4.6 and
  Claude Sonnet 5.5.

The `ID` column in these tables identifies the paper and corresponds to the
paper directories under `analysis/ICSE_<id>(<doi>)/`.
