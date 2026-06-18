"""Fetch the IntentFix artifact and build dataset/intentfix_pairs.jsonl.

Downloads the pinned files.tar.gz + metadata.json from the upstream repo, extracts the
before/after file pairs, and writes one JSON record per pair. To match the paper's baseline
input ("the vulnerable code snippet and a high-level description of the vulnerability",
section 4.3) and its oracle input ("the CWE description", section 4.4.1), each record carries
a `vulnerability_description` fetched from the official MITRE CWE REST API.

The artifact has NO free-text description field (only CWE/CVE identifiers; verified across
collect_dataset.py, metadata.json, and the experiment pipeline). The dataset spans only the
CWE-840 (Business Logic Errors) family, so the description is the standard MITRE text for each
pair's CWE -- looked up authoritatively from the CWE API, not transcribed by hand.

Each output record:
  pair_id, cwe, cve, vulnerability_description, buggy_code, human_patch

Run from the analysis directory:  python3 utils/produce_dataset.py
"""
import json
import tarfile
import tempfile
import urllib.request
from pathlib import Path

COMMIT       = "3d6a694d94882aa6703010171964a8e79fe75565"
RAW_BASE     = f"https://github.com/mrhjs225/intentfix-icse2026/raw/{COMMIT}/data"
TARBALL_URL  = f"{RAW_BASE}/files.tar.gz"
METADATA_URL = f"{RAW_BASE}/metadata.json"

# Official MITRE CWE REST API (https://github.com/CWE-CAPEC/REST-API-wg).
CWE_API = "https://cwe-api.mitre.org/api/v1/cwe"

OUT_PATH = Path("dataset/intentfix_pairs.jsonl")


def fetch(url, dest):
    print(f"  downloading {url} ...")
    urllib.request.urlretrieve(url, dest)


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def fetch_cwe_descriptions(cwe_ids):
    """Look up 'Name: Description' for each CWE id from the MITRE CWE API.

    cwe_ids: iterable like {'CWE-639', 'CWE-770'}. Returns {cwe_id: description}.
    Tries the weakness endpoint (all the dataset's CWEs are weaknesses); falls back to the
    category endpoint for any id the weakness endpoint doesn't return (e.g. CWE-840).
    """
    nums = sorted({c.split("-", 1)[1] for c in cwe_ids
                   if c.startswith("CWE-") and c.split("-", 1)[1].isdigit()}, key=int)
    if not nums:
        return {}

    def describe(entry):
        name = (entry.get("Name") or "").strip()
        desc = " ".join((entry.get("Description") or "").split())
        return f"{name}: {desc}" if desc else name

    out = {}
    print(f"  fetching CWE descriptions for {len(nums)} ids from {CWE_API} ...")
    data = get_json(f"{CWE_API}/weakness/{','.join(nums)}")
    for w in data.get("Weaknesses", []):
        out[f"CWE-{w['ID']}"] = describe(w)

    missing = [n for n in nums if f"CWE-{n}" not in out]
    for n in missing:  # some ids are Categories, not Weaknesses
        try:
            cat = get_json(f"{CWE_API}/category/{n}")
            for c in cat.get("Categories", []):
                name = (c.get("Name") or "").strip()
                summary = " ".join((c.get("Summary") or "").split())
                out[f"CWE-{n}"] = f"{name}: {summary}" if summary else name
        except Exception as e:
            print(f"  WARNING: could not fetch CWE-{n} ({e}); using bare id")
    return out


def build_pairs(metadata, changed_files_dir, desc_map):
    """Replicate intentfix.utils.load_dataset (the verified 1107-pair loader)."""
    pairs = metadata["pairs"] if isinstance(metadata, dict) and "pairs" in metadata else metadata
    records, skipped = [], 0
    for item in pairs:
        pair_id = item.get("pair_id")
        if not pair_id:
            continue
        if pair_id.startswith("ChangedFilePair:"):
            idx = item.get("pair_index")
            if not idx:
                continue
            pair_dir_name = f"pair_{idx:04d}"
        else:
            pair_dir_name = pair_id
        pair_path = Path(changed_files_dir) / pair_dir_name
        before_path, after_path = pair_path / "before", pair_path / "after"
        if not (before_path.is_dir() and after_path.is_dir()):
            skipped += 1
            continue
        before_files, after_files = list(before_path.glob("*")), list(after_path.glob("*"))
        if not before_files or not after_files:
            skipped += 1
            continue
        buggy_file = max(before_files, key=lambda p: p.stat().st_size if p.is_file() else 0)
        human_file = max(after_files, key=lambda p: p.stat().st_size if p.is_file() else 0)
        if not (buggy_file.is_file() and human_file.is_file()):
            skipped += 1
            continue
        try:
            buggy_code = buggy_file.read_text(encoding="utf-8")
            human_patch = human_file.read_text(encoding="utf-8")
        except Exception:
            skipped += 1
            continue
        if not buggy_code or not human_patch:
            skipped += 1
            continue
        cwe = item.get("cwe", "Unknown")
        records.append({
            "pair_id": pair_dir_name,
            "cwe": cwe,
            "cve": item.get("cve", "Unknown"),
            "vulnerability_description": desc_map.get(cwe, cwe),
            "buggy_code": buggy_code,
            "human_patch": human_patch,
        })
    return records, skipped


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        meta_path, tar_path = tmp / "metadata.json", tmp / "files.tar.gz"
        print("Fetching artifact...")
        fetch(METADATA_URL, meta_path)
        fetch(TARBALL_URL, tar_path)
        print("Extracting tarball...")
        with tarfile.open(tar_path) as t:
            t.extractall(tmp)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

        pairs = metadata["pairs"] if isinstance(metadata, dict) and "pairs" in metadata else metadata
        cwe_ids = {item.get("cwe") for item in pairs if item.get("cwe")}
        desc_map = fetch_cwe_descriptions(cwe_ids)
        for cwe in sorted(cwe_ids):
            print(f"    {cwe}: {desc_map.get(cwe, '(missing)')[:70]}")

        records, skipped = build_pairs(metadata, tmp / "changed_files", desc_map)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} pairs ({skipped} skipped as incomplete) -> {OUT_PATH}")
    from collections import Counter
    print("CWE distribution:", dict(Counter(r["cwe"] for r in records).most_common()))


if __name__ == "__main__":
    main()
