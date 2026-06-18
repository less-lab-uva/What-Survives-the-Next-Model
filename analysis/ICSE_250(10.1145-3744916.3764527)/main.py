#!/usr/bin/env python3
"""
Usage:
    python3 main.py <budget_usd> [dataset]

    dataset: 'rq3' — process the 46 RQ3 PRs (includes all 20 available RQ1 PRs,
                      so running rq3 first automatically covers the RQ1 overlap)
             'rq1' — process all 30 RQ1 PRs; if rq3 was already run, only the
                      10 RQ1-exclusive PRs are new work (the 20 overlap are skipped)
             (omit) — same as 'rq3'
"""

import anthropic
import csv
import importlib.util
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR          = Path(__file__).parent
PROMPTS_DIR       = BASE_DIR / "prompts"
OUTPUT_DIR        = BASE_DIR / "outputs"
DATA_DIR          = BASE_DIR / ".." / "data"
PR_DIR            = DATA_DIR / "pulled_prs" / "ground_truth"
RQ1_CSV           = DATA_DIR / "real-world_problems.csv"
GITHUB_TOKEN_FILE = BASE_DIR / ".github_token"

# GitHub repo slugs — used when pulling missing PRs
REPO_IDS = {
    "keras":       "keras-team/keras",
    "marshmallow": "marshmallow-code/marshmallow",
    "pandas":      "pandas-dev/pandas",
    "scipy":       "scipy/scipy",
}

MODEL        = "claude-sonnet-4-6"
INPUT_PRICE  = 3.0    # USD per 1M input tokens
OUTPUT_PRICE = 15.0   # USD per 1M output tokens
PROMPTS      = ["A", "B"]
MAX_TOKENS   = 950_000
CPT          = 3.5    # estimated chars per token
SIZE_THRESH  = 50_000  # bytes; records larger than this go to separate files


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(letter: str) -> str:
    path = PROMPTS_DIR / f"prompt{letter}.py"
    spec = importlib.util.spec_from_file_location("prompt_module", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "prompt"):
        raise AttributeError(f"No 'prompt' variable in {path}")
    return module.prompt


# ---------------------------------------------------------------------------
# Dataset membership
# ---------------------------------------------------------------------------

def build_rq1_keys() -> set:
    """Return set of (project, pr_number) for all 30 RQ1 CSV entries."""
    keys = set()
    with open(RQ1_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pr_url = row.get("PR", "").strip().rstrip("/")
            proj   = row.get("Project", "").strip().lower()
            if not pr_url or not proj:
                continue
            m = re.search(r"/pull/(\d+)", pr_url)
            if m:
                keys.add((proj, int(m.group(1))))
    return keys


def build_rq3_keys() -> set:
    """Return set of (project, pr_number) for all PRs in data/ground_truth/."""
    gt_dir = DATA_DIR / "ground_truth"
    keys   = set()
    for project_dir in gt_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for fname in project_dir.iterdir():
            if fname.suffix == ".json":
                keys.add((project_dir.name, int(fname.stem)))
    return keys


# ---------------------------------------------------------------------------
# Data availability — pull missing PRs from GitHub before inference
# ---------------------------------------------------------------------------

def ensure_data_available(dataset: str, rq1_keys: set, rq3_keys: set) -> None:
    """
    Check which PRs are expected for the requested dataset but missing from
    pulled_prs/ground_truth/. If any are missing, attempt to pull them via
    the GitHub API.

    Falls back gracefully if:
      - .github_token is absent (skips pulling, warns)
      - PyGithub is not installed (skips pulling, warns)
      - A specific PR fetch fails (logs error, continues)

    Always proceeds with whatever data is already on disk.
    """
    # Always check the full union — we process all PRs regardless of dataset arg
    expected_keys = rq3_keys | rq1_keys
    missing = [
        (proj, nb)
        for proj, nb in sorted(expected_keys)
        if not (PR_DIR / proj / f"{nb}.json").exists()
    ]

    total = len(expected_keys)
    avail = total - len(missing)

    if not missing:
        print(f"    Data: all {total} expected PRs already on disk.")
        return

    print(f"    Data: {avail}/{total} PRs on disk, {len(missing)} missing.")

    if not GITHUB_TOKEN_FILE.exists():
        print(f"    [!] No .github_token found — skipping pull. "
              f"Run pull_prs.py to fetch the missing PRs.")
        return

    try:
        from github import Github, Auth
        from pull_prs import fetch_pr_data
    except ImportError:
        print("    [!] PyGithub not installed — skipping pull. "
              "Install with: pip install PyGithub")
        return

    token  = GITHUB_TOKEN_FILE.read_text().strip()
    github = Github(auth=Auth.Token(token))
    repos  = {}  # cache repo objects

    print(f"    Pulling {len(missing)} missing PRs from GitHub ...")
    pulled = 0
    for proj, pr_nb in missing:
        if proj not in REPO_IDS:
            print(f"      {proj}/{pr_nb}: unknown project, skipping")
            continue
        out_path = PR_DIR / proj / f"{pr_nb}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if proj not in repos:
                repos[proj] = github.get_repo(REPO_IDS[proj])
            data = fetch_pr_data(repos[proj], pr_nb)
            if data is None:
                print(f"      {proj}/{pr_nb}: not merged, skipping")
                continue
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"      {proj}/{pr_nb}: saved")
            pulled += 1
        except Exception as e:
            print(f"      {proj}/{pr_nb}: error — {e}")
            time.sleep(1)

    still_missing = len(missing) - pulled
    print(f"    Pulled {pulled}/{len(missing)} missing PRs"
          + (f"; {still_missing} could not be fetched." if still_missing else "."))


