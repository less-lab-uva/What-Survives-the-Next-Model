"""Construct the input + label file pairs for the reasoning-verification oracle.

For each (dataset, model) we emit two files in the same folder, same records/order, linked by
`idx` (primary key):
  inputs/<dataset>/<model>.json         = the chain to verify  {idx, premises, question, reasoning_steps}
  inputs/<dataset>/<model>_labels.json  = the gold             {idx, step_correctness_label,
                                                                has_valid_proof_path_label}

Input fields come from the RQ1_2 *_baseline_*.json files (a prompting baseline already in the exact
shape we want: numbered premises, `question` as a string, `reasoning_steps` filtered+numbered to the
steps that carry a label — and judge-independent). The gold comes from the matching
*_manual_annotation.json (the human label `step_correctness_label_manual_annotation`).

main.py reads the <model>.json files; the evaluator joins outputs to <model>_labels.json on idx.
Prompt-example instances are excluded from both. Source data lives in the MATP artifact repo.
Run from the analysis directory:  python3 utils/build_inputs.py
"""

import os
import sys
import json
import glob

SRC = "/opt/devel/repos/icse_analysis/zxyhp--MATP/workspace/dataset_v_last/RQ1_2"
OUT = "inputs"
JUDGE = "deepseekr1"   # which baseline file to read the (judge-independent) input from

DATASETS = ["folio", "prontoqa_ood", "proofwriter"]
GOLD_STEPS = "step_correctness_label_manual_annotation"   # human gold, per filtered step
GOLD_PATH = "has_valid_proof_path_label"

# Instances used as few-shot examples in prompts/meta_prompt.txt — excluded from evaluation.
PROMPT_EXAMPLE_IDX = {
    "147_431",                                          # FOLIO   (Vic DiCara)
    "4hop_ProofsOnly_random_noadj_example55_example0",  # PrOntoQA (Sally)
    "ProofWriter_RelNoneg-OWA-D5-668_Q8",               # ProofWriter (the lion)
}

if not os.path.isdir(SRC):
    sys.exit(f"ABORT: source data not found at {SRC}")

n_pairs = grand_total = grand_excluded = 0
for ds in DATASETS:
    os.makedirs(os.path.join(OUT, ds), exist_ok=True)
    for baseline_file in sorted(glob.glob(os.path.join(SRC, ds, f"*_baseline_{JUDGE}.json"))):
        gen_model = os.path.basename(baseline_file)[:-len(f"_baseline_{JUDGE}.json")]
        manual_file = os.path.join(SRC, ds, f"{gen_model}_manual_annotation.json")
        if not os.path.exists(manual_file):
            sys.exit(f"ABORT: missing manual-annotation file {manual_file}")
        gold = {r["idx"]: r for r in json.load(open(manual_file, encoding="utf-8"))}

        inputs, labels, excluded = [], [], 0
        for r in json.load(open(baseline_file, encoding="utf-8")):
            if r["idx"] in PROMPT_EXAMPLE_IDX:
                excluded += 1
                continue
            g = gold[r["idx"]]
            if len(r["reasoning_steps"]) != len(g[GOLD_STEPS]):       # alignment invariant
                sys.exit(f"ABORT: step/label length mismatch for {r['idx']} in {baseline_file}")
            inputs.append({"idx": r["idx"], "premises": r["premises"],
                           "question": r["question"], "reasoning_steps": r["reasoning_steps"]})
            labels.append({"idx": r["idx"], "step_correctness_label": g[GOLD_STEPS],
                           "has_valid_proof_path_label": g[GOLD_PATH]})

        json.dump(inputs, open(os.path.join(OUT, ds, f"{gen_model}.json"), "w", encoding="utf-8"), indent=2)
        json.dump(labels, open(os.path.join(OUT, ds, f"{gen_model}_labels.json"), "w", encoding="utf-8"), indent=2)
        print(f"{ds}/{gen_model:38} {len(inputs):3} records" + (f"  (-{excluded} prompt-example)" if excluded else ""))
        n_pairs += 1
        grand_total += len(inputs)
        grand_excluded += excluded

print(f"\n{n_pairs} input/label pairs, {grand_total} records ({grand_excluded} prompt-example excluded)")
