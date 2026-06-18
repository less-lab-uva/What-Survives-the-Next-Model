import argparse
import json
from pathlib import Path


def compute_metrics(records: list) -> dict:
    tp = sum(1 for r in records if r["pred_label"] == 1 and r["true_label"] == 1)
    fp = sum(1 for r in records if r["pred_label"] == 1 and r["true_label"] == 0)
    fn = sum(1 for r in records if r["pred_label"] == 0 and r["true_label"] == 1)
    tn = sum(1 for r in records if r["pred_label"] == 0 and r["true_label"] == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "f1":        round(f1,        4),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


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

    if n != "all":
        records = records[:n]

    evaluated = [r for r in records if not r.get("skipped") and r["pred_label"] != -1]
    metrics = compute_metrics(evaluated)

    print(f"\n{'='*50}")
    print(f"SUMMARY — Prompt {prompt_label} — {len(evaluated)} evaluated ({len(records)-len(evaluated)} skipped)")
    print(f"  Precision : {metrics['precision']:.4f}")
    print(f"  Recall    : {metrics['recall']:.4f}")
    print(f"  F1-score  : {metrics['f1']:.4f}")
    print(f"  TP={metrics['tp']} FP={metrics['fp']} FN={metrics['fn']} TN={metrics['tn']}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"results_{prompt_label}.jsonl"
    aggregate = {**metrics, "total": len(records), "total_llm_time": round(sum(r.get("llm_response_time", 0.0) for r in records), 3)}
    with open(out_path, "w") as f:
        f.write(json.dumps({"aggregate": aggregate}) + "\n")
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Results saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", choices=["A", "B", "both"], default="both")
    parser.add_argument("--n", type=lambda v: "all" if str(v).lower() == "all" else int(v), default="all")
    args = parser.parse_args()

    prompt_labels = ["A", "B"] if args.prompt == "both" else [args.prompt]
    for pl in prompt_labels:
        evaluate_prompt(pl, args.n)


if __name__ == "__main__":
    main()
