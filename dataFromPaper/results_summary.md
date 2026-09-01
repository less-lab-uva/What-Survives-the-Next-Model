## Results Summary

The table below summarizes the paper-reported results against the two
single-prompt variants. `P_b` denotes the black-box prompt and `P_w` denotes
the white-box prompt.

| ID | Paper's LLM | Dataset | Metrics | Original Result | P_b | P_w |
|---:|---|---|---|---|---|---|
| 256 | Claude-3.5-Sonnet | EchoFuzz D2 | #Vuln detected/TP/FP/FN | 103/103/**0**/8 | 287/**111**/176/**0** | 297/**111**/186/**0** |
| 54 | Claude-3.5-Sonnet | StatType-SO | F1 | **90.8** | 42.9 | 43.1 |
| 66 | Claude-3.5-Sonnet | xCodeEval (C, C#, C++, Go, Java, JS, Kotlin, PHP, Python, Ruby, Rust) | Pass@10 | 90.42, 87.34, 80.81, 90.46, 85.99, 86.40, 92.89, 99.23, 90.66, 85.89, 86.09 | **93.15, 93.15, 81.25**, 92.86, 63.38, **100.00, 96.77, 100.00, 92.86**, 88.24, **100.00** | 86.3, 90.41, 81.25, **96.55**, 66.20, **100.00**, 90.32, 89.92, 89.47, **100.00**, 90.00 |
| 25 | CodeLlama-7B | Custom security code review dataset | F1/SecureBLEU | **71.98**/**29.31** | 36.62/18.59 | 32.97/16.59 |
| 73 | DeepSeek-Coder-V2-Lite | HumanEval, MBPP | Accuracy/RSR | 94.5/76.3, 80/39 | **100**/**100**, **91**/**72.56** | 98.17/92.11, 90/69.51 |
| 97 | DeepSeek-R1 | FoundRoot A-D | MRR | 56.9, 61, **85.8**, **93.1** | 61.33, 58, 84.44, 92.52 | **64.85**, 61.79, 83, 90.6 |
| 102 | DeepSeek-V3 | CodaMosa | (Line + Branch) coverage | **62** | 42.55 | 46.17 |
| 154 | DeepSeek-V3 | DB2 (Ethereum) | F1 | **88.46** | 40 | 28 |
| 219 | DeepSeek-V3 | FSD, RAC, PURE, BP, US, LMC | N-F1/R-F1/Pass_rate | **71.32**/**60.48**/97.78 | 48.53/49.99/96.34 | 49.65/50.71/**98.38** |
| 303 | DeepSeek-V3 | FSD | F1 | **50.94** | 38.64 | 35.71 |
| 88 | DeepSeek-V3 | LFTBench | Pass@1 | 45.9 | 68 | **72** |
| 38 | DeepSeek-V3 | SynthNL, ConfoNL, LangNL, SpecNL | Accuracy | **82** | 61.01 | 58.18 |
| 104 | Gemini-2.5-Flash | FSM-AP, FSM-S, REG, RobotExplain, Ventilator, Deepstl-test | Pass@10 | **100**, **100**, **100**, **71.7**, **61.2**, **100** | **100**, 66.7, **100**, 0, 20.7, 25 | **100**, **100**, **100**, 20, 27.6, **100** |
| 86 | Gemini-2.5-Flash | HumanEval, HumanEval+, ClassEval, BigCodeBench | Pass@1 | 99.39, **98.17**, **82**, 85 | **100**, 93.33, 71, **87.72** | **100**, 93.33, 74, 86.84 |
| 232 | Gemini-1.5-Flash | APPS, CodeContests, xCodeEval | Pass@1 | 65.33, 36.36, 38.67 | **70.54**, 40.85, **55.04** | 64.34, **43.66**, 48.06 |
| 11 | GLM4-2.0-Flash | BGL, Spirit, Thunderbird, HDFS, Hadoop2, Hadoop3, Spark2, Spark3 | F1 | **97.5** | 18.5 | 14.9 |
| 186 | GPT-4.1 | LV-Parser evaluation dataset | Mean accuracy | **93.60** | 82.99 | 86.77 |
| 98 | GPT-4.1-mini | MultiPL-E Java | Pass@1 | 61.90 | **78.85** | 77.88 |
| 32 | GPT-4o | Alexandria | Hit@k/F1 | **69**/**25** | 40.0/20.9 | 40.0/17.3 |
| 103 | GPT-4o | AGORA+ | Precision/Recall | **85.1**/**83** | 53.7/41.6 | 61.8/40.6 |
| 254 | GPT-4o | Defects4J V1.2, Defects4J V2.0 | Pass test | **52.94**, 43.38 | 43.33, 38.67 | 46, **47.33** |
| 18 | GPT-4o | HumanEval, LiveCodeBench | Pass@1 | 90.2, 50.2 | **99.1**, 52.51 | 98.2, **52.8** |
| 70 | GPT-4o | Py150, Netbeans | Precision/Recall | **73.1**/68.1, 72.11/69.46 | 66.12/65.47, **72.7**/**72.57** | 70/**69.06**, 71.5/71.38 |
| 82 | GPT-4o | PrimeVul | PC | 18.62 | 13.37 | **22.17** |
| 237 | GPT-4o | PrOntoQA-OOD, ProofWriter, FOLIO | Average macro F1 | **94.26**, **91.24**, **84.42** | 76.02, 65.79, 56.82 | 77.74, 84.28, 66.66 |
| 77 | GPT-4o | TPC-DS, SQLProcBench | Translation accuracy | **97.98** | 60.61 | 61.62 |
| 10 | GPT-4o-mini | CoderEval | Pass@1 | 36.52 | **54.62** | 54.55 |
| 108 | GPT-o3-mini | GuideSyn .mls benchmark | %solved | 78 | 81.25 | **83.75** |
| 14 | GPT-4o mini | SWE-bench | Differentiating rate | **29.3**, 27.2 | 15.56, **36.73** | 11.11, 24.49 |
| 52 | Llama 3.3 70B | Defects4J | Line/Branch coverage, Pass rate | 78.62/69.25, 62.91 | 89.3/80.3, **98.9** | **91.7**/**82.9**, 98.4 |
| 6 | Qwen2.5-14B | HPC (Loghub-2k) | PA/PTA/RTA/GA | **99.3**/71.7/**82.6**/**93.4** | 90.5/72.9/76.1/90 | 90.5/**78.3**/78.3/90.5 |
| 189 | Qwen2.5-32b-instruct | Custom GitHub derailment dataset | F1@threshold 0.3 | 90.10 | 85.82 | **90.91** |
| 20 | Qwen2.5-72B | CoCoClaNeL | MCC | 25.9 | **65.72** | 65.41 |
| 19 | Qwen2.5-Coder-7B-Instruct | HumanEval, MBPP, LiveCodeBench | Pass@1 | 90.9, 88.6, 36.7 | **100**, **100**, 48.68 | **100**, 99.29, **50.94** |
| 42 | StarCoder2-7B (v1), CodeLlama-Python-7B (v2) | Tfv1 Synthetic | Exact match@1 | **83.53** (v1), **60.86** (v2) | 71.4 (v1), 36.5 (v2) | 70.9 (v1), 36.3 (v2) |
