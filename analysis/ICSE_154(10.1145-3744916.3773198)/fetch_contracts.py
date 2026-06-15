"""
Fetch contract source files from pinned smart-contract-sanctuary GitHub repos.

Paper datasets:
  DB1 (RQ1 large-scale): 15,383 contracts across 4 chains
  DB2 (RQ2/RQ3 eval):      500 labeled contracts, 94% from Ethereum

Chain breakdown (per CSV files in Dataset/RQ1/DB1/):
  Ethereum : 4,514 contracts  ← covers 470/500 DB2 files (RQ2/RQ3)
  Polygon  : 5,304 contracts  ← largest chain by file count
  BSC      : 4,337 contracts
  Arbitrum : 1,228 contracts

Usage:
  python fetch_contracts.py                   # Ethereum only (recommended: covers RQ1+RQ2+RQ3)
  python fetch_contracts.py --chain Polygon   # single chain by name
  python fetch_contracts.py --all             # all 15,383 contracts (~450 MB)

Files are saved to Dataset/contracts/<chain>/<filename>.sol
The script is resumable: already-downloaded files are skipped.
"""

import argparse
import csv
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent

CHAINS = {
    "Ethereum": {
        "url": "https://github.com/tintinweb/smart-contract-sanctuary-ethereum.git",
        "commit": "015d0105102504dc8733a18c3543f87f1829a5e8",
        "csv": REPO_ROOT / "Dataset/RQ1/DB1/Ethereum.csv",
    },
    "Polygon": {
        "url": "https://github.com/tintinweb/smart-contract-sanctuary-polygon.git",
        "commit": "5e5bbae191cb03ae7ea58c80219e44edfb938a1d",
        "csv": REPO_ROOT / "Dataset/RQ1/DB1/Polygon.csv",
    },
    "BSC": {
        "url": "https://github.com/tintinweb/smart-contract-sanctuary-bsc.git",
        "commit": "74cf9ca766e80dc7fc2af7aee4ff6d896002b636",
        "csv": REPO_ROOT / "Dataset/RQ1/DB1/BSC.csv",
    },
    "Arbitrum": {
        "url": "https://github.com/tintinweb/smart-contract-sanctuary-arbitrum.git",
        "commit": "465b14914e025d2892dd0b484ef8bf8b1efbefe3",
        "csv": REPO_ROOT / "Dataset/RQ1/DB1/Arbitrum.csv",
    },
}

OUT_BASE = REPO_ROOT / "Dataset" / "contracts"


def run(cmd, cwd=None, check=True):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [STDERR] {result.stderr.strip()}")
        if check:
            raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def read_filenames(csv_path):
    names = set()
    with open(csv_path, newline="") as f:
        for row in csv.reader(f):
            fname = row[-1].strip()
            if fname:
                names.add(fname)
    return names


def fetch_chain(chain, cfg, work_dir):
    out_dir = OUT_BASE / chain
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = read_filenames(cfg["csv"])
    already = {p.name for p in out_dir.glob("*.sol")}
    needed = wanted - already

    if not needed:
        print(f"[{chain}] All {len(wanted)} files already present, skipping.")
        return

    print(f"[{chain}] Need {len(needed)} / {len(wanted)} files.")

    clone_dir = work_dir / chain
    clone_dir.mkdir(parents=True, exist_ok=True)

    # Blobless clone: downloads commit graph + tree structure, no file content.
    # Omit --single-branch so the full history is available, making the pinned
    # commit reachable via git ls-tree without a separate fetch.
    print(f"[{chain}] Cloning tree structure (blobless, no file content)...")
    run([
        "git", "clone",
        "--filter=blob:none",
        "--no-checkout",
        cfg["url"],
        str(clone_dir),
    ])

    # Verify the pinned commit is present, fall back to HEAD if not.
    commit = cfg["commit"]
    probe = run(["git", "cat-file", "-t", commit], cwd=clone_dir, check=False)
    if probe.returncode != 0:
        print(f"[{chain}] Pinned commit not found locally, falling back to HEAD.")
        commit = run(["git", "rev-parse", "HEAD"], cwd=clone_dir).stdout.strip()
    print(f"[{chain}] Using commit: {commit[:12]}")

    # Build a filename → repo-relative-path index directly from the commit tree.
    # No checkout needed — git ls-tree reads the object database directly.
    print(f"[{chain}] Indexing file tree...")
    result = run(["git", "ls-tree", "-r", "--name-only", commit, "contracts/mainnet"], cwd=clone_dir)
    name_to_path = {}
    for line in result.stdout.splitlines():
        name_to_path[Path(line).name] = line

    print(f"[{chain}] Tree index has {len(name_to_path)} entries.")

    # CSV filenames have a "0x" prefix; repo filenames do not — strip it when matching.
    paths_to_fetch = []
    not_found = set()
    for n in needed:
        key = n[2:] if n.startswith("0x") else n
        if key in name_to_path:
            paths_to_fetch.append(name_to_path[key])
        elif n in name_to_path:
            paths_to_fetch.append(name_to_path[n])
        else:
            not_found.add(n)
    if not_found:
        print(f"[{chain}] WARNING: {len(not_found)} filenames not found in repo at pinned commit.")

    if not paths_to_fetch:
        print(f"[{chain}] Nothing to fetch.")
        return

    # Fetch each needed file individually via git show (pulls only that blob).
    print(f"[{chain}] Fetching {len(paths_to_fetch)} .sol files...")
    failed = 0
    for i, rel_path in enumerate(paths_to_fetch, 1):
        dest = out_dir / Path(rel_path).name
        if dest.exists():
            continue
        result = run(["git", "show", f"{commit}:{rel_path}"], cwd=clone_dir, check=False)
        if result.returncode == 0:
            dest.write_text(result.stdout, encoding="utf-8")
        else:
            failed += 1
        if i % 500 == 0:
            pct = 100 * i // len(paths_to_fetch)
            print(f"  [{chain}] {i}/{len(paths_to_fetch)} ({pct}%)...")

    saved = len(paths_to_fetch) - failed
    print(f"[{chain}] Done. {saved} files saved to {out_dir}/")
    if failed:
        print(f"[{chain}] {failed} files could not be fetched.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Download all 4 chains (~450 MB, 15,383 files)")
    group.add_argument("--chain", choices=list(CHAINS.keys()), help="Download a single chain")
    args = parser.parse_args()

    if args.all:
        chains_to_fetch = list(CHAINS.keys())
    elif args.chain:
        chains_to_fetch = [args.chain]
    else:
        # Default: Ethereum — covers RQ1 Ethereum results + 94% of DB2 (RQ2/RQ3)
        chains_to_fetch = ["Ethereum"]
        print("Defaulting to Ethereum (covers RQ1 Ethereum + 470/500 DB2 contracts for RQ2/RQ3).")
        print("Use --all for all chains, or --chain <name> for a specific one.\n")

    OUT_BASE.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lasir_fetch_") as tmp:
        work_dir = Path(tmp)
        for chain in chains_to_fetch:
            try:
                fetch_chain(chain, CHAINS[chain], work_dir)
            except Exception as e:
                print(f"[{chain}] ERROR: {e}")

    print(f"\nDone. Contracts stored under {OUT_BASE}/<chain>/")


if __name__ == "__main__":
    main()
