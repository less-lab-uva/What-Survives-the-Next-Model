#!/usr/bin/env python3
"""
CoderEval evaluation script for Prompt A and Prompt B.

Steps run automatically:
  1. Convert outputs_A.jsonl / outputs_B.jsonl to the format expected by PythonExec.py
  2. Set up a writable workspace with the scripts CoderEval needs
  3. Run GroundTruth.py to validate the original test environment
  4. Execute the CoderEval runner for each prompt
  5. Compute Pass@1/3/5 and save results to results/results_A.jsonl and results_B.jsonl

Prerequisites:
  module load apptainer/1.5.0   (run this in the terminal before this script)

Usage:
  python3 evaluator.py
"""

import json
import os
import shutil
import subprocess
import sys
from math import comb

PROJECT_FOLDER   = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_FOLDER   = os.path.join(PROJECT_FOLDER, "outputs")
RESULTS_FOLDER   = os.path.join(PROJECT_FOLDER, "results")
SANDBOX          = os.path.join(PROJECT_FOLDER, "CoderEval-Docker", "codereval_sandbox")
BUILDS_WORKSPACE = os.path.join(PROJECT_FOLDER, "CoderEval-Docker", "builds_workspace")
SANDBOX_REPOS    = os.path.join(SANDBOX, "home", "travis", "builds", "repos")
SANDBOX_BUILDS   = os.path.join(SANDBOX, "home", "travis", "builds")
PROMPTS          = ["A", "B"]

WORKSPACE_FILES = [
    "PythonExec.py",
    "GroundTruth.py",
    "getfailfile.py",
    "CoderEval4Python.json",
    "testcasesoriginal",
]


def check_prerequisites():
    if not shutil.which("apptainer"):
        print("[!] apptainer not found in PATH.")
        print("    Run: module load apptainer/1.5.0")
        sys.exit(1)
    if not os.path.isdir(SANDBOX):
        print(f"[!] Sandbox not found: {SANDBOX}")
        print("    Extract CoderEval.tar into CoderEval-Docker/codereval_sandbox/ first.")
        sys.exit(1)
    for letter in PROMPTS:
        path = os.path.join(OUTPUTS_FOLDER, f"outputs_{letter}.jsonl")
        if not os.path.exists(path):
            print(f"[!] Missing outputs file: {path}")
            sys.exit(1)
    print("[*] Prerequisites OK.")


def setup_workspace():
    """Copy CoderEval scripts and data files from the sandbox to a writable host directory.

    The sandbox filesystem cannot be written to on this cluster. This workspace
    is bind-mounted over /home/travis/builds inside the container so that scripts
    can write log and output files freely. The sandbox repos are bind-mounted
    separately on top of it.
    """
    print("\n=== Setting up writable workspace ===")
    os.makedirs(BUILDS_WORKSPACE, exist_ok=True)
    os.makedirs(os.path.join(BUILDS_WORKSPACE, "repos"), exist_ok=True)
    for fname in WORKSPACE_FILES:
        src = os.path.join(SANDBOX_BUILDS, fname)
        dst = os.path.join(BUILDS_WORKSPACE, fname)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f"  Copied: {fname}")
        else:
            print(f"  Already exists: {fname}")


def apptainer_exec(cmd_args, label=""):
    """Run a command inside the CoderEval sandbox without requiring a writable sandbox.

    Mounts:
      BUILDS_WORKSPACE -> /home/travis/builds  (writable host dir for script outputs)
      SANDBOX_REPOS    -> /home/travis/builds/repos  (sandbox repos, writable via bind)
      PROJECT_FOLDER   -> /workspace  (our project, for reading input and writing results)
    """
    full_cmd = [
        "apptainer", "exec",
        "--bind", f"{BUILDS_WORKSPACE}:/home/travis/builds",
        "--bind", f"{SANDBOX_REPOS}:/home/travis/builds/repos",
        "--bind", f"{PROJECT_FOLDER}:/workspace",
        "--pwd", "/home/travis/builds",
        SANDBOX,
    ] + cmd_args
    if label:
        print(f"[*] {label}")
    result = subprocess.run(full_cmd)
    if result.returncode != 0:
        print(f"[!] Command failed with exit code {result.returncode}. Stopping.")
        sys.exit(result.returncode)