def load_prs_for_dataset(dataset: str, rq1_keys: set, rq3_keys: set) -> list:
    """
    Load PR dicts from pulled_prs/ground_truth/, filtered to the requested
    dataset. Each PR is annotated with 'datasets': list of all memberships.
    """
    all_prs = {}
    for project_dir in sorted(PR_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        project = project_dir.name
        for pr_file in sorted(project_dir.iterdir()):
            if pr_file.suffix != ".json":
                continue
            with open(pr_file, encoding="utf-8") as f:
                data = json.load(f)
            data["project"] = project
            key = (project, data["pr_number"])
            memberships = []
            if key in rq3_keys:
                memberships.append("rq3")
            if key in rq1_keys:
                memberships.append("rq1")
            if not memberships:
                memberships = ["rq3"]  # default for PRs without explicit membership
            data["_datasets"] = memberships
            all_prs[key] = data

    return list(all_prs.values())


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

def output_jsonl(letter: str) -> Path:
    return OUTPUT_DIR / f"outputs_{letter}.jsonl"


def token_log(letter: str) -> Path:
    return OUTPUT_DIR / f"tokens_{letter}.jsonl"


# ---------------------------------------------------------------------------
# Completion tracking
# ---------------------------------------------------------------------------

def get_completed(letter: str) -> set:
    path = output_jsonl(letter)
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                done.add((r.get("project"), r.get("pr_number")))
            except json.JSONDecodeError:
                pass
    for p in OUTPUT_DIR.glob(f"*_prompt{letter}.json"):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            done.add((r.get("project"), r.get("pr_number")))
        except (json.JSONDecodeError, OSError):
            pass
    return done


def pr_key(pr: dict) -> tuple:
    return (pr.get("project"), pr.get("pr_number"))


def get_pending(prs: list) -> tuple:
    """Return (partial, untouched) — always drain partial before picking from untouched."""
    completed = {p: get_completed(p) for p in PROMPTS}
    partial, untouched = [], []
    for pr in prs:
        key  = pr_key(pr)
        done = [p for p in PROMPTS if key in completed[p]]
        if done and len(done) < len(PROMPTS):
            partial.append(pr)
        elif not done:
            untouched.append(pr)
    return partial, untouched


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

def get_total_spent() -> float:
    total = 0.0
    for letter in PROMPTS:
        path = token_log(letter)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                total += r.get("cost_usd", {}).get("total_cost", 0.0)
            except json.JSONDecodeError:
                pass
    return round(total, 6)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _fix_json_newlines(s: str) -> str:
    """Escape bare newlines/tabs inside JSON string values (common LLM output issue)."""
    result = []
    in_string = False
    escape = False
    for ch in s:
        if escape:
            result.append(ch)
            escape = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escape = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == "\n":
            result.append("\\n")
        elif in_string and ch == "\r":
            result.append("\\r")
        elif in_string and ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
    return "".join(result)


def parse_response(text: str) -> dict:
    candidates = []
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1))
    candidates.append(text)

    decoder = json.JSONDecoder()
    for raw in candidates:
        # Direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Right-to-left scan
        for match in reversed(list(re.finditer(r"\{", raw))):
            try:
                obj, _ = decoder.raw_decode(raw, match.start())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
        # Repair unescaped newlines, then retry
        fixed = _fix_json_newlines(raw)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        for match in reversed(list(re.finditer(r"\{", fixed))):
            try:
                obj, _ = decoder.raw_decode(fixed, match.start())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    # Last resort: extract fields individually via regex.
    # verdict is always a simple inline value — never contains newlines.
    m_verdict = re.search(r'"verdict"\s*:\s*"(intended|unintended)"', text, re.IGNORECASE)
    if m_verdict:
        result = {"verdict": m_verdict.group(1).lower()}
        for field in ("explanation", "test_case",
                      "predicted_output_before_pr", "predicted_output_after_pr"):
            # [^"\\] matches any char except quote/backslash (including bare newlines)
            fm = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
            if fm:
                val = fm.group(1)
                val = (val.replace("\\n", "\n").replace("\\t", "\t")
                          .replace('\\"', '"').replace("\\\\", "\\"))
                result[field] = val
        return result

    return {}


