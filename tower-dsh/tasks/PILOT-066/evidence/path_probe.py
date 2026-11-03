"""PILOT-066 probe: the post-merge envelope path for base-side envelopes.

A base-side envelope is committed on the base branch *inside* the tower root,
so in the repository it lives at ``tower-dsh/merge-envelopes/<ENV>.json``.
PILOT-065 only passed post-merge because a duplicate copy (a shim) had been
committed at the repository root.  This probe compares the two rules:

  * new rule (066): ``base_side`` envelopes resolve to
    ``<git --show-prefix>/<envelope_path>`` -- the tower-root path;
  * old rule (065): every envelope was probed at the repository root.

It also reads the real ``ENV-PILOT-065`` record and shows that its file is
present under the tower root on base, independent of the repository-root shim.

Read-only against the real tower; throw-away repositories for the rest.

Run from the worktree root::

    python -B scratch/path_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
TOOLS = TOWER / "tools"
sys.path.insert(0, str(TOOLS))

import tower_post_merge  # noqa: E402  (tools/ on sys.path first)

ENVELOPE = "ENV-PILOT-066-PROBE"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BASE = "main"
BRANCH = "pilot/PILOT-066"

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


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str, *paths: str) -> str:
    git(repo, "add", "--", *paths)
    cp = git(repo, "-c", "commit.gpgsign=false", "commit", "-m", message)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def build_repo(tmp: Path) -> dict:
    """A throw-away repository whose tower root is ``kit/tower-dsh``."""
    kit = tmp / "kit"
    kit.mkdir(parents=True)
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    write(kit, "README.md", "base\n")
    write(kit, "tower-dsh/.keep", "tower root\n")
    base_sha = commit(kit, "base", "README.md", "tower-dsh/.keep")
    git(kit, "checkout", "-b", BRANCH)
    write(kit, "feature.txt", "implementation\n")
    impl = commit(kit, "implementation", "feature.txt")
    git(kit, "checkout", BASE)
    return {"kit": kit, "root": kit / "tower-dsh", "base_sha": base_sha,
            "impl": impl}


def env(base_side: bool = True, *, envelope_path: str = ENVELOPE_PATH,
        impl: str = "0" * 40) -> dict:
    record = {"envelope_id": ENVELOPE, "task": "PILOT-066",
              "repository": "..", "branch": BRANCH, "base": BASE,
              "implementation_head_sha": impl, "envelope_path": envelope_path}
    if base_side:
        record["base_side"] = True
    return record


def exists_at_base(repo: dict, base: str, rel: str) -> bool:
    return git(repo["kit"], "cat-file", "-e", f"{base}:{rel}").returncode == 0


def show(case: str, repo: dict, record: dict, *, expect_new: bool) -> bool:
    """Print the new/old repository paths and whether each one exists on base."""
    new_rel = tower_post_merge.envelope_repo_path(repo["root"], record)
    old_rel = record["envelope_path"]
    new_ok = exists_at_base(repo, BASE, new_rel)
    old_ok = exists_at_base(repo, BASE, old_rel)
    verdict = new_ok == expect_new
    print(f"\n[{case}] base-side={record.get('base_side') is True} "
          f"expect_new={'exists' if expect_new else 'missing'}")
    print(f"  new rule path: {BASE}:{new_rel} -> "
          f"{'EXISTS' if new_ok else 'MISSING'}")
    print(f"  old rule path: {BASE}:{old_rel} -> "
          f"{'EXISTS' if old_ok else 'MISSING'}")
    print(f"  verdict: {'PASS' if verdict else 'FAIL'}")
    return verdict


def real_065() -> bool:
    """The real 065 envelope file: on the tower-root path on base."""
    record_path = TOWER / "supervision" / "envelopes" / "ENV-PILOT-065.json"
    if not record_path.exists():
        print("\n[real 065] SKIP: envelope record not found")
        return True
    record = json.loads(record_path.read_text(encoding="utf-8"))
    new_rel = tower_post_merge.envelope_repo_path(TOWER, record)
    old_rel = record["envelope_path"]
    new_ok = exists_at_base({"kit": WORKTREE}, "main", new_rel)
    old_ok = exists_at_base({"kit": WORKTREE}, "main", old_rel)
    print(f"\n[real 065] base_side={record.get('base_side') is True}")
    print(f"  new rule path: main:{new_rel} -> "
          f"{'EXISTS' if new_ok else 'MISSING'}")
    print(f"  old rule path: main:{old_rel} -> "
          f"{'EXISTS (repo-root shim, to be deleted by the controller)' if old_ok else 'MISSING (shim already removed)'}")
    print("  post-merge now probes only the new-rule path; the shim is "
          "duplicate state, not a dependency.")
    return new_ok


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="pilot066-probe-") as tmp:
        tmp = Path(tmp)

        # A: base-side file under the tower root, no repo-root copy (065 shape).
        repo = build_repo(tmp / "a")
        write(repo["kit"], f"tower-dsh/{ENVELOPE_PATH}",
              json.dumps({"envelope_id": ENVELOPE}) + "\n")
        commit(repo["kit"], "envelope", f"tower-dsh/{ENVELOPE_PATH}")
        failures += not show("A base-side under tower root", repo,
                             env(impl=repo["impl"]), expect_new=True)

        # B: legacy branch-side file at the repository root.
        repo = build_repo(tmp / "b")
        write(repo["kit"], ENVELOPE_PATH, json.dumps({"envelope_id": ENVELOPE}) + "\n")
        commit(repo["kit"], "envelope", ENVELOPE_PATH)
        failures += not show("B legacy branch-side at repo root", repo,
                             env(False, impl=repo["impl"]), expect_new=True)

        # C: base-side record but only a repo-root copy (a shim, no tower file).
        repo = build_repo(tmp / "c")
        write(repo["kit"], ENVELOPE_PATH, json.dumps({"envelope_id": ENVELOPE}) + "\n")
        commit(repo["kit"], "shim", ENVELOPE_PATH)
        failures += not show("C base-side with only a repo-root copy", repo,
                             env(impl=repo["impl"]), expect_new=False)

        # D: base-side record and no envelope file at all.
        repo = build_repo(tmp / "d")
        failures += not show("D base-side missing everywhere", repo,
                             env(impl=repo["impl"]), expect_new=False)

        # E: the real 065 envelope file is present on its tower-root path.
        failures += not real_065()

    total = 5
    print(f"\nprobe {'PASS' if not failures else 'FAIL'} "
          f"({total - failures}/{total} as expected)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
