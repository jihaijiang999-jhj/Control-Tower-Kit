"""PILOT-069 probe: base-ahead is the merge-base..origin/main diff, offline.

Runs the same functions the merge gate uses against throw-away repositories and
a bare local "origin", so every printed path is real git output.  No network,
token or real GitHub repository is involved.

The contrast that 069 fixes is printed as ``tip_diff``: the old
``HEAD..origin/main`` spelling, which counts the branch's own commits (and
therefore the branch's own code) as "base-only".

    python scratch/base_ahead_probe.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS = WORKTREE / "tower-dsh" / "tools"
sys.path.insert(0, str(TOOLS))

import tower_cli  # noqa: E402  (TOOLS must be on sys.path first)
import tower_merge  # noqa: E402

STATE_PATH = "tower-dsh/ledger/BASE-SYNC-PROBE.json"
ENVELOPE_PATH = "tower-dsh/merge-envelopes/ENV-PILOT-069.json"
BRANCH_CODE = "tower-dsh/tools/tower_cli.py"
NEW_BASE_CODE = "tower-dsh/tools/x.py"
BRANCH = "pilot/PILOT-069"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8",
                          env={**os.environ, **IDENTITY})


def run(repo: Path, *args: str) -> str:
    cp = git(repo, *args)
    if cp.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp.stdout.strip()


def write(repo: Path, path: str, text: str = "probe\n") -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_repo(tmp: Path) -> Path:
    """A repo whose tower root is ``tower-dsh/``, plus a bare origin on main."""
    repo, origin = tmp / "repo", tmp / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                   capture_output=True)
    repo.mkdir()
    run(repo, "init")
    run(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    write(repo, "README.md", "base\n")
    (repo / "tower-dsh").mkdir()
    run(repo, "add", "-A")
    run(repo, "commit", "-m", "base")
    run(repo, "remote", "add", "origin", str(origin).replace("\\", "/"))
    run(repo, "push", "origin", "main")
    return repo


def cut_branch_with_code(repo: Path) -> None:
    """The task branch: its implementation is the branch's own ``tools/`` code."""
    run(repo, "checkout", "-b", BRANCH)
    write(repo, BRANCH_CODE, "# branch implementation\n")
    run(repo, "add", "--", BRANCH_CODE)
    run(repo, "commit", "-m", "implementation")
    run(repo, "checkout", "main")


def advance_base(repo: Path, paths: list[str]) -> None:
    """Commit ``paths`` on a throw-away branch and publish it as origin/main."""
    run(repo, "checkout", "-b", "base-ahead")
    for path in paths:
        write(repo, path)
    run(repo, "add", "--", *paths)
    run(repo, "commit", "-m", f"base advance: {', '.join(paths)}")
    run(repo, "push", "origin", "base-ahead:main")
    run(repo, "checkout", "main")


def scenario(name: str, paths: list[str] | None, checkout: str,
             local_only_commit: bool = False) -> dict:
    """One fresh repository; ``checkout`` selects the merge checkout."""
    tmp = Path(tempfile.mkdtemp(prefix="pilot-069-base-ahead-"))
    try:
        repo = build_repo(tmp)
        root = repo / "tower-dsh"
        cut_branch_with_code(repo)
        if paths:
            advance_base(repo, paths)
        run(repo, "checkout", checkout)
        if local_only_commit:
            write(repo, "local-only.txt", "unpublished\n")
            run(repo, "add", "--", "local-only.txt")
            run(repo, "commit", "-m", "local base commit (not pushed)")
        ahead = tower_cli.base_ahead_paths(repo, "main", "origin")
        state, code = tower_cli.classify_base_paths(
            ahead, tower_cli.tower_repo_prefix(root, repo))
        tip_diff = [line for line in run(
            repo, "diff", "--name-only", "HEAD..origin/main").splitlines() if line]
        return {
            "scenario": name,
            "checkout": checkout,
            "base_ahead_paths": ahead,
            "state_only": state,
            "code_docs": code,
            "branch_code_in_tip_diff": BRANCH_CODE in tip_diff,
            "tip_diff": tip_diff,
            "verdict": ("code-docs: refuse (rebase + re-review)" if code else
                        "state-only: --allow-state-ahead required" if state else
                        "no base advance: normal merge"),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    audited = argparse.Namespace(base_sync_audit={
        "base_sync": "state-only",
        "base_ahead_paths": [STATE_PATH, ENVELOPE_PATH], "admin": True})
    report = {
        "branch_code_state_base": scenario(
            "branch owns tools/tower_cli.py; base only state + envelope",
            [STATE_PATH, ENVELOPE_PATH], BRANCH),
        "base_added_tools": scenario(
            "base really adds tools/x.py",
            [NEW_BASE_CODE, STATE_PATH], "main"),
        "unchanged_base": scenario(
            "base did not advance", None, "main"),
        "local_base_ahead": scenario(
            "local main carries an unpublished commit (069's own shape)",
            None, "main", local_only_commit=True),
        "pr_merge_argv": {
            "without_audit": tower_merge.pr_merge_argv(69, "a" * 40,
                                                       argparse.Namespace()),
            "with_audit": tower_merge.pr_merge_argv(69, "a" * 40, audited),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
