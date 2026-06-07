"""
Panta — generation: run Prompt A and Prompt B on Defects4J classes.
Usage: python main.py [--n N] [--seed S] [--workers W]
Output: outputs/outputs_A.jsonl  outputs/outputs_B.jsonl
Env:    ANTHROPIC_API_KEY
Conda:  panta-env
"""

import argparse
import json
import random
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

MODEL      = "claude-sonnet-4-6"
HERE       = Path(__file__).parent
SUBJ_DIR   = HERE / "data" / "defects4j-subjects"
CLASS_LIST = HERE / "data" / "defects4j-codefiles"

_print_lock = threading.Lock()


def load_prompts():
    return (
        (HERE / "prompts" / "prompt_A.txt").read_text(),
        (HERE / "prompts" / "prompt_B.txt").read_text(),
    )


TARGET_PROJECTS = {"Codec-18f", "Collections-28f", "Csv-16f", "Jsoup-93f"}


def load_dataset():
    """
    Load classes from the 4 projects that match the paper's class counts exactly.
    Filter: at least one method with CYC > 10 and max CYC <= 40 (paper's criteria).
    All three sections are used (src_test_exact_match, src_test_fuzz_match, src_without_tests).
    """
    samples = []
    for json_file in sorted(CLASS_LIST.glob("*-codefiles.json")):
        project = json_file.stem.replace("-codefiles", "")
        if project not in TARGET_PROJECTS:
            continue
        data = json.loads(json_file.read_text())
        for section in ("src_test_exact_match", "src_test_fuzz_match", "src_without_tests"):
            for entry in data.get(section, []):
                if "error" in entry or "methods_under_test" not in entry:
                    continue
                # CYC filter: must have at least one method with CYC > 10, max CYC <= 40
                mut = entry["methods_under_test"]
                high = {**mut.get("11-20", {}), **mut.get(">20", {})}
                if not high:
                    continue
                all_high_cyc = [v[0] for v in high.values()
                                if isinstance(v, (list, tuple)) and v]
                if any(c > 40 for c in all_high_cyc):
                    continue

                class_name = entry["src_name"]
                rel = entry["src_path"].split("defects4j-subjects/", 1)[-1]
                src_path = (SUBJ_DIR / rel).resolve()
                if not src_path.exists():
                    continue
                src_parts = src_path.parts
                try:
                    main_idx = list(src_parts).index("main")
                    package  = ".".join(src_parts[main_idx + 2:-1])
                except (ValueError, IndexError):
                    package = ""
                samples.append({
                    "id":       f"{project}/{class_name}",
                    "project":  project,
                    "class":    class_name,
                    "package":  package,
                    "src_path": str(src_path),
                })
    return samples


def load_done(path):
    if not path.exists():
        return set()
    return {(json.loads(l)["project"], json.loads(l)["class"])
            for l in path.read_text().splitlines() if l.strip()}


def placeholder_test_file(package, class_name):
    return (
        f"package {package};\n\nimport org.junit.Test;\nimport static org.junit.Assert.*;\n\n"
        f"public class {class_name}Test {{\n\n    @Test\n"
        "    public void testPlaceHolder() {\n        assertTrue(true);\n    }\n}\n"
    )


def call_claude(system, user):
    client = anthropic.Anthropic()
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=MODEL, max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    elapsed = time.perf_counter() - t0
    return resp.content[0].text, resp.usage, elapsed


def stratified_sample(tasks, n, seed):
    by_project = defaultdict(list)
    for s in tasks:
        by_project[s["project"]].append(s)
    total, sampled, rng = len(tasks), [], random.Random(seed)
    for proj, items in by_project.items():
        quota = max(1, round(n * len(items) / total))
        sampled.extend(rng.sample(items, min(quota, len(items))))
    rng.shuffle(sampled)
    sampled = sampled[:n]
    if len(sampled) < n:
        leftover = [s for s in tasks if s not in sampled]
        rng.shuffle(leftover)
        sampled.extend(leftover[:n - len(sampled)])
    return sampled


def extract_tests(raw):
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text).get("generated_tests", "")
    except Exception:
        pass
    m = re.search(r'"generated_tests"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except Exception:
            return m.group(1)
    # Fallback: model returned prose + java code block (closed or unclosed)
    blocks = re.findall(r"```(?:java)?\s*\n(.*?)```", raw, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    m2 = re.search(r"```(?:java)?\s*\n(.*)", raw, re.DOTALL)
    if m2:
        return m2.group(1).strip()
    return raw.strip()


def run_one(sample, variant, prompt, out_path, file_lock, counters, counter_lock, total):
    source    = Path(sample["src_path"]).read_text(errors="replace")
    test_stub = placeholder_test_file(sample["package"], sample["class"])
    user      = f"source_code:\n{source}\n\ntest_file:\n{test_stub}"

    raw, usage, elapsed = call_claude(prompt, user)
    tests = extract_tests(raw)
    n_tests = len(re.findall(r"@Test", tests))

    record = json.dumps({
        "project":         sample["project"],
        "class":           sample["class"],
        "package":         sample["package"],
        "src_path":        sample["src_path"],
        "generated_tests": tests,
        "raw":             raw,
        "response_time":   round(elapsed, 3),
    })
    with file_lock:
        with open(out_path, "a") as f:
            f.write(record + "\n")

    with counter_lock:
        counters["done"] += 1
        done = counters["done"]

    with _print_lock:
        print(f"[{done}/{total}] {sample['project']}/{sample['class']}  "
              f"variant={variant}  tests={n_tests}  t={elapsed:.2f}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["A", "B", "both"], default="both",
                        help="which prompt(s) to run (default: both)")
    parser.add_argument("--n",       type=int, default=None)
    parser.add_argument("--seed",    type=int, default=42)
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel threads (default: 4)")
    args = parser.parse_args()
    run_a = args.variant in ("A", "both")
    run_b = args.variant in ("B", "both")

    prompt_a, prompt_b = load_prompts()
    dataset = load_dataset()

    out_a = HERE / "outputs" / "outputs_A.jsonl"
    out_b = HERE / "outputs" / "outputs_B.jsonl"
    out_a.parent.mkdir(exist_ok=True)

    done_a = load_done(out_a)
    done_b = load_done(out_b)

    candidate = [
        s for s in dataset
        if (run_a and (s["project"], s["class"]) not in done_a)
        or (run_b and (s["project"], s["class"]) not in done_b)
    ]

    if args.n is not None:
        already   = len(done_a | done_b)
        n_need    = max(0, args.n - already)
        candidate = stratified_sample(candidate, min(n_need, len(candidate)), args.seed)

    lock_a = threading.Lock()
    lock_b = threading.Lock()

    all_tasks = []
    for s in candidate:
        key = (s["project"], s["class"])
        if run_a and key not in done_a:
            all_tasks.append((s, "A", prompt_a, out_a, lock_a))
        if run_b and key not in done_b:
            all_tasks.append((s, "B", prompt_b, out_b, lock_b))

    n_total = len(dataset)
    print(f"Model: {MODEL}  |  Dataset: {n_total}  |  Tasks to run: {len(all_tasks)}")
    print(f"Already done — A: {len(done_a)}  B: {len(done_b)}\n")

    counters     = {"done": 0}
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(run_one, s, v, pr, o, lk, counters, counter_lock, len(all_tasks))
            for s, v, pr, o, lk in all_tasks
        ]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                with _print_lock:
                    print(f"ERROR: {e}")

    n_ran = counters["done"]
    print(f"\n{'='*50}")
    print(f"Ran: {n_ran}")


if __name__ == "__main__":
    main()
