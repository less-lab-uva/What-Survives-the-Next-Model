import json
from pathlib import Path

from datasets import load_from_disk


BASE_DIR = Path(__file__).resolve().parent
PATCHDIFF_DIR = BASE_DIR / "PatchDiff"
DATA_DIR = PATCHDIFF_DIR / "data"
SWEBENCH_PATH = DATA_DIR / "dataset" / "swebench_verified"
TOOL_RESULTS_DIR = DATA_DIR / "tool_results"
OUTPUT_PATH = BASE_DIR / "combined_dataset.json"

# Load SWE-bench Verified from LOCAL arrow files
print("Loading SWE-bench Verified locally...")
swebench = load_from_disk(str(SWEBENCH_PATH))
swebench_dict = {x["instance_id"]: x for x in swebench}
print(f"Loaded {len(swebench_dict)} instances")


print("\nAvailable tool folders:")
for path in sorted(TOOL_RESULTS_DIR.iterdir()):
    if path.is_dir():
        print(f"  {path.name}")

TOOLS = {
    "openhands": TOOL_RESULTS_DIR / "20241029_OpenHands-CodeAct-2.1-sonnet-20241022_verified" / "all_preds.jsonl",
    "codestory": TOOL_RESULTS_DIR / "20241221_codestory_midwit_claude-3-5-sonnet_swe-search" / "all_preds.jsonl",
    "learnbyinteract": TOOL_RESULTS_DIR / "20250110_learn_by_interact_claude3.5" / "all_preds.jsonl",
}

all_instances = []

for tool_name, path in TOOLS.items():
    print(f"\nProcessing {tool_name}...")
    count = 0
    skipped = 0

    if not path.exists():
        raise FileNotFoundError(f"Tool predictions file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pred = json.loads(line)
            instance_id = pred["instance_id"]

            # Skip if no patch was generated
            if not pred.get("model_patch") or pred["model_patch"].strip() == "":
                skipped += 1
                continue

            # Skip if not in SWE-bench Verified
            if instance_id not in swebench_dict:
                skipped += 1
                continue

            swe_instance = swebench_dict[instance_id]

            instance = {
                "instance_id": instance_id,
                "tool": tool_name,
                "problem_statement": swe_instance["problem_statement"],
                "plausible_patch": pred["model_patch"],
                "oracle_patch": swe_instance["patch"],
                "FAIL_TO_PASS": swe_instance["FAIL_TO_PASS"],
                "PASS_TO_PASS": swe_instance["PASS_TO_PASS"],
                "repo": swe_instance["repo"],
                "base_commit": swe_instance["base_commit"],
            }
            all_instances.append(instance)
            count += 1

    print(f"  Collected {count} instances, skipped {skipped}")

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    json.dump(all_instances, f, indent=2)

print(f"\nTotal instances: {len(all_instances)}")
print(f"Saved to {OUTPUT_PATH}")

# Show one example
if all_instances:
    print("\n=== SAMPLE INSTANCE ===")
    sample = all_instances[0]
    for k, v in sample.items():
        print(f"\n--- {k} ---")
        print(str(v)[:200])
