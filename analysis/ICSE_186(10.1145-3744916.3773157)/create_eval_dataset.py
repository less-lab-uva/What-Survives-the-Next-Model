import json
import tarfile
from pathlib import Path
from typing import Dict, Optional


BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = BASE_DIR / "icse-lv"
ANNOTATION_FILE = SOURCE_DIR / "Annotation" / "eval_label_term.jsonl"
PKG_LICENSE_TAR = SOURCE_DIR / "pkg_license.tar.gz"

DATASET_DIR = BASE_DIR / "dataset"
OUTPUT_FILE = DATASET_DIR / "eval_instances_with_text.jsonl"


def load_annotations() -> list[dict]:
    rows = []
    with ANNOTATION_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_license_index(tar_path: Path) -> Dict[str, str]:
    """
    Build project_name -> first license-file path inside pkg_license/TOP.
    This matches the lookup logic used by main.py.
    """
    index = {}
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if len(parts) >= 4 and parts[0] == "pkg_license" and parts[1] == "TOP":
                project = parts[2].lower()
                if project not in index and member.isfile():
                    index[project] = member.name
    return index


def find_member(project_name: str, index: Dict[str, str]) -> Optional[str]:
    project = project_name.lower()
    return (
        index.get(project)
        or index.get(project.replace("-", "_"))
        or index.get(project.replace("_", "-"))
    )


def read_tar_member(tar: tarfile.TarFile, member_name: str) -> str:
    extracted = tar.extractfile(member_name)
    if extracted is None:
        raise RuntimeError(f"Could not read tar member: {member_name}")
    return extracted.read().decode("utf-8", errors="replace")


def main() -> None:
    if not ANNOTATION_FILE.exists():
        raise FileNotFoundError(f"Annotation file not found: {ANNOTATION_FILE}")
    if not PKG_LICENSE_TAR.exists():
        raise FileNotFoundError(f"License tar not found: {PKG_LICENSE_TAR}")

    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    annotations = load_annotations()
    print(f"Loaded {len(annotations)} annotations.")

    print("Indexing license files from tar. This can take a little while...")
    license_index = build_license_index(PKG_LICENSE_TAR)
    print(f"Indexed {len(license_index)} TOP projects.")

    written = 0
    missing = []

    with tarfile.open(PKG_LICENSE_TAR, "r:gz") as tar, OUTPUT_FILE.open("w", encoding="utf-8") as out:
        for row in annotations:
            project_name = row["project_name"]
            member_name = find_member(project_name, license_index)

            if member_name is None:
                missing.append(project_name)
                continue

            license_text = read_tar_member(tar, member_name)
            compact_row = {
                "project_name": project_name,
                "license_name": row["license_name"],
                "license_file": member_name,
                "license_text": license_text,
                "term": row["term"],
            }
            out.write(json.dumps(compact_row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} rows to {OUTPUT_FILE}.")
    if missing:
        print(f"Missing {len(missing)} projects:")
        for project_name in missing:
            print(f"  - {project_name}")


if __name__ == "__main__":
    main()
