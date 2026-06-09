"""
Download and extract the Testora dataset from the official GitHub release.

The dataset provides:
  data/ground_truth/        46 PRs with human-verified differentiating-test labels (RQ3)
  data/real-world_problems.csv   30 real-world unintended behavioral changes (RQ1)

Run from the with_sonnet/ directory (or the project root — path is resolved automatically):

    python3 download_dataset.py

After this script completes, run pull_prs.py (with a .github_token) to fetch the
PR content (diff, title, description, etc.) needed for inference:

    python3 pull_prs.py
"""

import tarfile
import urllib.request
from pathlib import Path

RELEASE_URL = "https://github.com/michaelpradel/Testora/releases/download/data_03_2025/data_03_2025.tar.gz"
ARCHIVE_NAME = "data_03_2025.tar.gz"

# Resolve project root (one level above with_sonnet/)
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
ARCHIVE_PATH = PROJECT_ROOT / ARCHIVE_NAME


def download():
    if ARCHIVE_PATH.exists():
        print(f"Archive already exists: {ARCHIVE_PATH}")
        return
    print(f"Downloading {RELEASE_URL} ...")
    urllib.request.urlretrieve(RELEASE_URL, ARCHIVE_PATH)
    print(f"Saved to {ARCHIVE_PATH}")


def extract():
    print(f"Extracting {ARCHIVE_PATH} into {PROJECT_ROOT} ...")
    with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
        tar.extractall(path=PROJECT_ROOT)
    print("Extraction complete.")


def verify():
    gt_dir  = PROJECT_ROOT / "data" / "ground_truth"
    csv_file = PROJECT_ROOT / "data" / "real-world_problems.csv"
    ok = True
    if gt_dir.exists():
        n = sum(1 for f in gt_dir.rglob("*.json") if f.name != "template.json")
        print(f"  ground_truth/: {n} PR JSON files")
    else:
        print(f"  [!] ground_truth/ not found at {gt_dir}")
        ok = False
    if csv_file.exists():
        rows = sum(1 for _ in csv_file.open()) - 1  # subtract header
        print(f"  real-world_problems.csv: {rows} rows")
    else:
        print(f"  [!] real-world_problems.csv not found at {csv_file}")
        ok = False
    return ok


def main():
    download()
    extract()
    print("\nVerifying extracted data ...")
    if verify():
        print("\nDataset ready. Next step:")
        print("  python3 pull_prs.py   # requires .github_token in this directory")
    else:
        print("\n[!] Verification failed — check the extraction above.")


if __name__ == "__main__":
    main()
