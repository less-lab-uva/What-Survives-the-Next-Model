"""
prepare_input_java.py
─────────────────────
Build API-argument completion instances from a Java source tree.

Usage:
    python prepare_input_java.py netbeans
    python prepare_input_java.py netbeans --max-files 100 --max-instances 500

Output format:
    instances_<dataset>.json
"""

import argparse
import json
import os
from pathlib import Path

import javalang


MIN_ARGS = 1
MAX_ARGS = 10
MAX_ARG_LENGTH = 160

SKIP_DIRS = {
    ".git",
    ".gradle",
    "build",
    "dist",
    "target",
    "nbbuild",
}


def iter_java_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".java"):
                yield Path(dirpath) / filename


def line_starts(source: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def position_to_index(starts: list[int], line: int, column: int) -> int:
    return starts[line - 1] + column - 1


def find_matching_paren(source: str, open_idx: int) -> int | None:
    depth = 0
    quote = None
    escape = False
    line_comment = False
    block_comment = False

    i = open_idx
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue

        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue

        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return None


def split_arguments(arg_text: str) -> list[str]:
    args = []
    current = []
    round_depth = 0
    square_depth = 0
    curly_depth = 0
    angle_depth = 0
    quote = None
    escape = False

    for ch in arg_text:
        if quote:
            current.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue

        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            continue

        if ch == "(":
            round_depth += 1
        elif ch == ")":
            round_depth -= 1
        elif ch == "[":
            square_depth += 1
        elif ch == "]":
            square_depth -= 1
        elif ch == "{":
            curly_depth += 1
        elif ch == "}":
            curly_depth -= 1
        elif ch == "<":
            angle_depth += 1
        elif ch == ">" and angle_depth:
            angle_depth -= 1

        if (
            ch == ","
            and round_depth == 0
            and square_depth == 0
            and curly_depth == 0
            and angle_depth == 0
        ):
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def get_call_name(node) -> str:
    if isinstance(node, javalang.tree.MethodInvocation):
        if node.qualifier:
            return f"{node.qualifier}.{node.member}"
        return node.member
    if isinstance(node, javalang.tree.SuperMethodInvocation):
        return f"super.{node.member}"
    if isinstance(node, javalang.tree.ClassCreator):
        return f"new {node.type.name}"
    return "unknown"


def get_call_start(source: str, method_idx: int, call_name: str) -> int:
    line_start = source.rfind("\n", 0, method_idx) + 1
    prefix = source[line_start:method_idx]
    if "." in call_name:
        qualifier = call_name.rsplit(".", 1)[0]
        qualifier_idx = prefix.rfind(qualifier)
        if qualifier_idx >= 0:
            return line_start + qualifier_idx
    if call_name.startswith("new "):
        new_idx = prefix.rfind("new ")
        if new_idx >= 0:
            return line_start + new_idx
    return method_idx


def masked_call(call_name: str, num_args: int) -> str:
    placeholders = ", ".join(["/* missing */"] * num_args)
    return f"{call_name}({placeholders})"


def extract_instances(source: str, relpath: str) -> list[dict]:
    instances = []
    try:
        tree = javalang.parse.parse(source)
    except (
        javalang.parser.JavaSyntaxError,
        javalang.tokenizer.LexerError,
        IndexError,
        TypeError,
        ValueError,
    ):
        return instances

    starts = line_starts(source)
    source_lines = source.splitlines()
    seen_lines = set()

    node_types = (
        javalang.tree.MethodInvocation,
        javalang.tree.SuperMethodInvocation,
        javalang.tree.ClassCreator,
    )

    for _, node in tree:
        if not isinstance(node, node_types):
            continue
        if not getattr(node, "arguments", None):
            continue
        if not node.position:
            continue

        line, column = node.position
        if line <= 1 or line in seen_lines:
            continue

        try:
            method_idx = position_to_index(starts, line, column)
        except IndexError:
            continue

        open_idx = source.find("(", method_idx)
        if open_idx < 0:
            continue
        close_idx = find_matching_paren(source, open_idx)
        if close_idx is None:
            continue

        arg_text = source[open_idx + 1:close_idx]
        ground_truth = split_arguments(arg_text)
        if not (MIN_ARGS <= len(ground_truth) <= MAX_ARGS):
            continue
        if any(not arg or len(arg) > MAX_ARG_LENGTH for arg in ground_truth):
            continue

        call_name = get_call_name(node)
        if call_name == "unknown":
            continue

        call_start = get_call_start(source, method_idx, call_name)
        call_text = source[call_start:open_idx].strip() or call_name
        preceding_code = source[:call_start].strip()
        if not preceding_code:
            continue

        line_start = starts[line - 1]
        line_prefix = source[line_start:call_start].lstrip()
        call_line = masked_call(call_text, len(ground_truth))
        if line_prefix:
            call_line = f"{line_prefix}{call_line}"

        seen_lines.add(line)
        instances.append({
            "filepath": relpath,
            "preceding_code": preceding_code,
            "call_line": call_line,
            "ground_truth": ground_truth,
            "num_args": len(ground_truth),
        })

    return instances


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", help="Java dataset name, e.g. netbeans")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--max-instances", type=int, default=None)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    source_root = base_dir / "dataset-java" / args.dataset
    output_path = base_dir / f"instances_{args.dataset}.json"

    if not source_root.exists():
        raise FileNotFoundError(f"Java dataset not found: {source_root}")

    java_files = list(iter_java_files(source_root))
    if args.max_files is not None:
        java_files = java_files[:args.max_files]

    print(f"Loaded {len(java_files)} Java files from: {source_root}")

    all_instances = []
    processed = 0
    failed = 0

    for i, path in enumerate(java_files, start=1):
        relpath = path.relative_to(source_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            failed += 1
            continue

        instances = extract_instances(source, relpath)
        all_instances.extend(instances)
        processed += 1

        if i % 250 == 0:
            print(f"  Processed {i}/{len(java_files)} files | instances: {len(all_instances)}")

        if args.max_instances and len(all_instances) >= args.max_instances:
            all_instances = all_instances[:args.max_instances]
            print(f"Reached max instances limit ({args.max_instances}), stopping.")
            break

    with output_path.open("w") as f:
        json.dump(all_instances, f, indent=2)

    print(f"\n{'=' * 60}")
    print("  JAVA PREPROCESSING COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Dataset                : {args.dataset}")
    print(f"  Source files processed : {processed}")
    print(f"  Source files failed    : {failed}")
    print(f"  Total instances created: {len(all_instances)}")
    print(f"  Output saved to        : {output_path}")

    if all_instances:
        sample = all_instances[0]
        print(f"\n  SAMPLE INSTANCE")
        print(f"{'=' * 60}")
        print(f"  filepath     : {sample['filepath']}")
        print(f"  num_args     : {sample['num_args']}")
        print(f"  ground_truth : {sample['ground_truth']}")
        print(f"  call_line    : {sample['call_line']}")


if __name__ == "__main__":
    main()
