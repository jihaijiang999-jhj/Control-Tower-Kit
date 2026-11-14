#!/usr/bin/env python3
"""PILOT-077 dry run on the *real* 076 state bytes (read-only copy).

Copies the live tower root into a throw-away directory, builds a local git repo +
bare ``origin`` whose ``main`` is the real merge commit ``0d9cab0``, then runs
``towerctl envelope-recover`` against the copy.  Nothing outside ``%TEMP%`` is
written and no network is used.  The live tower is left exactly as it was.

Expected: before recovery ``state-verify`` reports the two 076 rows
(envelope/queue MERGED vs replay CORRECTION_REQUIRED); after recovery the replay
folds MERGED and ``state-verify`` is clean, with one recovered MERGE tail.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
WORKTREE = SCRATCH.parent
REAL = Path("C:/Users/mac/Documents/deepseek-harness/default-workspace/tower-dsh")
TOWERCTL = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
MERGE = "0d9cab0dc8d2b2aee555d6758c7c289881399176"
ENVELOPE = "ENV-PILOT-076"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Probe", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Probe", "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, **GIT_ENV), **kwargs)


def git(repo, *args):
    return run(["git", "-C", str(repo), *args])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tower-real076-") as name:
        kit = Path(name) / "kit"
        root = kit / "tower-dsh"
        origin = Path(name) / "origin.git"
        skip = {".git", "__pycache__", ".test-tmp", "worktrees"}
        shutil.copytree(REAL, root,
                        ignore=lambda _d, names: [n for n in names if n in skip])
        # a local repository that already contains the real merge commit
        for args in (("init",), ("symbolic-ref", "HEAD", "refs/heads/main")):
            git(kit, *args)
        fetched = git(kit, "fetch", str(WORKTREE), MERGE)
        print("fetch real merge:", fetched.returncode, fetched.stderr.strip()[:200])
        git(kit, "update-ref", "refs/heads/main", MERGE)
        run(["git", "init", "--bare", str(origin)])
        git(kit, "remote", "add", "origin", str(origin).replace("\\", "/"))
        pushed = git(kit, "push", "origin", "main")
        print("push main:", pushed.returncode, pushed.stderr.strip()[:200])
        git(kit, "update-ref", "refs/remotes/origin/main", MERGE)

        def cli(*args):
            return run([sys.executable, "-B", str(TOWERCTL), "--root", str(root),
                        *args])

        before = cli("state-verify")
        before_payload = json.loads(before.stdout)
        print("before ok:", before_payload["ok"])
        print("before drift:", [row for row in before_payload["drift"]
                                if row["target"] == ENVELOPE])
        recovered = cli("envelope-recover", "--envelope", ENVELOPE,
                        "--merge-commit", MERGE,
                        "--reason", "real 076 recovery re-fold probe")
        print("recover exit:", recovered.returncode)
        print("recover out:", recovered.stdout.strip()[:300])
        after = cli("state-verify")
        after_payload = json.loads(after.stdout)
        print("after ok:", after_payload["ok"])
        print("after drift:", after_payload["drift"])
        rows = [json.loads(line) for line in
                (root / "ledger" / "supervision.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()]
        events = [row for row in rows
                  if row.get("payload", {}).get("envelope") == ENVELOPE]
        print("event tail:", [(row["type"], row["payload"].get("recovered"),
                               (row["payload"].get("merge_commit") or "")[:7])
                              for row in events[-3:]])
        print("merge count:", len([row for row in events if row["type"] == "MERGE"]))
        print("verified:", [row["type"] for row in events
                            if row["type"] == "POST_MERGE_VERIFIED"])
        ok = (recovered.returncode == 0 and after_payload["ok"]
              and after_payload["drift"] == []
              and [row["type"] for row in events[-2:]] == ["MERGE_START", "MERGE"])
        print("REAL076 PROBE", "OK" if ok else "FAIL")
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
