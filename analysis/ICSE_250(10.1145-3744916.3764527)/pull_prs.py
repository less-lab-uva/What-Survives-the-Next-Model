"""
Pull PR inputs from GitHub and save them to ../data/pulled_prs/ground_truth/.

Pulls two groups:
  1. RQ3 PRs — the 46 PRs with human-verified ground truth labels used to
               evaluate classification accuracy (RQ3).
  2. RQ1-only PRs — 10 additional PRs from real-world_problems.csv that have
               no ground truth labels but are needed for RQ1 detection-rate
               evaluation.

Output per PR: ../data/pulled_prs/ground_truth/{project}/{pr_number}.json
  Fields: pr_number, title, description, diff, commit_messages,
          discussion_comments, html_url, pre_commit, post_commit

Usage:
    python3 pull_prs.py

Requires:
    .github_token  — file in this directory containing a GitHub personal
                     access token (classic, with public_repo scope)
    PyGithub       — pip install PyGithub
"""

import json
import os
import time
import urllib.request
from pathlib import Path
from github import Github, Auth

BASE_DIR          = Path(__file__).parent
GITHUB_TOKEN_FILE = BASE_DIR / ".github_token"
GT_OUTPUT_DIR     = BASE_DIR / ".." / "data" / "pulled_prs" / "ground_truth"

# ---------------------------------------------------------------------------
# PRs to pull
# RQ3 PRs: 46 PRs with human-verified differentiating-test labels
# RQ1-only PRs: 10 additional real-world-problem PRs not in ground_truth/
# ---------------------------------------------------------------------------
GROUND_TRUTH_PRS = {
    "keras": (
        "keras-team/keras",
        [19814],
    ),
    "marshmallow": (
        "marshmallow-code/marshmallow",
        [
            # RQ3:
            1399, 1989, 1998, 2017, 2022, 2044, 2102, 2123, 2215, 2244, 2246, 2271,
            # RQ1-only:
            2698, 2699, 2700, 2701,
        ],
    ),
    "pandas": (
        "pandas-dev/pandas",
        [
            # RQ3:
            55108, 57034, 57046, 57205, 57399, 58376,
            59759, 59782, 59809, 59810, 59843, 59907,
            # RQ1-only:
            56841, 57595, 60461, 60483, 60538,
        ],
    ),
    "scipy": (
        "scipy/scipy",
        [
            # RQ3:
            19263, 19428, 19680, 19776, 19853, 19861,
            20089, 20751, 20974, 21036, 21076, 21518,
            21528, 21553, 21572, 21577, 21597, 21604,
            21629, 21633, 21642,
            # RQ1-only:
            21768,
        ],
    ),
}


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def fetch_diff(pr_html_url: str) -> str:
    try:
        diff_url = pr_html_url + ".diff"
        with urllib.request.urlopen(diff_url) as response:
            enc = (response.headers.get_charsets() or ["utf-8"])[0]
            return response.read().decode(enc, errors="replace")
    except Exception as e:
        return f"ERROR fetching diff: {e}"


def fetch_pr_data(github_repo, pr_nb: int) -> dict | None:
    pr = github_repo.get_pull(pr_nb)
    if not pr.is_merged():
        return None

    post_commit = pr.merge_commit_sha
    parents     = github_repo.get_commit(post_commit).parents
    pre_commit  = parents[0].sha if parents else None

    commit_messages = [c.commit.message for c in pr.get_commits() if c.commit.message]

    discussion_comments = (
        [c.body for c in pr.get_issue_comments()  if c.body] +
        [c.body for c in pr.get_review_comments() if c.body]
    )

    return {
        "pr_number":           pr_nb,
        "title":               pr.title or "",
        "description":         pr.body  or "",
        "diff":                fetch_diff(pr.html_url),
        "commit_messages":     commit_messages,
        "discussion_comments": discussion_comments,
        "html_url":            pr.html_url,
        "pre_commit":          pre_commit,
        "post_commit":         post_commit,
    }


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

def pull_all(github) -> None:
    total_rq3     = sum(len(nbs) for _, nbs in GROUND_TRUTH_PRS.values())
    print(f"\n=== Pulling {total_rq3} PRs (RQ3 + RQ1-only) ===")

    for project_name, (repo_id, pr_numbers) in GROUND_TRUTH_PRS.items():
        out_dir = GT_OUTPUT_DIR / project_name
        out_dir.mkdir(parents=True, exist_ok=True)
        github_repo = github.get_repo(repo_id)
        print(f"\n  {project_name} ({len(pr_numbers)} PRs)")

        for pr_nb in pr_numbers:
            out_path = out_dir / f"{pr_nb}.json"
            if out_path.exists():
                print(f"    PR {pr_nb}: already saved, skipping")
                continue
            try:
                data = fetch_pr_data(github_repo, pr_nb)
            except Exception as e:
                print(f"    PR {pr_nb}: error — {e}")
                time.sleep(1)
                continue
            if data is None:
                print(f"    PR {pr_nb}: not merged, skipping")
                continue
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"    PR {pr_nb}: saved")

    print(f"\nDone. PR data saved to: {GT_OUTPUT_DIR}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not GITHUB_TOKEN_FILE.exists():
        print(f"ERROR: {GITHUB_TOKEN_FILE} not found.")
        print("Create it with your GitHub personal access token (public_repo scope).")
        return

    token  = GITHUB_TOKEN_FILE.read_text().strip()
    github = Github(auth=Auth.Token(token))

    GT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pull_all(github)


if __name__ == "__main__":
    main()
