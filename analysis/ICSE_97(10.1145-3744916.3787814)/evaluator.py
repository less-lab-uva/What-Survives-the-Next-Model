"""
FoundRoot evaluator.
Reads outputs JSONL from main.py and computes Top-1, Top-3, MRR per dataset and overall.

Usage:
  python evaluator.py [--prompt A|B|both] [--n N]

Input:  outputs/outputs_{P}.jsonl
Output: results/results_{P}.jsonl
"""

import argparse
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "dataset"


def _load_ground_truth(datasets: list) -> dict:
    """Load {(dataset, case_idx): {"ground_truth": [...], "all_components": [...]}}
    straight from dataset/{ds}/test.jsonl, so scoring is always against the
    canonical source rather than whatever main.py happened to embed in the
    output record (which can carry a non-deterministic component order — see
    the set() round-trip in main.py's process_example)."""
    gt = {}
    for ds in datasets:
        path = DATA_DIR / ds / "test.jsonl"
        if not path.exists():
            print(f"[WARN] Dataset {ds} not found at {path}; cannot verify ground truth")
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                sol = json.loads(case["solution"])
                gt[(ds, case["case_idx"])] = {
                    "ground_truth":   sol["root_cause"],
                    "all_components": list(dict.fromkeys(item["component"] for item in sol["rank_list"])),
                }
    return gt


def _normalize(name: str) -> str:
    return re.sub(r'[^一-龥a-zA-Z0-9]', '', name).lower()


def _resolve_component(pred_comp: str, all_components: list) -> str:
    """Resolve a predicted component name to its canonical entry in all_components.

    Tries an exact normalized match first — that's unambiguous and should cover
    the common case. Only falls back to substring containment when no exact
    match exists, and among substring matches picks the candidate whose
    normalized name is closest in length to the prediction (the "tightest" fit).
    This avoids a short/generic prediction arbitrarily latching onto whichever
    differently-sized candidate happens to come first in all_components.
    """
    norm_pred = _normalize(pred_comp)
    if not norm_pred:
        return "Unknown"

    for c in all_components:
        if _normalize(c) == norm_pred:
            return c

    candidates = [c for c in all_components if norm_pred in _normalize(c)]
    if candidates:
        return min(candidates, key=lambda c: len(_normalize(c)))

    return "Unknown"


def _build_group_rank(predicted_rank_list: list, all_components: list) -> list:
    group_rank = []
    for item in predicted_rank_list:
        pred_comp = item.get("component", "")
        canonical = _resolve_component(pred_comp, all_components)
        if canonical not in group_rank:
            group_rank.append(canonical)
    return group_rank


def evaluate_case(record: dict, gt_lookup: dict) -> dict:
    truth = gt_lookup.get((record["dataset"], record["case_idx"]))
    if truth is None:
        return {"top1": 0.0, "top3": 0.0, "mrr": 0.0, "parsed": False}

    gt_root_causes = set(truth["ground_truth"])
    all_components = truth["all_components"]
    predicted      = record.get("predicted")

    if predicted is None or "rank_list" not in predicted:
        return {"top1": 0.0, "top3": 0.0, "mrr": 0.0, "parsed": False}

    group_rank = _build_group_rank(predicted["rank_list"], all_components)

    top1 = 1.0 if group_rank and group_rank[0] in gt_root_causes else 0.0

    mrr = 0.0
    for i, comp in enumerate(group_rank):
        if comp in gt_root_causes:
            mrr = 1.0 / (i + 1)
            break

    top3 = float(mrr > 0.32)

    return {"top1": top1, "top3": top3, "mrr": mrr, "parsed": True}


def evaluate_prompt(prompt_label: str, n):
    outputs_path = Path(__file__).parent / "outputs" / f"outputs_{prompt_label}.jsonl"
    if not outputs_path.exists():
        print(f"ERROR: outputs file not found: {outputs_path}")
        return

    records = []
    with open(outputs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    datasets  = list(dict.fromkeys(r["dataset"] for r in records))
    gt_lookup = _load_ground_truth(datasets)
    results = []
    for rec in records:
        eval_result = evaluate_case(rec, gt_lookup)
        results.append({**rec, "eval": eval_result})

    print(f"\n{'='*60}")
    print(f"RESULTS — {len(results)} cases  |  Prompt={prompt_label}")
    print(f"{'='*60}")
    print(f"{'Dataset':<10} {'Cases':>6} {'Top-1':>8} {'Top-3':>8} {'MRR':>8}")
    print(f"{'-'*44}")

    agg = {}
    for ds in datasets:
        ds_recs = [r for r in results if r["dataset"] == ds]
        if not ds_recs:
            continue
        t1  = sum(r["eval"]["top1"] for r in ds_recs) / len(ds_recs)
        t3  = sum(r["eval"]["top3"] for r in ds_recs) / len(ds_recs)
        mrr = sum(r["eval"]["mrr"]  for r in ds_recs) / len(ds_recs)
        agg[ds] = {"top1": t1, "top3": t3, "mrr": mrr, "n": len(ds_recs)}
        print(f"{ds:<10} {len(ds_recs):>6} {t1:>8.3f} {t3:>8.3f} {mrr:>8.3f}")

    t1_all  = sum(r["eval"]["top1"] for r in results) / len(results)
    t3_all  = sum(r["eval"]["top3"] for r in results) / len(results)
    mrr_all = sum(r["eval"]["mrr"]  for r in results) / len(results)
    print(f"{'-'*44}")
    print(f"{'Overall':<10} {len(results):>6} {t1_all:>8.3f} {t3_all:>8.3f} {mrr_all:>8.3f}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {
        "top1":  round(t1_all,  4),
        "top3":  round(t3_all,  4),
        "mrr":   round(mrr_all, 4),
        "total": len(results),
        "total_llm_time": round(sum(r.get("llm_response_time", 0.0) for r in results), 3),
        "by_dataset": {
            ds: {"top1": round(v["top1"], 4), "top3": round(v["top3"], 4), "mrr": round(v["mrr"], 4), "n": v["n"]}
            for ds, v in agg.items()
        },
    }
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nResults saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n", type=lambda v: "all" if str(v).lower() == "all" else int(v), default=5)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
