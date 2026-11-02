"""PILOT-061 probe: which PR head may be pinned, and at what commit.

Builds a throw-away repository plus a bare origin and an offline ``gh`` stub,
drives the real ``pr_remote_merge`` / ``pr_merge_head`` code, and prints one
line per head shape.  Run from the worktree root::

    python scratch/merge_probe.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS = WORKTREE / "tower-dsh" / "tools"
sys.path.insert(0, str(TOOLS))

import tower_merge  # noqa: E402
from tower_common import MergeBlocked  # noqa: E402

BRANCH = "pilot/PILOT-061"
ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-061.json"
SECOND_ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-061-B.json"

GH_STUB = """import json, os, sys
def record(argv):
    path = os.environ.get("PROBE_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\\n")
def main(argv):
    if argv[:2] == ["pr", "merge"]:
        record(argv)
        return 0
    if argv[:2] == ["pr", "create"]:
        print("https://example.invalid/pull/61")
        return 0
    return 0
raise SystemExit(main(sys.argv[1:]))
"""

GIT_ID = {
    "GIT_AUTHOR_NAME": "PILOT-061 Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "PILOT-061 Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                        text=True, encoding="utf-8",
                        env={**os.environ, **GIT_ID})
    if cp.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp.stdout.strip()


def commit(repo: Path, message: str, *paths: str) -> str:
    add = ["git", "-C", str(repo), "add", "--", *paths] if paths else \
          ["git", "-C", str(repo), "add", "-A"]
    subprocess.run(add, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                    "commit", "-m", message], check=True, capture_output=True,
                   env={**os.environ, **GIT_ID})
    return git(repo, "rev-parse", "HEAD")


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def match_head_from_log(log: Path) -> str:
    calls = [json.loads(line) for line in
             log.read_text(encoding="utf-8").splitlines() if line.strip()]
    argv = [call for call in calls if call[:2] == ["pr", "merge"]][-1]
    return argv[argv.index("--match-head-commit") + 1]


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pilot-061-probe-") as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        origin = tmp_path / "origin.git"
        stub = tmp_path / "gh_stub.py"
        log = tmp_path / "gh-argv.jsonl"
        stub.write_text(GH_STUB, encoding="utf-8")
        subprocess.run(["git", "init", "--bare", str(origin)], check=True,
                       capture_output=True)
        repo.mkdir()
        git(repo, "init")
        git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
        write(repo, "README.md", "base\n")
        base = commit(repo, "base")
        git(repo, "checkout", "-b", BRANCH)
        write(repo, "feature.txt", "implementation\n")
        implementation = commit(repo, "implementation")
        git(repo, "remote", "add", "origin", str(origin).replace("\\", "/"))
        args = argparse.Namespace(remote="origin", envelope="ENV-PILOT-061",
                                  supervisor="sup-061", check_timeout=10,
                                  check_interval=0.05)
        env = {
            "envelope_id": "ENV-PILOT-061", "task": "PILOT-061",
            "branch": BRANCH, "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": implementation,
        }

        os.environ["TOWERCTL_GH"] = f"{sys.executable} {stub}"
        os.environ["PROBE_GH_LOG"] = str(log)

        def run(label: str) -> None:
            try:
                identity = tower_merge.pr_remote_merge(repo, env, args)
            except MergeBlocked as exc:
                print(f"{label}: BLOCKED {exc.phase}/{exc.reason}: {exc.detail}")
                return
            pinned = match_head_from_log(log)
            print(f"{label}: MERGED pin={pinned} "
                  f"(pr={identity['pr_number']})")
            if pinned != git(repo, "rev-parse", BRANCH):
                failures.append(f"{label}: pinned {pinned} is not the PR head")

        # 1. implementation-only head.
        print(f"base={base} implementation={implementation}")
        run("case-1 impl-only")
        if match_head_from_log(log) != implementation:
            failures.append("case-1: match head is not the implementation")

        # 2. implementation + one envelope-only commit.
        write(repo, ENVELOPE_PATH, json.dumps({"envelope_id": "ENV-PILOT-061"}))
        envelope_head = commit(repo, "envelope", ENVELOPE_PATH)
        print(f"envelope_head={envelope_head}")
        run("case-2 envelope-only")
        if match_head_from_log(log) != envelope_head:
            failures.append("case-2: match head is not the PR head")

        def blocked(label: str) -> None:
            try:
                tower_merge.pr_merge_head(repo, env)
            except MergeBlocked as exc:
                print(f"{label}: BLOCKED {exc.phase}/{exc.reason}: {exc.detail}")
                return
            failures.append(f"{label}: was not blocked")
            print(f"{label}: NOT BLOCKED (unexpected)")

        # 3. implementation + an extra file.
        write(repo, "leak.txt", "implementation change\n")
        commit(repo, "extra", "leak.txt")
        blocked("case-3 extra-file")

        # 4. one commit carrying two envelope files.
        git(repo, "reset", "--hard", implementation)
        write(repo, ENVELOPE_PATH, json.dumps({"envelope_id": "ENV-PILOT-061"}))
        write(repo, SECOND_ENVELOPE_PATH, json.dumps({"envelope_id": "ENV-PILOT-061"}))
        commit(repo, "two envelopes", ENVELOPE_PATH, SECOND_ENVELOPE_PATH)
        blocked("case-4 two-envelope-files")

        # 5. two commits touching the same envelope file.
        git(repo, "reset", "--hard", envelope_head)
        write(repo, ENVELOPE_PATH, json.dumps({"envelope_id": "ENV-PILOT-061",
                                               "revision": 2}))
        commit(repo, "envelope revision", ENVELOPE_PATH)
        blocked("case-5 two-commits")

        # 6. an empty commit on top of the implementation: different head, no
        #    diff at all.
        git(repo, "reset", "--hard", implementation)
        subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                        "commit", "--allow-empty", "-m", "empty"], check=True,
                       capture_output=True, env={**os.environ, **GIT_ID})
        blocked("case-6 empty-diff")

    print("PROBE: " + ("PASS" if not failures else "FAIL " + "; ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
