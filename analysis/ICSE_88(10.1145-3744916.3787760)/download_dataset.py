#!/usr/bin/env python3
"""
Download the LFTBench dataset from Zenodo and extract it to dataset/lftbench/.

Usage:
  python download_dataset.py <zenodo_url>

Accepted URL forms:
  https://zenodo.org/records/<id>
  https://zenodo.org/record/<id>
  https://doi.org/10.5281/zenodo.<id>
  https://zenodo.org/records/<id>/files/<filename>.zip   (direct file link)
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Tuple

DATASET_DIR = Path(__file__).parent / "dataset"


def resolve_doi(doi_url: str) -> str:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(doi_url)
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location")
        if location:
            return location
    raise RuntimeError(f"Could not resolve DOI: {doi_url}")


def extract_record_id(url: str) -> str:
    m = re.search(r'zenodo\.org/records?/(\d+)', url)
    if m:
        return m.group(1)
    raise ValueError(f"Could not extract Zenodo record ID from: {url}")


def get_zip_url_from_api(record_id: str) -> Tuple[str, str]:
    """Return (download_url, filename) for the first zip file in the record."""
    api_url = f"https://zenodo.org/api/records/{record_id}"
    with urllib.request.urlopen(api_url) as resp:
        data = json.loads(resp.read())
    files = data.get("files", [])
    for f in files:
        if f.get("key", "").endswith(".zip"):
            return f["links"]["self"], f["key"]
    if files:
        f = files[0]
        return f["links"]["self"], f["key"]
    raise RuntimeError(f"No files found in Zenodo record {record_id}")


def download_with_progress(url: str, dest: Path) -> None:
    print(f"Downloading: {url}")

    def reporthook(count, block_size, total_size):
        if total_size > 0:
            pct = min(100.0, count * block_size * 100.0 / total_size)
            done_mb = count * block_size / 1e6
            total_mb = total_size / 1e6
            print(f"\r  {pct:5.1f}%  {done_mb:.1f}/{total_mb:.1f} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    print()


def extract_zip(archive: Path, target_dir: Path) -> None:
    """
    Extract archive into target_dir.
    If the zip's top-level entries are all under a single 'lftbench/' prefix,
    extract directly so the result is target_dir/lftbench/.
    Otherwise wrap them inside target_dir/lftbench/.
    """
    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
        # Determine whether the archive already has lftbench/ at the root
        top_level = {n.split("/")[0] for n in names if n.strip("/")}
        has_lftbench_root = top_level == {"lftbench"} or all(
            n.startswith("lftbench/") for n in names if not n.endswith("/") or n != "lftbench/"
        )

        if has_lftbench_root:
            print(f"Extracting into {target_dir} ...")
            zf.extractall(target_dir)
        else:
            # Flat archive — wrap in lftbench/
            dest = target_dir / "lftbench"
            dest.mkdir(parents=True, exist_ok=True)
            print(f"Extracting into {dest} ...")
            zf.extractall(dest)


def main():
    parser = argparse.ArgumentParser(
        description="Download the LFTBench dataset from Zenodo."
    )
    parser.add_argument("url", help="Zenodo record URL, DOI URL, or direct file link")
    args = parser.parse_args()

    url = args.url.strip()

    if "doi.org" in url:
        print("Resolving DOI ...")
        url = resolve_doi(url)
        print(f"  -> {url}")

    # Determine the direct download URL and filename
    if re.search(r'/files/[^/]+(\.(zip|tar\.gz|tgz))?$', url):
        download_url = url
        filename = url.rstrip("/").split("/")[-1]
    else:
        record_id = extract_record_id(url)
        print(f"Fetching file list for record {record_id} via Zenodo API ...")
        download_url, filename = get_zip_url_from_api(record_id)

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATASET_DIR / filename

    if not archive.exists():
        download_with_progress(download_url, archive)
        print(f"Saved to: {archive}")
    else:
        print(f"Archive already present: {archive}")

    lftbench_dir = DATASET_DIR / "lftbench"
    if lftbench_dir.exists():
        print(f"Dataset already extracted at: {lftbench_dir}")
    else:
        extract_zip(archive, DATASET_DIR)
        if not lftbench_dir.exists():
            print(
                f"\nWARNING: 'lftbench/' not found under {DATASET_DIR} after extraction.\n"
                "Check the archive structure and rename the extracted folder to 'lftbench'."
            )
            sys.exit(1)

    print(f"\nDataset ready at: {lftbench_dir}")


if __name__ == "__main__":
    main()
