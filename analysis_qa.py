#!/usr/bin/env python3
"""Structural QA over the per-paper directories under analysis/.

Each *analysis* is a single function that takes a paper directory (Path) and
returns a Result (pass/fail + summary + detail lines). Analyses self-register
via the @analysis decorator, so adding a new structural check is just writing
one function below.

Run `python analysis_qa.py`. stdout shows a SUMMARY only; full results are
written into the (gitignored) metaanalysis/ directory:
    metaanalysis/report.json     full per-paper results
    metaanalysis/failures.json   failing analyses only
    metaanalysis/matrix.txt      paper x analysis pass/fail grid
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYSIS_DIR = HERE / "analysis"      # holds the per-paper directories
OUT_DIR = HERE / "metaanalysis"       # where results are written (gitignored)

# Root-level dir entries under analysis/ that are NOT paper directories.
SKIP_DIRS = {"__pycache__"}


@dataclass
class Result:
    passed: bool
    summary: str                       # one line describing the outcome
    details: list[str] = field(default_factory=list)
    excluded: str | None = None        # reason, if a failure was excluded

    def to_dict(self) -> dict:
        return {"passed": self.passed, "summary": self.summary,
                "details": self.details, "excluded": self.excluded}


def ok(summary: str, details: list[str] | None = None) -> Result:
    """Build a passing Result."""
    return Result(True, summary, details or [])


def fail(summary: str, details: list[str] | None = None) -> Result:
    """Build a failing Result."""
    return Result(False, summary, details or [])


# ---------------------------------------------------------------------------
# Analysis registry
# ---------------------------------------------------------------------------
# The set of analyses we run is whatever is in this list. You never edit it by
# hand: every function decorated with @analysis(...) below appends itself here
# (in source order) when this module is imported. So to add a check, write a
# new @analysis-decorated function; to disable one, remove/comment its
# decorator. Undecorated functions (ok, fail, run, ...) are NOT analyses.
ANALYSES: list = []          # list of (name, description, func)


def analysis(name: str, description: str):
    """Decorator: register a function as a named analysis with a description.

    Appending to ANALYSES is the registration — it runs once, at import time,
    when Python evaluates the @analysis(...) line above each check. The
    description states what the check requires, so a reader of the report (or
    this file) knows the intent without reading the function body.
    """
    def wrap(func):
        ANALYSES.append((name, description, func))   # <-- registers the check
        return func
    return wrap


# Global checks run ONCE over the whole set of paper dirs (not per paper), for
# table-level assertions like "no orphan rows". Same auto-register pattern: a
# @global_analysis-decorated function takes the set of paper-dir names and
# returns one Result.
GLOBAL_ANALYSES: list = []    # list of (name, description, func)


def global_analysis(name: str, description: str):
    """Decorator: register a whole-corpus check (runs once, gets all dir names)."""
    def wrap(func):
        GLOBAL_ANALYSES.append((name, description, func))
        return func
    return wrap


# Sanctioned exceptions: papers allowed to fail a given analysis, with a reason.
# An excluded failure is reported as passing (so it does not fail the run), but
# the reason is recorded in the report. Keep this list short and justified.
#
#   EXCLUSIONS = {
#       "dir_name_convention": {
#           "10.1145-3744916.3773260": "legacy bare-DOI dir for IntentFix",
#       },
#   }
EXCLUSIONS: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Analyses  --  each takes the paper directory Path and returns ok/fail.
# Constants an analysis depends on live inside that analysis.
# ---------------------------------------------------------------------------

@analysis("required_files",
          "The canonical paper.json/paper.pdf plus the prompts/, outputs/, and "
          "results/ A/B artifacts all exist.")
def check_required_files(d: Path) -> Result:
    """Every paper dir must contain the canonical files (relative paths)."""
    REQUIRED = [
        "paper.json",
        "paper.pdf",
        "prompts/meta_prompt.txt",
        "prompts/prompt_A.txt",
        "prompts/prompt_B.txt",
        "outputs/outputs_A.jsonl",
        "outputs/outputs_B.jsonl",
        "results/results_A.jsonl",
        "results/results_B.jsonl",
    ]
    missing = [rel for rel in REQUIRED if not (d / rel).is_file()]
    if missing:
        return fail(f"missing {len(missing)}/{len(REQUIRED)} file(s)",
                    [f"missing: {m}" for m in missing])
    return ok(f"all {len(REQUIRED)} present")


@analysis("no_extra_files",
          "prompts/, outputs/, and results/ contain ONLY the canonical A/B "
          "files — no stray variants, caches, or token dumps.")
def check_no_extra_files(d: Path) -> Result:
    """prompts/, outputs/, results/ must contain ONLY the canonical files."""
    ALLOWED = {
        "prompts": {"meta_prompt.txt", "prompt_A.txt", "prompt_B.txt"},
        "outputs": {"outputs_A.jsonl", "outputs_B.jsonl"},
        "results": {"results_A.jsonl", "results_B.jsonl"},
    }
    IGNORE = {"__pycache__"}  # transient build output, not artifact content
    extras = []
    for sub, allowed in ALLOWED.items():
        subdir = d / sub
        if not subdir.is_dir():
            continue  # absence is required_files' concern, not this check's
        for entry in sorted(subdir.iterdir()):
            if entry.name in IGNORE or entry.suffix == ".pyc":
                continue
            if entry.name not in allowed:
                extras.append(f"{sub}/{entry.name}")
    if extras:
        return fail(f"{len(extras)} unexpected file(s)",
                    [f"extra: {e}" for e in extras])
    return ok("no extra files")


@analysis("no_forbidden_dirs",
          "No build/environment directories (__pycache__, venv, .venv) are "
          "committed to git. They are fine locally; they just must not ship.")
def check_no_forbidden_dirs(d: Path) -> Result:
    """Reject build/env directories that are tracked by git (i.e. committed).

    Asks `git ls-files` rather than walking the filesystem, so a gitignored
    local .venv/__pycache__ passes; only tracked copies fail. Reports the
    forbidden directory itself, once, not the files inside it.
    """
    import subprocess
    FORBIDDEN = {"__pycache__", "venv", ".venv"}
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=d, check=True,
                             capture_output=True, text=True).stdout
    except Exception as e:
        return fail("git ls-files failed", [repr(e)])

    hits = set()
    for path in filter(None, out.split("\0")):
        parts = path.split("/")
        for i, seg in enumerate(parts):
            if seg in FORBIDDEN:
                hits.add("/".join(parts[:i + 1]))  # the dir, not the file
                break
    if hits:
        return fail(f"{len(hits)} committed forbidden dir(s)",
                    [f"dir: {h}" for h in sorted(hits)])
    return ok("none committed")


@analysis("dir_name_convention",
          "The directory name follows the ICSE_<num>(<doi>) convention.")
def check_dir_name(d: Path) -> Result:
    """Directory name must follow ICSE_<num>(<doi>), e.g. ICSE_6(10.1145-...)."""
    import re
    PATTERN = re.compile(r"^ICSE_\d+\(10\.1145-\d+\.\d+\)$")
    if PATTERN.match(d.name):
        return ok("matches ICSE_<num>(<doi>)")
    return fail("does not match ICSE_<num>(<doi>)", [f"name: {d.name}"])


@analysis("doi_consistent",
          "The canonical DOI (the 10.1145/... slash form) is consistent across "
          "the directory name (dashes->slashes), the paper.json doi field, and "
          "the PDF text. A https://doi.org/... URL form in paper.json is flagged.")
def check_doi_consistent(d: Path) -> Result:
    """Check the directory name, paper.json, and paper.pdf agree on the DOI.

    The directory name carries the DOI in dash form; turning its dashes into
    slashes yields the canonical form. paper.json's doi field must equal that
    canonical form exactly (so a URL-wrapped DOI is flagged), and the canonical
    DOI must appear in the PDF text.
    """
    import re

    m = re.search(r"10\.1145-[0-9.]+", d.name)
    if not m:
        return fail("no DOI in directory name", [f"name: {d.name}"])
    canonical = m.group().replace("-", "/")   # dir DOI -> canonical slash form

    problems = []
    try:
        json_doi = json.loads((d / "paper.json").read_text())["doi"].strip()
    except Exception as e:
        problems.append(f"paper.json doi unreadable: {e!r}")
    else:
        if json_doi != canonical:
            problems.append(f"paper.json doi: {json_doi}")
    try:
        import pypdf
        pages = pypdf.PdfReader(str(d / "paper.pdf")).pages[:2]
        text = " ".join(p.extract_text() or "" for p in pages)
    except Exception as e:
        problems.append(f"PDF unreadable: {e!r}")
    else:
        if canonical not in text:
            problems.append("canonical DOI not found in PDF text")

    if problems:
        return fail("DOI not consistently canonical",
                    [f"canonical: {canonical}", *problems])
    return ok("DOI canonical & consistent across dir/json/pdf")


@analysis("in_readme_table",
          "The directory is listed (backtick-quoted) in analysis/README.md.")
def check_in_readme(d: Path) -> Result:
    """Directory must be listed (backtick-quoted) in analysis/README.md."""
    readme = ANALYSIS_DIR / "README.md"
    if not readme.is_file():
        return fail("analysis/README.md not found")
    text = readme.read_text()
    if f"`{d.name}`" in text:
        return ok("listed in README table")
    return fail("not found in README table", [f"name: {d.name}"])


@global_analysis("readme_no_orphan_entries",
                 "Every paper-dir listed in analysis/README.md's table exists "
                 "as a directory (no orphan / mistyped rows).")
def check_readme_orphans(names: set[str]) -> Result:
    """Reverse of in_readme_table: each backtick-quoted DOI entry has a dir."""
    import re
    readme = ANALYSIS_DIR / "README.md"
    if not readme.is_file():
        return fail("analysis/README.md not found")
    # Every paper dir is listed backtick-quoted; keep only the DOI-bearing ones
    # so prose code spans (e.g. `utils/build_inputs.py`) aren't mistaken for rows.
    listed = {m for m in re.findall(r"`([^`]+)`", readme.read_text())
              if "10.1145-" in m}
    orphans = sorted(listed - names)
    if orphans:
        return fail(f"{len(orphans)} table entr(y/ies) with no dir",
                    [f"orphan: {o}" for o in orphans])
    return ok("every table entry has a dir")


@analysis("paper_json_valid",
          "paper.json exists and is parseable JSON.")
def check_paper_json(d: Path) -> Result:
    """paper.json must exist and be valid JSON."""
    p = d / "paper.json"
    if not p.is_file():
        return fail("no paper.json")
    try:
        json.loads(p.read_text())
    except Exception as e:
        return fail("invalid JSON", [str(e)])
    return ok("valid JSON")


@analysis("pdf_title_matches",
          "The title in paper.json appears in the text of paper.pdf's first "
          "pages — i.e. the JSON describes the PDF that ships with it.")
def check_pdf_title(d: Path) -> Result:
    """Check that paper.json's title aligns with paper.pdf's text."""
    import re
    import pypdf

    def norm(s: str) -> str:
        # Keep only letters/digits so curly vs straight quotes, colons, and
        # hyphen line-wraps in the extracted text can't defeat the match.
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    try:
        title = json.loads((d / "paper.json").read_text())["title"]
        pages = pypdf.PdfReader(str(d / "paper.pdf")).pages[:2]
        text = " ".join(p.extract_text() or "" for p in pages)
    except Exception as e:
        return fail("could not read title or PDF text", [repr(e)])

    if norm(title) in norm(text):
        return ok("title found in PDF")
    return fail("title not found in PDF", [f"json title: {title}"])


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def paper_dirs() -> list[Path]:
    """Return the per-paper directories under ANALYSIS_DIR (sorted)."""
    return [p for p in sorted(ANALYSIS_DIR.iterdir())
            if p.is_dir() and p.name not in SKIP_DIRS]


def run(dirs: list[Path]) -> dict[str, dict[str, Result]]:
    """Run every analysis on every paper dir, applying exclusions.

    Returns a nested mapping: paper name -> analysis name -> Result.
    """
    report = {}
    for d in dirs:
        report[d.name] = {}
        for name, _desc, func in ANALYSES:
            try:
                res = func(d)
            except Exception as e:  # an analysis bug shouldn't kill the run
                res = fail("analysis error", [repr(e)])
            # apply a sanctioned exclusion: a failure becomes a recorded pass
            if not res.passed:
                reason = EXCLUSIONS.get(name, {}).get(d.name)
                if reason:
                    res = Result(True, res.summary, res.details, excluded=reason)
            report[d.name][name] = res
    return report


def run_global(names: set[str]) -> dict[str, Result]:
    """Run every whole-corpus check once. Returns analysis name -> Result."""
    out = {}
    for name, _desc, func in GLOBAL_ANALYSES:
        try:
            out[name] = func(names)
        except Exception as e:
            out[name] = fail("analysis error", [repr(e)])
    return out


def paper_path(name: str) -> str:
    """Absolute path to a paper dir, so the report links straight to it."""
    return str(ANALYSIS_DIR / name)


def to_json(report: dict[str, dict[str, Result]],
            global_results: dict[str, Result]) -> dict:
    """Serialize the report, prefixed with each analysis's description."""
    return {
        "analyses": {name: desc for name, desc, _ in ANALYSES},
        "global_analyses": {name: desc for name, desc, _ in GLOBAL_ANALYSES},
        "papers": {
            paper: {"path": paper_path(paper),
                    "checks": {name: r.to_dict() for name, r in results.items()}}
            for paper, results in report.items()
        },
        "global": {name: r.to_dict() for name, r in global_results.items()},
    }


