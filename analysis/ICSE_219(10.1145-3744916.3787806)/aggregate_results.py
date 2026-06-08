import json
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"

PROMPT_TYPES = ["A", "B"]
DATASET_NAMES = ["bp", "fsd", "lmc", "pure", "rac", "us"]
METRICS = ["r_f1", "n_f1", "pass_rate"]


def load_dataset_aggregate(prompt_type: str, dataset_name: str) -> Dict[str, Any]:
    path = RESULTS_DIR / f"results_{prompt_type}_{dataset_name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Missing result file: {path}")

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            obj = json.loads(line)
            if "aggregate" not in obj:
                raise ValueError(f"First non-empty row has no aggregate field: {path}")

            aggregate = obj["aggregate"]
            missing_metrics = [metric for metric in METRICS if metric not in aggregate]
            if missing_metrics:
                raise ValueError(
                    f"Missing metrics in {path}: {', '.join(missing_metrics)}"
                )

            return aggregate

    raise ValueError(f"No JSON rows found in result file: {path}")


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_prompt(prompt_type: str) -> Dict[str, Any]:
    per_dataset: Dict[str, Dict[str, float]] = {}

    for dataset_name in DATASET_NAMES:
        aggregate = load_dataset_aggregate(prompt_type, dataset_name)
        per_dataset[dataset_name] = {
            "r_f1": float(aggregate["r_f1"]),
            "n_f1": float(aggregate["n_f1"]),
            "pass_rate": float(aggregate["pass_rate"]),
        }

    averaged = {
        metric: round(mean([scores[metric] for scores in per_dataset.values()]), 4)
        for metric in METRICS
    }

    return {
        "prompt_type": prompt_type,
        "datasets": DATASET_NAMES,
        "averaging": "macro_average_over_datasets",
        "aggregate": {
            "R-F1": averaged["r_f1"],
            "N-F1": averaged["n_f1"],
            "pass_rate": averaged["pass_rate"],
        },
        "per_dataset": {
            dataset_name: {
                "R-F1": scores["r_f1"],
                "N-F1": scores["n_f1"],
                "pass_rate": scores["pass_rate"],
            }
            for dataset_name, scores in per_dataset.items()
        },
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for prompt_type in PROMPT_TYPES:
        result = aggregate_prompt(prompt_type)
        output_path = RESULTS_DIR / f"aggregated_results_{prompt_type}.json"

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(result, file, indent=2)
            file.write("\n")

        aggregate = result["aggregate"]
        print(
            f"Prompt {prompt_type}: "
            f"R-F1={aggregate['R-F1']:.4f}, "
            f"N-F1={aggregate['N-F1']:.4f}, "
            f"pass_rate={aggregate['pass_rate']:.4f}"
        )
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
