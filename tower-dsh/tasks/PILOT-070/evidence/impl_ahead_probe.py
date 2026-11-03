"""PILOT-070 probe: base-ahead must start at the implementation head.

Builds the exact shape that defeated PILOT-069 in a throw-away repository:

* ``main`` carries a base-side envelope commit and then a state-only commit;
* the implementation branch was cut before both, so it is behind;
* the merge checkout is ``main`` and ``main`` already equals ``origin/main``.

It then prints, side by side, what a ``HEAD``-based merge-base sees (an empty
base-ahead, the 069 bug) and what ``tower_cli.base_ahead_paths(impl_head)``
sees (the state-only paths the audited ``--admin`` merge needs).  Branch-only
code must not appear on either side.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS_DIR = WORKTREE / "tower-dsh" / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import tower_cli  # noqa: E402  (path setup must run first)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "PILOT-070 Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "PILOT-070 Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}
STATE_PATH = "tower-dsh/ledger/BASE-SYNC-STATE.json"
ENVELOPE_PATH = "tower-dsh/merge-envelopes/ENV-PILOT-070.json"
BRANCH_CODE_PATH = "feature.txt"


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                        text=True, encoding="utf-8",
                        env={**os.environ, **GIT_ENV})
    if cp.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp.stdout.strip()


def commit(repo: Path, message: str, paths: list[str]) -> str:
    git(repo, "add", "--", *paths)
    git(repo, "-c", "commit.gpgsign=false", "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def build(tmp: Path) -> dict:
    kit = tmp / "kit"
    origin = tmp / "origin.git"
    kit.mkdir()
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    commit(kit, "base", ["README.md"])
    base_sha = git(kit, "rev-parse", "HEAD")
    # The implementation forks before the envelope and state commits.
    git(kit, "checkout", "-b", "pilot/PILOT-070")
    (kit / BRANCH_CODE_PATH).write_text("implementation\n", encoding="utf-8")
    impl_head = commit(kit, "implementation", [BRANCH_CODE_PATH])
    git(kit, "checkout", "main")
    # The base-side envelope is committed straight to main (063/068/070).
    envelope = kit / ENVELOPE_PATH
    envelope.parent.mkdir(parents=True)
    envelope.write_text(json.dumps({"envelope_id": "ENV-PILOT-070"}) + "\n",
                        encoding="utf-8")
    commit(kit, "base-side envelope", [ENVELOPE_PATH])
    subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                   capture_output=True)
    git(kit, "remote", "add", "origin", str(origin).replace("\\", "/"))
    git(kit, "push", "origin", "main")
    # The base advances with state only after the implementation forked.
    state = kit / STATE_PATH
    state.parent.mkdir(parents=True)
    state.write_text("{}\n", encoding="utf-8")
    commit(kit, "base state advance", [STATE_PATH])
    git(kit, "push", "origin", "main")
    return {"kit": kit, "origin": origin, "base_sha": base_sha,
            "impl_head": impl_head}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pilot-070-probe-") as raw:
        fixture = build(Path(raw))
        kit = fixture["kit"]
        impl_head = fixture["impl_head"]
        head = git(kit, "rev-parse", "HEAD")
        origin_main = git(fixture["origin"], "rev-parse", "refs/heads/main")
        git(kit, "fetch", "--quiet", "origin", "main")
        tip = git(kit, "rev-parse", "FETCH_HEAD")
        old_common = git(kit, "merge-base", "HEAD", tip)
        old_paths = ([] if old_common == tip else
                     [line for line in git(kit, "diff", "--name-only",
                                           old_common, tip).splitlines()
                      if line])
        new_paths = tower_cli.base_ahead_paths(kit, impl_head)
        state, code = tower_cli.classify_base_paths(new_paths, "tower-dsh/")
        result = {
            "head": head,
            "origin_main": origin_main,
            "impl_head": impl_head,
            "head_equals_origin_main": head == origin_main,
            "head_merge_base": old_common,
            "head_based_paths": old_paths,
            "impl_based_paths": new_paths,
            "state_only": state,
            "code_docs": code,
            "branch_code_excluded": BRANCH_CODE_PATH not in new_paths,
        }
        print(json.dumps(result, indent=2))
        if head != origin_main:
            raise SystemExit("probe fixture: HEAD must equal origin/main")
        if old_common != tip or old_paths:
            raise SystemExit("probe fixture: HEAD-based base-ahead must be empty")
        if new_paths != [STATE_PATH, ENVELOPE_PATH]:
            raise SystemExit(f"implementation-based base-ahead drifted: {new_paths}")
        if code or BRANCH_CODE_PATH in new_paths:
            raise SystemExit("branch code leaked into base-ahead")


if __name__ == "__main__":
    main()