# ---------------------------------------------------------------------------
# Save result
# ---------------------------------------------------------------------------

def save_result(pr: dict, result: dict, letter: str, timestamp: str) -> None:
    record = {
        "pr_number":                  pr.get("pr_number"),
        "project":                    pr.get("project"),
        "datasets":                   pr.get("_datasets", ["rq3"]),  # list of all memberships
        "timestamp":                  timestamp,
        "verdict":                    result.get("verdict", ""),
        "test_case":                  result.get("test_case", ""),
        "predicted_output_before_pr": result.get("predicted_output_before_pr", ""),
        "predicted_output_after_pr":  result.get("predicted_output_after_pr", ""),
        "explanation":                result.get("explanation", ""),
    }
    record_bytes = len(json.dumps(record).encode("utf-8"))
    project = pr.get("project", "unknown")
    pr_nb   = pr.get("pr_number", "unknown")

    if record_bytes > SIZE_THRESH:
        out_file = OUTPUT_DIR / f"{project}_{pr_nb}_prompt{letter}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        print(f"    [+] Saved separately: {out_file.name} ({record_bytes:,} bytes)")
    else:
        with open(output_jsonl(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        print(f"    [+] Appended to outputs_{letter}.jsonl")


# ---------------------------------------------------------------------------
# Single prompt run
# ---------------------------------------------------------------------------

def run_pr(pr: dict, letter: str, system_prompt: str, client: anthropic.Anthropic) -> None:
    user_msg = json.dumps({
        "title":               pr.get("title", ""),
        "description":         pr.get("description", ""),
        "diff":                pr.get("diff", ""),
        "commit_messages":     pr.get("commit_messages", []),
        "discussion_comments": pr.get("discussion_comments", []),
    }, indent=2)

    est_tokens = (len(system_prompt) + len(user_msg)) / CPT
    if est_tokens > MAX_TOKENS:
        print(f"    prompt {letter}: SKIPPED — estimated {int(est_tokens):,} tokens exceeds limit")
        with open(output_jsonl(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "pr_number": pr.get("pr_number"),
                "project":   pr.get("project"),
                "datasets":  pr.get("_datasets", ["rq3"]),
                "skipped":   True,
                "reason":    "too_large",
                "estimated_tokens": int(est_tokens),
            }) + "\n")
        return

    timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    t_start       = time.time()
    response_text = ""

    with client.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for chunk in stream.text_stream:
            response_text += chunk
            print(chunk, end="", flush=True)
        print()
        usage = stream.get_final_message().usage

    duration      = round(time.time() - t_start, 3)
    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    input_cost    = round(input_tokens  * INPUT_PRICE  / 1_000_000, 6)
    output_cost   = round(output_tokens * OUTPUT_PRICE / 1_000_000, 6)
    total_cost    = round(input_cost + output_cost, 6)

    result = parse_response(response_text)
    if result.get("verdict"):
        save_result(pr, result, letter, timestamp)
    else:
        raw_file = OUTPUT_DIR / f"raw_{pr.get('project')}_{pr.get('pr_number')}_prompt{letter}_{timestamp}.txt"
        raw_file.write_text(response_text, encoding="utf-8")
        print(f"    [!] JSON parse failed. Raw saved: {raw_file.name}")
        # Write a sentinel record so get_completed() marks this PR done and won't retry.
        with open(output_jsonl(letter), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "pr_number":   pr.get("pr_number"),
                "project":     pr.get("project"),
                "datasets":    pr.get("_datasets", ["rq3"]),
                "timestamp":   timestamp,
                "parse_failed": True,
                "verdict":     "",
            }) + "\n")

    with open(token_log(letter), "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "model":            MODEL,
            "prompt":           letter,
            "project":          pr.get("project"),
            "pr_number":        pr.get("pr_number"),
            "datasets":         pr.get("_datasets", ["rq3"]),
            "timestamp":        timestamp,
            "duration_seconds": duration,
            "tokens": {
                "input_tokens":  input_tokens,
                "output_tokens": output_tokens,
                "total_tokens":  input_tokens + output_tokens,
            },
            "cost_usd": {
                "input_cost":  input_cost,
                "output_cost": output_cost,
                "total_cost":  total_cost,
            },
        }) + "\n")
    print(f"    tokens: in={input_tokens} out={output_tokens} cost=${total_cost} time={duration}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <budget_usd> [rq3|rq1]")
        sys.exit(1)

    budget  = float(sys.argv[1])
    dataset = sys.argv[2] if len(sys.argv) > 2 else "rq3"

    if dataset not in ("rq3", "rq1"):
        print(f"[!] Unknown dataset: {dataset!r}. Use 'rq3' or 'rq1'.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[*] Preprocessing ...")
    rq1_keys = build_rq1_keys()
    rq3_keys = build_rq3_keys()
    ensure_data_available(dataset, rq1_keys, rq3_keys)
    prs      = load_prs_for_dataset(dataset, rq1_keys, rq3_keys)

    overlap     = sum(1 for pr in prs if set(pr["_datasets"]) == {"rq3", "rq1"})
    rq3_only    = sum(1 for pr in prs if pr["_datasets"] == ["rq3"])
    rq1_only    = sum(1 for pr in prs if pr["_datasets"] == ["rq1"])

    print(f"    PRs to process : {len(prs)}")
    if overlap:
        print(f"      {overlap} tagged [rq3, rq1] — counted in both evaluations")
    if rq3_only:
        print(f"      {rq3_only} tagged [rq3] only")
    if rq1_only:
        print(f"      {rq1_only} tagged [rq1] only")
    print(f"[*] Budget: ${budget:.4f}")

    prompts = {letter: load_prompt(letter) for letter in PROMPTS}
    client  = anthropic.Anthropic()

    while True:
        spent     = get_total_spent()
        remaining = round(budget - spent, 6)
        print(f"\n[budget] spent=${spent:.4f}  remaining=${remaining:.4f}")

        if spent >= budget:
            print("[*] Budget exhausted. Stopping.")
            break

        partial, untouched = get_pending(prs)
        if not partial and not untouched:
            print("[*] All PRs processed. Stopping.")
            break

        if partial:
            pr     = random.choice(partial)
            status = "Completing partial"
        else:
            pr     = random.choice(untouched)
            status = "Selected new"

        project  = pr.get("project")
        pr_nb    = pr.get("pr_number")
        title    = pr.get("title", "")[:60]
        datasets = pr.get("_datasets", [])
        print(f"[*] {status}: {project}/{pr_nb} {datasets} — {title!r}")

        completed = {p: get_completed(p) for p in PROMPTS}
        for letter in PROMPTS:
            if pr_key(pr) in completed[letter]:
                print(f"    prompt {letter}: already done, skipping.")
                continue

            spent = get_total_spent()
            if spent >= budget:
                print("[*] Budget exhausted. Stopping.")
                return

            print(f"    prompt {letter}: running ...")
            run_pr(pr, letter, prompts[letter], client)

    final_spent = get_total_spent()
    print(f"\n[*] Run complete. Total spent: ${final_spent:.4f}")


if __name__ == "__main__":
    main()
