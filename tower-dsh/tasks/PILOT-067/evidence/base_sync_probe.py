"""PILOT-067 probe: base-sync detection, classification and gh argv, offline.

Runs the same functions the merge gate uses against a throw-away repository and
a bare local "origin", so the printed result is real git output rather than a
hand-written expectation.  No network, token or real GitHub repository is
involved.

    python scratch/base_sync_probe.py
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
CODE_PATH = "tower-dsh/tools/base_sync_probe.py"
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


def build_repo(tmp: Path) -> tuple[Path, Path]:
    """A repo whose tower root is ``tower-dsh/``, plus a bare origin on main."""
    repo, origin = tmp / "repo", tmp / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                   capture_output=True)
    repo.mkdir()
    run(repo, "init")
    run(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "tower-dsh").mkdir()
    run(repo, "add", "-A")
    run(repo, "commit", "-m", "base")
    run(repo, "remote", "add", "origin", str(origin).replace("\\", "/"))
    run(repo, "push", "origin", "main")
    return repo, origin


def advance_base(repo: Path, path: str) -> None:
    """Commit ``path`` on a throw-away branch and publish it as origin/main."""
    run(repo, "checkout", "-b", "base-ahead")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("probe\n", encoding="utf-8")
    run(repo, "add", "--", path)
    run(repo, "commit", "-m", f"base advance: {path}")
    run(repo, "push", "origin", "base-ahead:main")
    run(repo, "checkout", "main")


def scenario(path: str | None) -> dict:
    """One fresh repository: no advance, or one base-only commit at ``path``."""
    tmp = Path(tempfile.mkdtemp(prefix="pilot-067-base-sync-"))
    try:
        repo, _origin = build_repo(tmp)
        root = repo / "tower-dsh"
        if path:
            advance_base(repo, path)
        ahead = tower_cli.base_ahead_paths(repo, "main", "origin")
        state, code = tower_cli.classify_base_paths(
            ahead, tower_cli.tower_repo_prefix(root, repo))
        return {"base_ahead_paths": ahead, "state_only": state,
                "code_docs": code,
                "verdict": ("code-docs: refuse (rebase + re-review)"
                            if code else
                            "state-only: --allow-state-ahead required" if state
                            else "no base advance: normal merge")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    audited = argparse.Namespace(base_sync_audit={
        "base_sync": "state-only", "base_ahead_paths": [STATE_PATH],
        "admin": True})
    report = {
        "unchanged_base": scenario(None),
        "state_only_base": scenario(STATE_PATH),
        "code_base": scenario(CODE_PATH),
        "pr_merge_argv": {
            "without_audit": tower_merge.pr_merge_argv(42, "a" * 40,
                                                       argparse.Namespace()),
            "with_audit": tower_merge.pr_merge_argv(42, "a" * 40, audited),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
