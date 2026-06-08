import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
RESULTS_DIR = BASE_DIR / "results"

NUMERIC_FIELDS = [
    "copyright",
    "copyleft",
    "modification",
    "patent",
    "trademark",
    "interaction",
    "retain_attr",
    "acceptance",
    "enhance_attr",
    "patent_term",
]

OPEN_FIELDS = [
    "Usage Limitation",
    "exception",
    "compatible_version",
    "secondary_license",
    "gpl_combine",
]

SKIP_FIELDS = {"vio_term"}


def usage() -> None:
    print("Usage: python evaluator.py <A|B>")


if len(sys.argv) != 2 or sys.argv[1].upper() not in ("A", "B"):
    usage()
    sys.exit(1)

variant = sys.argv[1].upper()
inputs_path = OUTPUTS_DIR / f"outputs_{variant}.jsonl"
output_path = RESULTS_DIR / f"results_{variant}.jsonl"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_open_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(key).strip().lower() for key, enabled in value.items() if enabled]
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        if value.strip() in ("", "0", "null", "None", "[]"):
            return []
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return []


def normalize_label(value: str) -> str:
    label = value.strip().lower()
    label = label.replace("_", "-")
    label = re.sub(r"\s+", "-", label)
    label = re.sub(r"-+", "-", label)
    return label.strip("-")


def numeric_score(gt_value: Any, pred_value: Any) -> int:
    try:
        return int(int(gt_value) == int(pred_value))
    except Exception:
        return 0


def open_recall(gt_value: Any, pred_value: Any) -> float:
    gt_values = {normalize_label(value) for value in normalize_open_values(gt_value)}
    pred_values = {normalize_label(value) for value in normalize_open_values(pred_value)}

    if not gt_values:
        return 1.0
    if not pred_values:
        return 0.0

    return len(gt_values & pred_values) / len(gt_values)


def evaluate_one(gt_term: Dict[str, Any], pred_term: Dict[str, Any]) -> Dict[str, float]:
    scores = {}
    for field, gt_value in gt_term.items():
        if field in SKIP_FIELDS:
            continue

        pred_value = pred_term.get(field)
        if field in NUMERIC_FIELDS or isinstance(gt_value, int):
            scores[field] = float(numeric_score(gt_value, pred_value))
        else:
            scores[field] = open_recall(gt_value, pred_value)

    return scores


def field_summary(per_instance_scores: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    totals: Dict[str, Tuple[float, int]] = defaultdict(lambda: [0.0, 0])
    for scores in per_instance_scores:
        for field, score in scores.items():
            totals[field][0] += score
            totals[field][1] += 1

    summary = {}
    for field, (score_sum, count) in sorted(totals.items()):
        summary[field] = {
            "score": round(score_sum / count, 4) if count else 0.0,
            "score_sum": round(score_sum, 4),
            "count": count,
        }
    return summary


def micro_average(summary: Dict[str, Dict[str, float]], fields: List[str] | None = None) -> float | None:
    selected = fields if fields is not None else list(summary.keys())
    score_sum = 0.0
    count_sum = 0

    for field in selected:
        if field not in summary:
            continue
        score_sum += float(summary[field]["score_sum"])
        count_sum += int(summary[field]["count"])

    if count_sum == 0:
        return None
    return round(score_sum / count_sum, 4)


def main() -> None:
    if not inputs_path.exists():
        raise FileNotFoundError(f"Output file not found: {inputs_path}")

    rows = load_jsonl(inputs_path)
    print(f"Loaded {len(rows)} predictions from {inputs_path}.")

    per_instance = []
    per_instance_scores = []

    for row in rows:
        gt_term = row.get("gt_term", {})
        pred_term = row.get("pred_term", {})
        scores = evaluate_one(gt_term, pred_term)
        per_instance_scores.append(scores)

        per_instance.append({
            "project_name": row.get("project_name", ""),
            "license_name": row.get("license_name", ""),
            "scores": {field: round(score, 4) for field, score in sorted(scores.items())},
            "mean_score": round(sum(scores.values()) / len(scores), 4) if scores else 0.0,
            "pred_term": pred_term,
            "gt_term": gt_term,
        })

    summary = field_summary(per_instance_scores)
    numeric_accuracy = micro_average(summary, NUMERIC_FIELDS)
    open_recall_avg = micro_average(summary, OPEN_FIELDS)
    overall_mean = micro_average(summary)

    aggregate = {
        "aggregate": {
            "total": len(rows),
            "numeric_accuracy": numeric_accuracy,
            "open_field_recall": open_recall_avg,
            "overall_mean": overall_mean,
            "field_scores": summary,
        }
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        file.write(json.dumps(aggregate, ensure_ascii=False) + "\n")
        for item in per_instance:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 55}")
    print(f"Total evaluated          : {len(rows)}")
    print(f"Numeric-field accuracy   : {100 * numeric_accuracy:.2f}%" if numeric_accuracy is not None else "Numeric-field accuracy   : N/A")
    print(f"Open-field recall        : {100 * open_recall_avg:.2f}%" if open_recall_avg is not None else "Open-field recall        : N/A")
    print(f"Overall mean             : {100 * overall_mean:.2f}%" if overall_mean is not None else "Overall mean             : N/A")
    print(f"{'=' * 55}")
    print("\nPer-field scores:")
    for field, info in summary.items():
        metric_name = "recall" if field in OPEN_FIELDS else "accuracy"
        print(f"  {field:20s} {metric_name:8s}: {100 * info['score']:.2f}% ({info['score_sum']}/{info['count']})")
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
