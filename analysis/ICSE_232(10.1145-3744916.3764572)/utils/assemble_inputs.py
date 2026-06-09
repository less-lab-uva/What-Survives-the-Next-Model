"""Reassemble the split Specine input files.

The downsampled benchmarks are too large for GitHub's per-file limit, so they're committed as
`<name>.part-aa`, `.part-ab`, ... chunks (each < 50 MB). This concatenates them back into the
whole `.jsonl` files that `main.py` / `evaluator.py` read. Run once after cloning. Idempotent.

    python3 utils/assemble_inputs.py
"""

import os
import glob

TARGETS = [
    os.path.join("inputs", "apps.down_sampled_15usd.jsonl"),
    os.path.join("inputs", "code_contests.down_sampled_15usd.jsonl"),
]

for target in TARGETS:
    parts = sorted(glob.glob(target + ".part-*"))
    if not parts:
        print(f"  no parts for {target} — skipping")
        continue
    with open(target, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                out.write(f.read())
    mb = os.path.getsize(target) / (1024 * 1024)
    print(f"  assembled {target} from {len(parts)} parts ({mb:.0f} MB)")
