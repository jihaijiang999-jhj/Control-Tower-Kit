"""PILOT-068 probe: ``merge-envelopes/**`` inside the tower is state-only.

Every scenario is a throw-away repository with a tower root in ``tower-dsh/`` and
a bare local "origin"; the base-only paths come from the same
``tower_cli.base_ahead_paths``/``classify_base_paths`` the merge gate uses, so the
printed classification is real git output rather than a written expectation.
No network, token or real GitHub repository is involved.

    python scratch/whitelist_probe.py
"""
from __future__ import annotations

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

STATE_PATH = "tower-dsh/ledger/BASE-SYNC-PROBE.json"
ENVELOPE_PATH = "tower-dsh/merge-envelopes/ENV-PILOT-068.json"
ROOT_ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-068.json"
TOOLS_PATH = "tower-dsh/tools/tower_cli.py"
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


def advance_base(repo: Path, paths: list[str]) -> None:
    """Commit ``paths`` on a throw-away branch and publish it as origin/main."""
    run(repo, "checkout", "-b", "base-ahead")
    for path in paths:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("probe\n", encoding="utf-8")
    run(repo, "add", "--", *paths)
    run(repo, "commit", "-m", f"base advance: {', '.join(paths)}")
    run(repo, "push", "origin", "base-ahead:main")
    run(repo, "checkout", "main")


def scenario(paths: list[str]) -> dict:
    """One fresh repository: no advance, or one base-only commit at ``paths``."""
    tmp = Path(tempfile.mkdtemp(prefix="pilot-068-whitelist-"))
    try:
        repo, _origin = build_repo(tmp)
        root = repo / "tower-dsh"
        if paths:
            advance_base(repo, paths)
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
    report = {
        "state_only_prefixes": list(tower_cli.STATE_ONLY_PREFIXES),
        "unchanged_base": scenario([]),
        "envelope_and_state_base": scenario([STATE_PATH, ENVELOPE_PATH]),
        "envelope_only_base": scenario([ENVELOPE_PATH]),
        "tools_plus_envelope_base": scenario([TOOLS_PATH, ENVELOPE_PATH]),
        "root_envelope_outside_tower": scenario([ROOT_ENVELOPE_PATH]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
