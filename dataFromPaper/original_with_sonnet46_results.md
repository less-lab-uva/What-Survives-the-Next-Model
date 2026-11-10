This file compares three settings for each paper:
1. **Original:** the paper's technique with the paper's own LLM. Numbers are as reported in the paper.
2. **Single prompt:** our single-prompt approach with Claude Sonnet 4.6.
3. **Original w/ Sonnet 4.6:** the paper's technique unchanged, with only its LLM replaced by Claude Sonnet 4.6.

Comparison symbols: + = outperforms, - = underperforms, +- = mixed, = = tie. SP is the single prompt.

## Summary

| ID | Dataset | Metric | Original Result | Single Prompt | Original w/ Sonnet 4.6 | Original w/ Sonnet 4.6 vs. Original | SP vs. Original | SP vs. Original w/ Sonnet 4.6 |
|---|---|---|---|---|---|:---:|:---:|:---:|
| 52 | Defects4J | Line/Branch coverage/Pass Rate | 78.62/69.25/62.91 | 91.7/82.9/98.9 | 97.24/92.13/98.65 | + | + | +- |
| 189 | Custom GitHub derailment dataset | F1 @ threshold 0.3 | 90.10 | 90.91 | 89.50 | - | + | + |
| 232 | APPS, CodeContests, xCodeEval | Pass@1 | 65.33, 36.36, 38.67 | 70.54, 40.85, 55.04 | 71.32, 39.44, 57 | + | + | +- |
| 86 | HumanEval, HumanEval+, ClassEval, BigCodeBench | Pass@1 | 99.39, 98.17, 82, 85 | 100, 93.33, 71, 87.72 | 100, NA, NA, 87.72 | + | +- | = |
| 186 | LV-Parser evaluation dataset | Mean Accuracy | 93.60 | 86.77 | 92.68 | - | - | - |
| 11 | BGL, Spirit, Thunderbird, HDFS, Hadoop2, Hadoop3, Spark2, Spark3 | F1 | 97.5 | 18.5 | 92.70 | - | - | - |
