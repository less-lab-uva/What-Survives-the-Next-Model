import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) not in (2, 3) or sys.argv[1].upper() not in ("A", "B"):
    print("Usage: python evaluator.py <A|B> [dataset]")
    print("Available datasets: py150, netbeans")
    sys.exit(1)

variant      = sys.argv[1].upper()
dataset_key  = sys.argv[2].lower() if len(sys.argv) == 3 else "py150"
suffix       = f"_{dataset_key}"
inputs_path  = os.path.join(BASE_DIR, "outputs", f"outputs_{variant}{suffix}.jsonl")
results_dir  = os.path.join(BASE_DIR, "results")
output_path  = os.path.join(results_dir, f"results_{variant}{suffix}.jsonl")
failed_path  = os.path.join(results_dir, f"failed_{variant}{suffix}.json")
os.makedirs(results_dir, exist_ok=True)


def is_correct(predicted: str, ground_truth: str) -> bool:
    return predicted == ground_truth


def normalise_by_position(predictions: list[dict], num_expected: int) -> list[dict]:
    by_pos = {}
    for pred in predictions:
        try:
            pos = int(pred["position"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= pos < num_expected and pos not in by_pos:
            by_pos[pos] = {"position": pos, "value": str(pred.get("value", ""))}
    return [by_pos[pos] for pos in sorted(by_pos)]


records = []
with open(inputs_path) as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

print(f"Loaded {len(records)} instances from {inputs_path}.")
print(f"Dataset: {dataset_key}")

correct          = 0
total_pred       = 0
total_gt         = 0
failed_cases     = []
per_instance     = []

for record in records:
    ground_truth = record["ground_truth"]
    predictions  = normalise_by_position(record["arguments"], len(ground_truth))

    total_gt   += len(ground_truth)
    total_pred += len(predictions)

    inst_correct = 0
    for pred in predictions:
        pos = pred["position"]
        val = pred["value"]

        if pos < len(ground_truth):
            gt_val = ground_truth[pos]
            if is_correct(str(val).strip(), str(gt_val).strip()):
                correct += 1
                inst_correct += 1
            else:
                failed_cases.append({
                    "filepath":     record["filepath"],
                    "call_line":    record["call_line"],
                    "position":     pos,
                    "ground_truth": gt_val,
                    "predicted":    val,
                })
        else:
            failed_cases.append({
                "filepath":     record["filepath"],
                "call_line":    record["call_line"],
                "position":     pos,
                "ground_truth": None,
                "predicted":    val,
            })

    predicted_positions = {pred["position"] for pred in predictions}
    for pos, gt_val in enumerate(ground_truth):
        if pos not in predicted_positions:
            failed_cases.append({
                "filepath":     record["filepath"],
                "call_line":    record["call_line"],
                "position":     pos,
                "ground_truth": gt_val,
                "predicted":    None,
            })

    per_instance.append({
        "filepath":     record["filepath"],
        "call_line":    record["call_line"],
        "ground_truth": ground_truth,
        "arguments":    predictions,
        "correct":      inst_correct,
        "total":        len(predictions),
    })

precision = correct / total_pred        if total_pred        else 0.0
recall    = correct / total_gt          if total_gt          else 0.0

print(f"\n{'='*60}")
print(f"Total instances evaluated : {len(records)}")
print(f"Total ground truth args   : {total_gt}")
print(f"Total predictions made    : {total_pred}")
print(f"Correct predictions       : {correct}")
print(f"Precision : {precision:.4f}")
print(f"Recall    : {recall:.4f}")
print(f"{'='*60}")

with open(output_path, "w") as f:
    aggregate = {
        "aggregate": {
            "precision": round(precision, 4),
            "recall":    round(recall, 4),
            "correct":   correct,
            "total_pred": total_pred,
            "total_gt":  total_gt,
            "instances": len(records),
        }
    }
    f.write(json.dumps(aggregate) + "\n")
    for r in per_instance:
        f.write(json.dumps(r) + "\n")

with open(failed_path, "w") as f:
    json.dump(failed_cases, f, indent=2)

print(f"\nResults saved to  : {output_path}")
print(f"Failed cases saved: {failed_path}")
