"""PILOT-064 probe: base-side envelope against the real tower-subdir layout.

The tower is a subdirectory of the repository (``tower-dsh/``), so the envelope
file lives at ``tower-dsh/merge-envelopes/<ENV>.json`` while the envelope
declares ``envelope_path`` relative to the tower root
(``merge-envelopes/<ENV>.json``).  ``envelope_git_checks`` compares that path to
``git diff --name-only``, which is repo-root relative, so the tower prefix must
come from the tower root — not from the repository root.

This script builds throw-away repositories (no network, no tower state) and
prints the git-shape verdict for four layouts:

  A subdir      base-side envelope committed under ``tower-dsh/``  -> all ok
  B subdir+leak the same commit also touches another file          -> refused
  C flat        repo root == tower root, envelope at root          -> all ok
  D legacy      branch-side envelope (pre-063)                     -> all ok

Run from the worktree root::

    python -B scratch/base_side_probe.py
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS = WORKTREE / "tower-dsh" / "tools"
sys.path.insert(0, str(TOOLS))

import tower_envelope  # noqa: E402  (tools/ on sys.path first)

BRANCH = "pilot/PILOT-064"
BASE = "main"
ENVELOPE = "ENV-PILOT-064"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"

IDENTITY = {
    "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@local",
    "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@local",
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def commit(repo: Path, message: str) -> str:
    cp = git(repo, "-c", "commit.gpgsign=false", "commit", "-m", message)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_repo(tmp: Path, subdir: bool) -> dict:
    """main + implementation branch; the envelope commit is added separately."""
    kit = tmp / "kit"
    kit.mkdir(parents=True)
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    write(kit / "README.md", "base\n")
    git(kit, "add", "README.md")
    base_sha = commit(kit, "base")
    git(kit, "checkout", "-b", BRANCH)
    write(kit / "feature.txt", "implementation\n")
    git(kit, "add", "feature.txt")
    impl = commit(kit, "implementation")
    git(kit, "checkout", BASE)
    root = kit / "tower-dsh" if subdir else kit
    root.mkdir(exist_ok=True)
    return {"kit": kit, "root": root, "base_sha": base_sha, "impl": impl}


def repo_of(root: Path) -> Path:
    return (root / "..").resolve() if root.name == "tower-dsh" else root


def envelope_env(root: Path, impl: str, *, base_side: bool,
                 declared_head: str = "") -> dict:
    repository = ".." if root.name == "tower-dsh" else "."
    env = {"envelope_id": ENVELOPE, "task": "PILOT-064",
           "repository": repository, "branch": BRANCH, "base": BASE,
           "implementation_head_sha": impl, "envelope_path": ENVELOPE_PATH}
    if base_side:
        env["base_side"] = True
    if declared_head:
        env["envelope_head_sha"] = declared_head
    return env


def envelope_commit(root: Path, *extra: str, in_tower: bool) -> str:
    rel = f"tower-dsh/{ENVELOPE_PATH}" if in_tower else ENVELOPE_PATH
    write(root.parent / rel if in_tower else root / rel,
          json.dumps({"envelope_id": ENVELOPE}) + "\n")
    paths = [rel, *extra]
    git(root.parent if in_tower else root, "add", "--", *paths)
    return commit(root.parent if in_tower else root, "envelope")


def git_checks(root: Path, env: dict) -> tuple[str, list[dict]]:
    repo = repo_of(root)
    params = inspect.signature(tower_envelope.envelope_git_checks).parameters
    extra = {"tower_root": root} if "tower_root" in params else {}
    return tower_envelope.envelope_git_checks(repo, env, **extra)


def prefixes(root: Path) -> tuple[str, str]:
    repo = repo_of(root)
    return (git(repo, "rev-parse", "--show-prefix").stdout.strip(),
            git(root, "rev-parse", "--show-prefix").stdout.strip())


def show(case: str, expect_ok: bool, root: Path, env: dict) -> bool:
    head, checks = git_checks(root, env)
    ok = all(check["ok"] for check in checks)
    print(f"\n[{case}] head={head[:10]} expected={'ok' if expect_ok else 'refused'} "
          f"verdict={'ok' if ok else 'refused'} "
          f"{'PASS' if ok == expect_ok else 'FAIL'}")
    print(f"  repo_prefix={prefixes(root)[0]!r} tower_prefix={prefixes(root)[1]!r} "
          f"repo_path={prefixes(root)[1] + ENVELOPE_PATH}")
    for check in checks:
        print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
    return ok == expect_ok


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="pilot064-probe-") as tmp:
        tmp = Path(tmp)

        # A: the real layout — repo has tower-dsh/, envelope under the tower.
        repo = build_repo(tmp / "a", subdir=True)
        head = envelope_commit(repo["root"], in_tower=True)
        failures += not show("A subdir base-side", True, repo["root"],
                             envelope_env(repo["root"], repo["impl"], base_side=True))

        # B: the same base commit also carries a non-envelope file -> refused.
        repo = build_repo(tmp / "b", subdir=True)
        write(repo["kit"] / "leak.txt", "leak\n")
        envelope_commit(repo["root"], "leak.txt", in_tower=True)
        failures += not show("B subdir + leak", False, repo["root"],
                             envelope_env(repo["root"], repo["impl"], base_side=True))

        # C: a flat repository (repo root == tower root) stays supported.
        repo = build_repo(tmp / "c", subdir=False)
        envelope_commit(repo["root"], in_tower=False)
        failures += not show("C flat base-side", True, repo["root"],
                             envelope_env(repo["root"], repo["impl"], base_side=True))

        # D: branch-side legacy (pre-063) — envelope commit on the branch.
        repo = build_repo(tmp / "d", subdir=False)
        git(repo["kit"], "checkout", BRANCH)
        head = envelope_commit(repo["root"], in_tower=False)
        failures += not show("D legacy branch-side", True, repo["root"],
                             envelope_env(repo["root"], repo["impl"],
                                          base_side=False, declared_head=head))

    print(f"\nprobe {'PASS' if not failures else 'FAIL'} "
          f"({4 - failures}/4 layouts as expected)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
