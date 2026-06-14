import argparse
import json
import math
from pathlib import Path


def compute_metrics(records):
    tp = sum(1 for r in records if r["target"] == 1 and r["predicted"] == 1)
    tn = sum(1 for r in records if r["target"] == 0 and r["predicted"] == 0)
    fp = sum(1 for r in records if r["target"] == 0 and r["predicted"] == 1)
    fn = sum(1 for r in records if r["target"] == 1 and r["predicted"] == 0)
    n = len(records)
    accuracy  = (tp + tn) / n if n else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall    = tp / (tp + fn) if (tp + fn) else 0
    fpr       = fp / (fp + tn) if (fp + tn) else 0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    denom     = math.sqrt((tp+fp)*(tp+fn)*(tn+fp)*(tn+fn))
    mcc       = ((tp*tn)-(fp*fn)) / denom if denom else 0

    pairs = {}
    for r in records:
        cid = r.get("commit_id") or r["idx"]
        pairs.setdefault(cid, []).append(r)

    pc = pv = pb = pr = pair_count = 0
    unpaired = 0
    for cid, group in pairs.items():
        group = sorted(group, key=lambda r: r.get("order", 0))
        for i in range(0, len(group) - 1, 2):
            r1, r2 = group[i], group[i+1]
            pair_count += 1
            if r1["predicted"] == r1["target"] and r2["predicted"] == r2["target"]:
                pc += 1
            elif r1["predicted"] == 1 and r2["predicted"] == 1:
                pv += 1
            elif r1["predicted"] == 0 and r2["predicted"] == 0:
                pb += 1
            else:
                pr += 1
        if len(group) % 2:
            unpaired += 1

    if unpaired:
        print(f"  WARNING: {unpaired} commit-id group(s) had an odd number of records; "
              f"the last record of each was excluded from pair-level metrics")

    return {
        "accuracy":  round(accuracy,  4),
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "f1":        round(f1,        4),
        "mcc":       round(mcc,       4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "pair_count": pair_count,
        "PC": pc,
        "PV": pv,
        "PB": pb,
        "PR": pr,
        "Error": pair_count - pc,
        "P": round(precision, 4),
        "R": round(recall, 4),
        "FPR": round(fpr, 4),
    }


def evaluate_prompt(prompt_label: str, n: int):
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

    metrics = compute_metrics(records)

    print(f"\n{'='*50}")
    print(f"SUMMARY — Prompt {prompt_label} — {len(records)} examples")
    print(f"  Accuracy  : {metrics['accuracy']:.1%}")
    print(f"  Precision : {metrics['precision']:.3f}")
    print(f"  Recall    : {metrics['recall']:.3f}")
    print(f"  FPR       : {metrics['FPR']:.3f}")
    print(f"  F1        : {metrics['f1']:.3f}")
    print(f"  MCC       : {metrics['mcc']:.3f}")
    print(f"  TP={metrics['tp']} TN={metrics['tn']} FP={metrics['fp']} FN={metrics['fn']}")
    if metrics["pair_count"]:
        print(f"  Pairs={metrics['pair_count']} | PC={metrics['PC']} PV={metrics['PV']} PB={metrics['PB']} PR={metrics['PR']} Error={metrics['Error']}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {**metrics, "total": len(records), "total_llm_time": round(sum(r.get("llm_response_time", 0.0) for r in records), 3)}
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nResults saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n",      type=int, default=5)
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
