This file compares the paper's original result with our single-prompt result on Claude Sonnet 4.6 and on Claude Sonnet 5.5.

All values are percentages. Values for different metrics are separated by /, and values for different datasets by a comma.

## Summary

| ID | Citation Number | Dataset | Metric | Original Result | Sonnet 4.6 | Sonnet 5.5 |
|---|---|---|---|---|---|---|
| 11 | EP23 | BGL, Spirit, Thunderbird, HDFS, Hadoop2, Hadoop3, Spark2, Spark3 | F1 | **97.5** | 18.5 | 19.23 |
| 25 | EP16 | Custom security code review dataset | F1 | **71.98** | 36.62 | 44.19 |
| 32 | EP32 | Alexandria | F1 | 25 | 20.9 | **28.90** |
| 38 | EP8 | SynthNL, LangNL, SpecNL, ConfoNL | Accuracy | **82** | 59.12 | 62.58 |
| 42 | EP15 | Tfv1 Real, Tfv1 Synthetic | Exact Match@1 | 60.86 (v2) | 36.5 (v2) | **66.83** (v2) |
| 54 | EP20 | StatType-SO | F1 | **90.80** | 42.9 | 42.80 |
| 77 | EP29 | TPC-DS, SQLProcBench | Translation accuracy | **97.98** | 61.62 | 63.64 |
| 102 | EP13 | CodaMosa | Line + Branch Coverage | **62** | 46.17 | 56.02 |
| 103 | EP11 | AGORA+ | Precision | **85.10** | 76.80 | 75.00 |
| 154 | EP27 | DB2 (Ethereum) | F1 | **88.46** | 40 | 47.62 |
| 186 | EP31 | LV-Parser evaluation dataset | Mean Accuracy | **93.60** | 86.77 | 89.28 |
| 237 | EP35 | PrOntoQA-OOD, ProofWriter, FOLIO | Average Macro F1 | **94.26**, 91.24, **84.42** | 77.74, 84.28, 66.66 | 84.14, **93.41**, 69.20 |
| 303 | EP22 | FSD | F1 | **50.94** | 38.64 | 38.46 |