def failures_only(report: dict[str, dict[str, Result]],
                  global_results: dict[str, Result]) -> dict:
    """Same shape as the full report, but only failing analyses / papers."""
    out = {}
    for paper, results in report.items():
        fails = {name: r.to_dict() for name, r in results.items()
                 if not r.passed}
        if fails:
            out[paper] = {"path": paper_path(paper), "checks": fails}
    global_fails = {name: r.to_dict() for name, r in global_results.items()
                    if not r.passed}
    if global_fails:
        out["__global__"] = {"checks": global_fails}
    return out


def matrix_text(report: dict[str, dict[str, Result]]) -> str:
    """Render a paper x analysis pass/fail grid."""
    names = [n for n, _, _ in ANALYSES]
    dirw = max((len(p) for p in report), default=0)
    lines = []
    header = " " * dirw + "  " + "  ".join(f"{n:>{max(len(n), 4)}}" for n in names)
    lines.append(header)
    lines.append("-" * len(header))
    for paper, results in report.items():
        cells = []
        for n in names:
            r = results[n]
            glyph = "E" if r.excluded else ("✓" if r.passed else "✗")
            cells.append(f"{glyph:>{max(len(n), 4)}}")
        lines.append(f"{paper:<{dirw}}  " + "  ".join(cells))
    return "\n".join(lines) + "\n"


