"""
preprocess.py
─────────────
Preprocessing script for the ETH PY150 dataset.

Takes raw .py source files and produces instances ready for LLM evaluation:
  - preceding_code  : all code before the method call
  - call_line     : the method call with arguments replaced by /* missing */
  - ground_truth    : the actual arguments (for evaluation)

Usage:
    python prepare_input.py

Output format (instances.json):
    [
        {
            "filepath"       : "owner/repo/path/to/file.py",
            "preceding_code" : "... all code before the call ...",
            "call_line"    : "result = transformer.resize(/* missing */, /* missing */)",
            "ground_truth"   : ["originalImage", "200", "150"],
            "num_args"       : 3
        },
        ...
    ]

Requirements:
    No external dependencies beyond the Python standard library.
"""

import ast
import json
import os
from pathlib import Path


# Minimum number of arguments a call must have to be included
MIN_ARGS = 1

# Maximum number of arguments (to avoid noise from huge calls)
MAX_ARGS = 10

# Skip calls where any argument is itself a large nested call
# (keeps instances clean and readable)
MAX_ARG_LENGTH = 100  # characters



def load_source_from_disk(filepath: str, source_dir: str) -> str | None:
    """Load .py source from a local directory."""
    full_path = os.path.join(source_dir, filepath)
    if os.path.exists(full_path):
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    return None


def get_call_name(node: ast.Call) -> str:
    """Extract a human-readable name from a Call node."""
    func = node.func
    if isinstance(func, ast.Attribute):
        # e.g. transformer.resize(...)
        try:
            obj = ast.unparse(func.value)
            return f"{obj}.{func.attr}"
        except Exception:
            return func.attr
    elif isinstance(func, ast.Name):
        # e.g. resize(...)
        return func.id
    else:
        try:
            return ast.unparse(func)
        except Exception:
            return "unknown"


def get_arg_text(arg_node: ast.expr) -> str | None:
    try:
        text = ast.unparse(arg_node)
        if len(text) > MAX_ARG_LENGTH:
            return None
        return text
    except Exception:
        return None


def mask_call(call_name: str, num_args: int) -> str:

    placeholders = ", ".join(["/* missing */"] * num_args)
    return f"{call_name}({placeholders})"


def extract_instances(source: str, filepath: str) -> list[dict]:

    instances = []

    # Try to parse the file — skip if syntax errors
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return instances

    lines = source.splitlines()
    seen_linenos = set()  # one instance per source line

    for node in ast.walk(tree):
        # Only process Call nodes
        if not isinstance(node, ast.Call):
            continue

        # Skip calls with no positional arguments
        if not node.args:
            continue

        # Skip calls with too many or too few arguments
        if not (MIN_ARGS <= len(node.args) <= MAX_ARGS):
            continue

        # Skip if we can't determine line number
        if not hasattr(node, "lineno"):
            continue

        lineno = node.lineno  # 1-indexed

        # Skip if call is on the very first line (no preceding code)
        if lineno <= 1:
            continue

        # One instance per source line — skip if we already have one
        if lineno in seen_linenos:
            continue

        # Extract ground truth arguments
        ground_truth = []
        skip = False
        for arg in node.args:
            arg_text = get_arg_text(arg)
            if arg_text is None:
                skip = True
                break
            ground_truth.append(arg_text)

        if skip or not ground_truth:
            continue

        # Extract preceding code (everything before this line)
        preceding_code = "\n".join(lines[:lineno - 1]).strip()

        # Skip if preceding code is empty
        if not preceding_code:
            continue

        # Build the masked call
        call_name   = get_call_name(node)
        call_line = mask_call(call_name, len(ground_truth))

        # Build the full masked line for context
        # (preserves assignment if present, e.g. "result = transformer.resize(/* missing */)")
        original_line = lines[lineno - 1]
        if "=" in original_line and not original_line.strip().startswith("#"):
            lhs = original_line.split("=")[0].strip()
            full_masked_line = f"{lhs} = {call_line}"
        else:
            full_masked_line = call_line

        seen_linenos.add(lineno)
        instances.append({
            "filepath"      : filepath,
            "preceding_code": preceding_code,
            "call_line"   : full_masked_line,
            "ground_truth"  : ground_truth,
            "num_args"      : len(ground_truth),
        })

    return instances


def main():
    BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
    MANIFEST    = os.path.join(BASE_DIR, "eth_py150_open", "eval__manifest.json")
    SOURCE_DIR  = os.path.join(BASE_DIR, "dataset", "py150", "py150_files", "data")
    OUTPUT      = os.path.join(BASE_DIR, "instances.json")
    SAMPLES     = None   # None = process all files
    MAX_INSTANCES = None  # set to an int to cap total instances

    with open(MANIFEST) as f:
        records = json.load(f)
    print(f"Loaded manifest: {len(records)} files")

    records = records[:SAMPLES]
    print(f"Processing first {SAMPLES} files")

    all_instances = []
    processed     = 0
    failed        = 0

    for i, record in enumerate(records):
        filepath = record["filepath"]
        source   = load_source_from_disk(filepath, SOURCE_DIR)

        if not source:
            failed += 1
            continue

        instances = extract_instances(source, filepath)
        all_instances.extend(instances)
        processed += 1

        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(records)} files | "
                  f"Instances so far: {len(all_instances)}")

        if MAX_INSTANCES and len(all_instances) >= MAX_INSTANCES:
            all_instances = all_instances[:MAX_INSTANCES]
            print(f"Reached max_instances limit ({MAX_INSTANCES}), stopping.")
            break

    with open(OUTPUT, "w") as f:
        json.dump(all_instances, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  PREPROCESSING COMPLETE")
    print(f"{'='*60}")
    print(f"  Source files processed : {processed}")
    print(f"  Source files failed    : {failed}")
    print(f"  Total instances created: {len(all_instances)}")
    print(f"  Output saved to        : {OUTPUT}")
    print()

    # Show a few sample instances
    print(f"  SAMPLE INSTANCES")
    print(f"{'='*60}")
    for i, inst in enumerate(all_instances[:1]):
        print(f"\n  Instance #{i+1}")
        print(f"  {'─'*56}")
        print(f"  filepath     : {inst['filepath']}")
        print(f"  num_args     : {inst['num_args']}")
        print(f"  ground_truth : {inst['ground_truth']}")
        print(f"\n  preceding_code:")
        print(inst['preceding_code'])
        print(f"\n  call_line:")
        print(f"    {inst['call_line']}")


if __name__ == "__main__":
    main()
