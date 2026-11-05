"""PILOT-075 probe: 074's recovered merge replays and recovers to zero drift.

Two independent observations, neither touching the real tower state:

A. Replay the *real* worktree ``ledger/supervision.jsonl`` (read-only) and show
   that ENV-PILOT-074 no longer reports ``illegal_transition``: the recovered
   ``MERGE`` from ``CORRECTION_REQUIRED`` is admitted, and the two failed
   post-merges keep the settled status ``MERGED``.

B. Build a throw-away copy of the 074 shape (local git repo + local bare origin,
   no network) and run the real ``envelope-recover`` / ``state-verify`` CLIs:
   the existing recovered ``MERGE`` is not duplicated, the envelope/queue become
   ``MERGED`` and state-verify reports zero drift.

Run from anywhere::

    python -B scratch/recover_probe.py
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
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import tower_envelope  # noqa: E402
from tower_ledger_replay import (  # noqa: E402
    replay_envelope_statuses, verify_ledger_file,
)

ENV = "ENV-PILOT-074"
TASK = "PILOT-074"
SUP = "sup-probe-075"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Pilot Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Pilot Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", env={**dict(os.environ), **IDENTITY})


def ok(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    cp = run(args, cwd)
    if cp.returncode != 0:
        raise AssertionError(f"{args}: {cp.stdout}{cp.stderr}")
    return cp


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return run([sys.executable, "-B", str(TOOLS / "towerctl.py"),
                "--root", str(root), *args], root)


def real_tower_replay() -> None:
    print("== A. real worktree ledger replay (read-only) ==")
    report = verify_ledger_file(TOWER, "supervision")
    print(f"ledger events={report['events']} chain_errors={report['errors']}")
    transitions: list[dict] = []
    states = replay_envelope_statuses(TOWER, transitions)
    print(f"{ENV} replayed status = {states.get(ENV)!r}")
    rows = [row for row in transitions if row["target"] == ENV]
    print(f"{ENV} illegal_transition rows = {rows}")
    cp = cli(TOWER, "state-verify")
    payload = json.loads(cp.stdout)
    print(f"state-verify exit={cp.returncode} drift={json.dumps(payload['drift'], ensure_ascii=False)}")
    print()


def build_074_fixture() -> tuple[Path, Path, str]:
    tmp = Path(tempfile.mkdtemp(prefix="pilot075-probe-"))
    kit = tmp / "kit"
    tower = kit / "tower-dsh"
    origin = tmp / "origin.git"
    for directory in ("primary", "supervision/envelopes", "ledger"):
        (tower / directory).mkdir(parents=True, exist_ok=True)
    for name in ("primary.jsonl", "supervision.jsonl"):
        (tower / "ledger" / name).write_text("", encoding="utf-8")
    for name, payload in (
            ("CURRENT_STATE.json", {"schema": "tower/current-state@1",
                                    "tower_id": "tower-dsh", "role": "primary",
                                    "phase": "PROBE", "owner": {"name": "mac"},
                                    "primary": {"id": "ctl-probe-075"}}),
    ):
        (tower / "primary" / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    (tower / "supervision" / "CURRENT_STATE.json").write_text(json.dumps({
        "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
        "role": "supervision", "phase": "PROBE",
        "supervisor": {"id": SUP}}) + "\n", encoding="utf-8")
    (tower / "primary" / "TASK_BOARD.json").write_text(
        '{"schema": "tower/task-board@1", "tasks": []}\n', encoding="utf-8")
    (tower / "supervision" / "MERGE_QUEUE.json").write_text(
        '{"schema": "tower/merge-queue@1", "entries": []}\n', encoding="utf-8")

    kit.mkdir(parents=True, exist_ok=True)
    ok(["git", "init"], kit)
    ok(["git", "symbolic-ref", "HEAD", "refs/heads/main"], kit)
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    ok(["git", "add", "-A"], kit)
    ok(["git", "-c", "commit.gpgsign=false", "commit", "-m", "base"], kit)
    ok(["git", "checkout", "-b", "feature/probe"], kit)
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    ok(["git", "add", "-A"], kit)
    ok(["git", "-c", "commit.gpgsign=false", "commit", "-m", "implementation"], kit)
    impl = ok(["git", "rev-parse", "HEAD"], kit).stdout.strip()
    ok(["git", "checkout", "main"], kit)
    ok(["git", "init", "--bare", str(origin)], tmp)
    ok(["git", "remote", "add", "origin", str(origin).replace("\\", "/")], kit)
    ok(["git", "-c", "commit.gpgsign=false", "merge", "--no-ff", "feature/probe",
        "-m", "merge feature"], kit)
    merge_commit = ok(["git", "rev-parse", "HEAD"], kit).stdout.strip()
    ok(["git", "push", "origin", "main"], kit)

    auth = cli(tower, "authority-set", "--supervisor", SUP,
               "--decision", "D-PROBE-075", "--by", "mac")
    if auth.returncode != 0:
        raise AssertionError(auth.stdout + auth.stderr)

    event = lambda kind, **payload: tower_envelope.append_supervision_ledger(
        tower, kind, "supervision", {"envelope": ENV, **payload})
    tower_envelope.append_supervision_ledger(
        tower, "ENVELOPE_NEW", "primary",
        {"envelope": ENV, "task": TASK, "head": impl, "base_side": True,
         "base": "main"})
    tower_envelope.append_supervision_ledger(
        tower, "QUEUE_ADD", "primary", {"envelope": ENV, "task": TASK})
    event("MERGE_START", supervisor=SUP)
    event("MERGE_BLOCKED", phase="checks", reason="checks")
    event("MERGE", merge_commit=merge_commit, recovered=True, by=SUP,
          reason="074 admin merge")
    event("POST_MERGE_FAILED", result="PASS")
    event("POST_MERGE_FAILED", result="PASS")

    envelope = {
        "schema": "tower/merge-envelope@1", "envelope_id": ENV, "task": TASK,
        "repository": "..", "branch": "feature/probe", "base": "main",
        "envelope_path": f"merge-envelopes/{ENV}.json",
        "implementation_head_sha": impl, "tests_baseline": 770,
        "tower_tests_baseline": 900, "status": "CORRECTION_REQUIRED",
        "base_side": True, "merge_commit": merge_commit, "recovered": True,
        "recovered_by": SUP, "recovery_reason": "074 re-recover after failed post-merge",
    }
    (tower / "supervision" / "envelopes" / f"{ENV}.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (tower / "supervision" / "MERGE_QUEUE.json").write_text(json.dumps({
        "schema": "tower/merge-queue@1", "entries": [{
            "envelope_id": ENV, "task": TASK, "branch": "feature/probe",
            "base": "main", "status": "CORRECTION_REQUIRED",
            "added_at": "2026-11-04T23:27:48+08:00",
            "merge_commit": merge_commit}]}) + "\n", encoding="utf-8")
    return tower, tmp, merge_commit


def fixture_recovery() -> None:
    print("== B. isolated 074-shape recovery (local git + bare origin, no network) ==")
    tower, tmp, merge_commit = build_074_fixture()
    before = cli(tower, "state-verify")
    before_payload = json.loads(before.stdout)
    print(f"before exit={before.returncode} "
          f"drift={json.dumps(before_payload['drift'], ensure_ascii=False)}")
    recovered = cli(tower, "envelope-recover", "--envelope", ENV,
                    "--merge-commit", merge_commit,
                    "--reason", "075 probe: finish 074 recovery")
    print(f"recover exit={recovered.returncode} stdout={recovered.stdout.strip()}")
    after = cli(tower, "state-verify")
    after_payload = json.loads(after.stdout)
    rows = [json.loads(line) for line in
            (tower / "ledger" / "supervision.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    merges = [row for row in rows if row["type"] == "MERGE"]
    starts = [row for row in rows if row["type"] == "MERGE_START"]
    envelope = json.loads((tower / "supervision" / "envelopes" / f"{ENV}.json")
                          .read_text(encoding="utf-8"))
    queue = json.loads((tower / "supervision" / "MERGE_QUEUE.json")
                       .read_text(encoding="utf-8"))
    entry = next(item for item in queue["entries"] if item["envelope_id"] == ENV)
    print(f"after exit={after.returncode} "
          f"drift={json.dumps(after_payload['drift'], ensure_ascii=False)}")
    print(f"MERGE events={len(merges)} recovered={[m['payload'].get('recovered') for m in merges]}")
    print(f"MERGE_START events={len(starts)}")
    print(f"envelope.status={envelope['status']!r} merge_commit_match="
          f"{envelope.get('merge_commit') == merge_commit}")
    print(f"queue.status={entry['status']!r} merge_commit_match="
          f"{entry.get('merge_commit') == merge_commit}")
    verified = [row for row in rows if row["type"] == "POST_MERGE_VERIFIED"]
    print(f"POST_MERGE_VERIFIED events={len(verified)} (recover must not write one)")
    print(f"fixture={tmp}")


if __name__ == "__main__":
    real_tower_replay()
    fixture_recovery()