def convert_outputs():
    """Convert outputs_{A,B}.jsonl to the JSONL format expected by PythonExec.py.

    Output format per line: {"_id": "...", "generate_results": ["code1", ..., "code5"]}
    Intermediate files are saved under outputs/ as input_{letter}.jsonl.
    """
    print("\n=== Converting outputs to CoderEval input format ===")
    os.makedirs(OUTPUTS_FOLDER, exist_ok=True)
    for letter in PROMPTS:
        src = os.path.join(OUTPUTS_FOLDER, f"outputs_{letter}.jsonl")
        dst = os.path.join(OUTPUTS_FOLDER, f"input_{letter}.jsonl")
        with open(src) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        with open(dst, "w") as fout:
            for entry in entries:
                fout.write(json.dumps({
                    "_id": entry["_id"],
                    "generate_results": entry["predictions"],
                }) + "\n")
        print(f"  Prompt {letter}: {len(entries)} tasks -> {dst}")


def reset_test_environment(letter):
    """Run GroundTruth.py to verify the original test files pass before each evaluation.

    Also removes any leftover state from a previous run.
    """
    print(f"\n=== Resetting test environment (Prompt {letter}) ===")
    apptainer_exec(["python", "GroundTruth.py"], label="Running GroundTruth.py")


def run_codereval(letter):
    """Inject each generated function into the project test harness and record pass/fail.

    PythonExec.py writes its output to outputs/input_{letter}.jsonl_out.jsonl,
    one line per task with per-attempt is_pass results.
    """
    print(f"\n=== Running CoderEval for Prompt {letter} ===")
    input_path = f"/workspace/outputs/input_{letter}.jsonl"
    apptainer_exec(
        ["python", "PythonExec.py", input_path, "5"],
        label=f"PythonExec.py Prompt {letter}",
    )
    out_file = os.path.join(OUTPUTS_FOLDER, f"input_{letter}.jsonl_out.jsonl")
    if os.path.exists(out_file):
        print(f"  [+] Raw evaluation output: {out_file}")
    else:
        print(f"  [!] Expected output file not found: {out_file}")


def pass_at_k(n, c, k):
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def save_results(letter, aggregate, task_results):
    """Save aggregate Pass@k summary and per-task results to results/results_{letter}.jsonl.

    First line: aggregate summary dict.
    Subsequent lines: one dict per task with pass/fail details.
    """
    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    path = os.path.join(RESULTS_FOLDER, f"results_{letter}.jsonl")
    with open(path, "w") as f:
        f.write(json.dumps(aggregate) + "\n")
        for r in task_results:
            f.write(json.dumps(r) + "\n")
    print(f"  [+] Results saved to: {path}")


def compute_scores():
    """Read per-task pass/fail results, compute Pass@1/3/5, and save to results/.

    Uses the unbiased estimator: Pass@k = mean over tasks of (1 - C(n-c,k)/C(n,k)).
    The denominator is the number of evaluated tasks, not the full dataset size.
    """
    print("\n=== Pass@k Results ===")
    print(f"  {'Prompt':<10} {'Tasks':<8} {'Pass@1':>8} {'Pass@3':>8} {'Pass@5':>8}")
    print(f"  {'-'*46}")
    for letter in PROMPTS:
        out_file = os.path.join(OUTPUTS_FOLDER, f"input_{letter}.jsonl_out.jsonl")
        if not os.path.exists(out_file):
            print(f"  Prompt {letter}: output file not found, skipping.")
            continue
        with open(out_file) as f:
            task_results = [json.loads(l) for l in f if l.strip()]
        if not task_results:
            print(f"  Prompt {letter}: output file is empty, skipping.")
            continue

        n = 5
        scores = [
            sum(1 for attempt in r.get("generate_results", []) if attempt.get("is_pass"))
            for r in task_results
        ]
        total = len(scores)
        p1 = sum(pass_at_k(n, c, 1) for c in scores) / total * 100
        p3 = sum(pass_at_k(n, c, 3) for c in scores) / total * 100
        p5 = sum(pass_at_k(n, c, 5) for c in scores) / total * 100

        print(f"  Prompt {letter:<9} {total:<8} {p1:>7.2f}% {p3:>7.2f}% {p5:>7.2f}%")

        aggregate = {
            "prompt":      letter,
            "total_tasks": total,
            "pass_at_1":   round(p1, 4),
            "pass_at_3":   round(p3, 4),
            "pass_at_5":   round(p5, 4),
        }
        save_results(letter, aggregate, task_results)

    print(f"\n  Baseline (AllianceCoderGPT, 230 tasks): Pass@1 = 36.52%")


def main():
    print("=== CoderEval Evaluation ===")
    check_prerequisites()
    convert_outputs()
    setup_workspace()
    for letter in PROMPTS:
        reset_test_environment(letter)
        run_codereval(letter)
    compute_scores()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
