"""Macro-F1 for our reasoning step-verification oracle (RQ1).

Computed the way the paper's rq1_2_cale_marco_f1.py does: map each step label
{True:0, False:1, Unknown:2}, flatten every step across all instances of one (dataset, model),
then macro-averaged F1 against the manual-annotation gold. The F1 is computed directly here
(identical to sklearn's f1_score average="macro") — no third-party dependency.

Reads the two committed prediction files outputs/output_A.jsonl and outputs/output_B.jsonl (each
line tagged with dataset/model/idx), groups by (variant, dataset, model), and joins to the gold in
inputs/<ds>/<model>_labels.json by idx. Reports per (variant, dataset, model), aggregated per
dataset. Writes results/metrics.json.

An instance whose predicted label count differs from the gold (or whose prediction is missing) can't
be aligned, so it is counted as `unaligned` and reported rather than silently dropped.

Run from the analysis directory:  python3 evaluator.py
"""

import os
import sys
import json
import glob
from collections import defaultdict

LABEL = {"True": 0, "False": 1, "Unknown": 2}
METRIC_DESC = ("macro_f1 (step verification, 3-class True/False/Unknown, flattened per "
               "dataset+model, macro average)")


def norm(x: str):
    """Map a label string to its class id, tolerating casing; None if unrecognized."""
    return LABEL.get(str(x).strip().capitalize())


def macro_f1(gt: list, pred: list) -> float:
    """Macro-averaged F1 over the classes present in gt ∪ pred — identical to
    sklearn.metrics.f1_score(..., average='macro') with zero_division=0."""
    scores = []
    for c in set(gt) | set(pred):
        tp = sum(1 for t, p in zip(gt, pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(gt, pred) if p == c and t != c)
        fn = sum(1 for t, p in zip(gt, pred) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def score(pred_by_idx: dict, gold_by_idx: dict):
    """Flatten aligned steps over all instances → (macro_f1, n_steps, n_unaligned, n_badlabel)."""
    gt, pred, unaligned, bad = [], [], 0, 0
    for idx, gold in gold_by_idx.items():
        p = pred_by_idx.get(idx)
        if p is None or len(p) != len(gold):
            unaligned += 1
            continue
        gp, gg = [norm(v) for v in p], [norm(v) for v in gold]
        if None in gp or None in gg:
            bad += 1
            continue
        pred.extend(gp)
        gt.extend(gg)
    if not gt:
        return None, 0, unaligned, bad
    return macro_f1(gt, pred), len(gt), unaligned, bad


def steps_json(path: str, field: str) -> dict:
    return {r["idx"]: r[field] for r in json.load(open(path, encoding="utf-8"))}


# Group predictions from the two tagged files: (variant, dataset, model) -> {idx: step_labels}.
out_files = sorted(glob.glob("outputs/output_*.jsonl"))
if not out_files:
    sys.exit("ABORT: no outputs/output_*.jsonl (run main.py first)")
preds = defaultdict(dict)
for out_path in out_files:
    variant = os.path.basename(out_path)[len("output_"):-len(".jsonl")]
    for line in open(out_path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            preds[(variant, r["dataset"], r["model"])][r["idx"]] = r["step_correctness_label"]

per_run = defaultdict(list)      # variant -> [run dicts]
agg = defaultdict(list)          # (variant, dataset) -> [f1, ...]
for (variant, ds, model), pred_by_idx in sorted(preds.items()):
    labels_path = os.path.join("inputs", ds, f"{model}_labels.json")
    if not os.path.exists(labels_path):
        print(f"  skip {variant}/{ds}/{model}: no labels at {labels_path}", file=sys.stderr)
        continue
    f1, n, un, bad = score(pred_by_idx, steps_json(labels_path, "step_correctness_label"))
    per_run[variant].append({"dataset": ds, "model": model, "macro_f1": f1,
                             "n_steps": n, "unaligned_instances": un, "bad_label_instances": bad})
    if f1 is not None:
        agg[(variant, ds)].append(f1)
    f1s = "n/a" if f1 is None else f"{f1:.4f}"
    flag = f"  ⚠ unaligned={un}" if un else ""
    print(f"[{variant}] {ds}/{model:34} macro_f1={f1s}  (steps={n}){flag}")

# One results file per prompt variant: results/results_<variant>.json
os.makedirs("results", exist_ok=True)
print("\n=== mean macro-F1 per (variant, dataset) ===")
for variant in sorted(per_run):
    mean_per_dataset = {}
    for (vv, ds), f1s in sorted(agg.items()):
        if vv != variant:
            continue
        mean = sum(f1s) / len(f1s)
        mean_per_dataset[ds] = round(mean, 4)
        print(f"  [{variant}] {ds:16} {mean:.4f}  (over {len(f1s)} models)")
    out = os.path.join("results", f"results_{variant}.json")
    json.dump({"metric": METRIC_DESC, "prompt_variant": variant,
               "mean_per_dataset": mean_per_dataset, "per_run": per_run[variant]},
              open(out, "w"), indent=2)
    print(f"  saved {out}")