def print_summary(report, out_dir: Path,
                  global_results: dict[str, Result]) -> int:
    """Print the stdout summary; return an exit code (1 if any check failed)."""
    n_papers = len(report)
    n_analyses = len(ANALYSES)
    all_results = [r for results in report.values() for r in results.values()]
    n_pass = sum(r.passed for r in all_results)
    n_fail = n_papers * n_analyses - n_pass
    n_excluded = sum(r.excluded is not None for r in all_results)
    n_global_fail = sum(not r.passed for r in global_results.values())
    n_papers_failing = sum(any(not r.passed for r in results.values())
                           for results in report.values())

    print("ANALYSIS QA SUMMARY")
    print(f"  papers:    {n_papers}")
    print(f"  analyses:  {n_analyses}")
    print(f"  checks:    {n_papers * n_analyses}  "
          f"(PASS={n_pass}  FAIL={n_fail}  EXCLUDED={n_excluded})")
    print(f"  papers with failures: {n_papers_failing}")

    print("  by analysis:")
    namew = max((len(n) for n, _, _ in ANALYSES + GLOBAL_ANALYSES), default=0)
    for name, _desc, _ in ANALYSES:
        p = sum(report[paper][name].passed for paper in report)
        e = sum(report[paper][name].excluded is not None for paper in report)
        flag = "" if p == n_papers else "  <-- failing"
        enote = f"  ({e} excluded)" if e else ""
        print(f"    {name:<{namew}}  {p}/{n_papers}{flag}{enote}")

    if global_results:
        print("  global checks:")
        for name, r in global_results.items():
            status = "ok" if r.passed else "FAIL"
            print(f"    {name:<{namew}}  {status}  {r.summary}")

    print(f"\n  results -> {out_dir}/")
    for f in ("report.json", "failures.json", "matrix.txt"):
        print(f"    {f}")
    return 1 if (n_fail or n_global_fail) else 0


def main():
    """Run all analyses, write the metaanalysis/ outputs, print the summary."""
    dirs = paper_dirs()
    if not dirs:
        print(f"no paper directories under {ANALYSIS_DIR}", file=sys.stderr)
        return 2

    report = run(dirs)
    global_results = run_global({d.name for d in dirs})
    failures = failures_only(report, global_results)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.json").write_text(
        json.dumps(to_json(report, global_results), indent=2) + "\n")
    (OUT_DIR / "failures.json").write_text(json.dumps(failures, indent=2) + "\n")
    (OUT_DIR / "matrix.txt").write_text(matrix_text(report))

    return print_summary(report, OUT_DIR, global_results)


if __name__ == "__main__":
    sys.exit(main())
