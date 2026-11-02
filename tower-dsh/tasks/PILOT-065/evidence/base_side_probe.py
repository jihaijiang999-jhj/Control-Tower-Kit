"""PILOT-065 probe: base-side shape checks bind ``envelope_head_sha``.

PILOT-064 generated the base-side envelope correctly but ``envelope_checks``
still bound the shape to the *base tip*.  PR CI needs ledger/queue/task state
commits on base *after* the envelope, so the tip moves and the "envelope commit
only changes envelope path" / "envelope parent is ancestor of implementation"
checks failed.  This probe shows the 065 rule:

  * the envelope commit is ``envelope_head_sha`` (fallback ``head``, then the
    base tip for pre-065 records), never the moving base tip;
  * that commit must be an ancestor of base and change only the envelope path;
  * later state commits on base do not change the verdict;
  * branch head == implementation, review binding and the refusals stay.

It is read-only against the real tower (it loads ``ENV-PILOT-064`` and calls
``envelope_git_checks``) and builds throw-away repositories for the rest.

Run from the worktree root::

    python -B scratch/base_side_probe.py
"""
from __future__ import annotations

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

BRANCH = "pilot/PILOT-065"
BASE = "main"
ENVELOPE = "ENV-PILOT-065"
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
    """main + implementation branch; the envelope commit is added by the case."""
    kit = tmp / "kit"
    kit.mkdir(parents=True)
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    write(kit, "README.md", "base\n")
    # The tower root is a real tracked directory on every branch: the
    # ``--show-prefix`` bridge is resolved from it.
    write(kit, "tower-dsh/.keep", "tower root\n")
    base_sha = commit(kit, "base", "README.md", "tower-dsh/.keep")
    git(kit, "checkout", "-b", BRANCH)
    write(kit, "feature.txt", "implementation\n")
    impl = commit(kit, "implementation", "feature.txt")
    git(kit, "checkout", BASE)
    root = kit / "tower-dsh"
    root.mkdir(exist_ok=True)
    return {"kit": kit, "root": root, "base_sha": base_sha, "impl": impl}


def envelope_env(root: Path, impl: str, envelope_head: str) -> dict:
    return {"envelope_id": ENVELOPE, "task": "PILOT-065",
            "repository": "..", "branch": BRANCH, "base": BASE,
            "implementation_head_sha": impl, "envelope_path": ENVELOPE_PATH,
            "base_side": True, "envelope_head_sha": envelope_head}


def tower_path(root: Path) -> str:
    prefix = git(root, "rev-parse", "--show-prefix").stdout.strip().strip("/")
    return f"{prefix}/{ENVELOPE_PATH}" if prefix else ENVELOPE_PATH


def envelope_commit(repo: dict, *extra: str) -> str:
    root = repo["root"]
    rel = tower_path(root)
    write(repo["kit"], rel, json.dumps({"envelope_id": ENVELOPE}) + "\n")
    return commit(repo["kit"], "envelope", rel, *extra)


def state_commits(repo: dict) -> None:
    """Ordinary post-envelope base movement: ledger, queue and task state."""
    for rel, text, message in (
            ("tower-dsh/ledger/primary.jsonl", '{"type": "PHASE"}\n', "state: ledger"),
            ("tower-dsh/supervision/MERGE_QUEUE.json",
             '{"schema": "tower/merge-queue@1", "entries": []}\n', "state: queue"),
            ("tower-dsh/tasks/PILOT-065/record.json",
             '{"schema": "tower/task@1", "id": "PILOT-065"}\n', "state: task")):
        write(repo["kit"], rel, text)
        commit(repo["kit"], message, rel)


def show(case: str, expect_ok: bool, repo: dict, env: dict) -> bool:
    head, checks = tower_envelope.envelope_git_checks(
        repo["kit"], env, repo["root"])
    ok = all(check["ok"] for check in checks)
    print(f"\n[{case}] head={head[:10]} expected="
          f"{'ok' if expect_ok else 'refused'} "
          f"verdict={'ok' if ok else 'refused'} "
          f"{'PASS' if ok == expect_ok else 'FAIL'}")
    for check in checks:
        print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['name']}: "
              f"{check['detail']}")
    return ok == expect_ok


def real_064() -> bool:
    """The real 064 envelope, whose base tip moved 3 state commits ahead."""
    real_root = WORKTREE.parents[2]
    record = real_root / "supervision" / "envelopes" / "ENV-PILOT-064.json"
    if not record.exists():
        print("\n[real 064] SKIP: envelope record not found")
        return True
    env = json.loads(record.read_text(encoding="utf-8"))
    repo = real_root.parent
    tip = git(repo, "rev-parse", str(env.get("base") or "main")).stdout.strip()
    print(f"\n[real 064] base tip={tip[:10]} "
          f"envelope_head_sha={str(env.get('envelope_head_sha'))[:10]} "
          f"(tip moved past the envelope: {tip != env.get('envelope_head_sha')})")
    head, checks = tower_envelope.envelope_git_checks(repo, env, real_root)
    ok = all(check["ok"] for check in checks)
    for check in checks:
        print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['name']}: "
              f"{check['detail']}")
    return ok


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="pilot065-probe-") as tmp:
        tmp = Path(tmp)

        # A: the fixed rule — state commits after the envelope keep it green.
        repo = build_repo(tmp / "a")
        eh = envelope_commit(repo)
        state_commits(repo)
        tip = git(repo["kit"], "rev-parse", BASE).stdout.strip()
        print(f"\n[A] base tip={tip[:10]} envelope={eh[:10]} "
              f"(state moved base past the envelope: {tip != eh})")
        failures += not show("A state after envelope", True, repo,
                             envelope_env(repo["root"], repo["impl"], eh))

        # B: the pre-065 bug — binding the shape to the base tip refuses.
        failures += not show("B base-tip binding (old bug)", False, repo,
                             envelope_env(repo["root"], repo["impl"], tip))

        # C: the declared envelope commit is not an ancestor of base.
        repo = build_repo(tmp / "c")
        git(repo["kit"], "checkout", "-b", "envelope-side")
        outside = envelope_commit(repo)
        git(repo["kit"], "checkout", BASE)
        failures += not show("C envelope not in base", False, repo,
                             envelope_env(repo["root"], repo["impl"], outside))

        # D: the envelope commit carries a non-envelope file.
        repo = build_repo(tmp / "d")
        write(repo["kit"], "leak.txt", "leak\n")
        leaky = envelope_commit(repo, "leak.txt")
        failures += not show("D envelope + extra file", False, repo,
                             envelope_env(repo["root"], repo["impl"], leaky))

        # E: branch head != implementation is still refused.
        repo = build_repo(tmp / "e")
        eh = envelope_commit(repo)
        git(repo["kit"], "checkout", BRANCH)
        write(repo["kit"], "feature.txt", "moved\n")
        commit(repo["kit"], "extra implementation", "feature.txt")
        git(repo["kit"], "checkout", BASE)
        failures += not show("E branch head moved", False, repo,
                             envelope_env(repo["root"], repo["impl"], eh))

        # The real 064 envelope now passes its git shape with the moved tip.
        failures += not real_064()

    total = 5
    print(f"\nprobe {'PASS' if not failures else 'FAIL'} "
          f"({total - failures + 1}/{total + 1} as expected)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
