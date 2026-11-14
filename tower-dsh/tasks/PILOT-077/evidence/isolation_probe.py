#!/usr/bin/env python3
"""PILOT-077 independent probe: frozen post-merge state + real recovery re-fold.

Standalone (no test-suite import): builds throw-away towers + git repos under
``%TEMP%`` and demonstrates, against the real ``towerctl`` entry point:

  1. ``snapshot_state``/``restore_state`` round-trip every byte, delete a file
     a child created and re-create one a child deleted;
  2. a failing post-merge child that mutates the state still leaves the tree
     restored (board/record bytes unchanged) before ``CORRECTION_REQUIRED`` +
     ``POST_MERGE_FAILED`` are written;
  3. a passing post-merge child observes ``MERGED`` and ``TOWER_POST_MERGE=1``;
  4. the root gate does not recurse into the tower suite under that marker;
  5. the 076 recovery shape (a real ``MERGE`` followed by ``POST_MERGE_FAILED``)
     re-folds to ``MERGED`` with a recovered tail, ``state-verify`` drift ``[]``
     and no duplicate event on a second attempt.

Run from anywhere:  python -B scratch/isolation_probe.py
Exit 0 prints ``PROBE OK``; any broken contract prints ``PROBE FAIL`` and exits 2.
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
TOWER = WORKTREE / "tower-dsh"
TOOLS = TOWER / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import tower_cli  # noqa: E402
import tower_envelope  # noqa: E402
import tower_ledger_replay  # noqa: E402

TCLI = TOOLS / "towerctl.py"
ENVELOPE_ID = "ENV-PROBE-001"
TASK_ID = "PROBE-001"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Probe", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Probe", "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}
MUTATE_CHILD = """\
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tower-dsh"
ENVELOPE = ROOT / "supervision" / "envelopes" / "%s.json"
QUEUE = ROOT / "supervision" / "MERGE_QUEUE.json"
BOARD = ROOT / "primary" / "TASK_BOARD.json"
RECORD = ROOT / "tasks" / "%s" / "record.json"

envelope = json.loads(ENVELOPE.read_text(encoding="utf-8"))
envelope["status"] = "MUTATED"
ENVELOPE.write_text(json.dumps(envelope), encoding="utf-8")
QUEUE.write_text('{"entries": []}', encoding="utf-8")
BOARD.write_text('{"mutated": true}', encoding="utf-8")
RECORD.write_text('{"mutated": true}', encoding="utf-8")
raise SystemExit(1)
""" % (ENVELOPE_ID, TASK_ID)
OBSERVE_CHILD = """\
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tower-dsh"
ENVELOPE = ROOT / "supervision" / "envelopes" / "%s.json"


class ObserveTest(unittest.TestCase):
    def test_merged(self):
        self.assertEqual(json.loads(ENVELOPE.read_text(encoding="utf-8"))["status"],
                         "MERGED")
        self.assertEqual(os.environ.get("TOWER_POST_MERGE"), "1")
""" % ENVELOPE_ID


def build_fixture(tmp: Path) -> tuple[Path, Path, str]:
    """A tower root nested in a git repo, with a MERGED legacy envelope."""
    kit = tmp / "kit"
    root = kit / "tower-dsh"
    for name in ("supervision/envelopes", "primary", "ledger"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (kit / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tasks" / TASK_ID).mkdir(parents=True, exist_ok=True)

    def write(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    write(root / "supervision" / "CURRENT_STATE.json",
          {"schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
           "role": "supervision", "phase": "PROBE"})
    write(root / "primary" / "TASK_BOARD.json",
          {"schema": "tower/task-board@1", "tasks": [{"id": TASK_ID}]})
    write(root / "tasks" / TASK_ID / "record.json",
          {"schema": "tower/task@1", "id": TASK_ID, "status": "accepted"})
    write(root / "supervision" / "MERGE_QUEUE.json",
          {"schema": "tower/merge-queue@1", "entries": [{
              "envelope_id": ENVELOPE_ID, "task": TASK_ID, "branch": "probe",
              "base": "main", "status": "MERGED"}]})
    (root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")
    (kit / "tests" / "test_probe.py").write_text(OBSERVE_CHILD, encoding="utf-8")
    # A branch-side envelope lives at the repository root (``repository: ".."``).
    (kit / "merge-envelopes").mkdir(exist_ok=True)
    write(kit / "merge-envelopes" / f"{ENVELOPE_ID}.json",
          {"schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE_ID,
           "task": TASK_ID})
    (kit / "README.md").write_text("base\n", encoding="utf-8")

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, **GIT_ENV))

    git("init")
    git("symbolic-ref", "HEAD", "refs/heads/main")
    git("add", "--all")
    git("-c", "commit.gpgsign=false", "commit", "-m", "base")
    implementation = git("rev-parse", "HEAD").stdout.strip()
    write(root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json", {
        "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE_ID,
        "task": TASK_ID, "repository": "..", "branch": "probe", "base": "main",
        "envelope_path": f"merge-envelopes/{ENVELOPE_ID}.json",
        "implementation_head_sha": implementation,
        "envelope_head_sha": implementation, "status": "MERGED",
        "merge_commit": implementation, "tests_baseline": 1,
    })
    git("add", "--all")
    git("-c", "commit.gpgsign=false", "commit", "-m", "merged envelope")
    return kit, root, implementation


def post_merge(root: Path, result: str = "PASS") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for name in (tower_cli.POST_MERGE_ENV, tower_cli.POST_MERGE_ROOT_ENV):
        env.pop(name, None)
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), "post-merge",
         "--envelope", ENVELOPE_ID, "--result", result],
        capture_output=True, text=True, encoding="utf-8", env=env)


def state_bytes(root: Path) -> dict[str, bytes]:
    paths = {
        "envelope": root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json",
        "queue": root / "supervision" / "MERGE_QUEUE.json",
        "ledger": root / "ledger" / "supervision.jsonl",
        "board": root / "primary" / "TASK_BOARD.json",
        "record": root / "tasks" / TASK_ID / "record.json",
    }
    return {name: path.read_bytes() for name, path in paths.items()}


class RecoverProbe:
    """The 076 recovery shape: a real MERGE, then POST_MERGE_FAILED rows."""

    ENVELOPE = "ENV-PILOT-076"
    TASK = "PILOT-076"

    def __init__(self, tmp: Path) -> None:
        self.kit = tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.origin = tmp / "origin.git"
        for name in ("primary", "supervision/envelopes", "ledger",
                     "tasks/" + self.TASK):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "PROBE", "owner": {"name": "mac"},
            "primary": {"id": "ctl-probe"}})
        self.write_json(self.root / "primary" / "TASK_BOARD.json",
                        {"schema": "tower/task-board@1", "tasks": []})
        self.write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "PROBE",
            "supervisor": {"id": "sup-probe"}})
        for name in ("primary", "supervision"):
            (self.root / "ledger" / f"{name}.jsonl").write_text(
                "", encoding="utf-8")
        self.git("init")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "--all")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "base")
        self.git("checkout", "-b", "pilot/PILOT-076")
        (self.kit / "implementation.txt").write_text("076\n", encoding="utf-8")
        self.git("add", "--all")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "implementation")
        self.implementation = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "-m", "merge 076", "pilot/PILOT-076")
        self.merge_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.merge_commit)
        subprocess.run(["git", "init", "--bare", str(self.origin)],
                       capture_output=True)
        self.git("remote", "add", "origin", str(self.origin).replace("\\", "/"))
        self.git("push", "origin", "main")
        envelope = {
            "schema": "tower/merge-envelope@1", "envelope_id": self.ENVELOPE,
            "task": self.TASK, "repository": "..", "branch": "pilot/PILOT-076",
            "base": "main", "envelope_path": "merge-envelopes/x.json",
            "implementation_head_sha": self.implementation,
            "envelope_head_sha": self.merge_commit,
            "status": "CORRECTION_REQUIRED",
            "merge_commit": self.merge_commit, "tests_baseline": 1,
            "tower_tests_baseline": 1}
        self.write_json(self.root / "supervision" / "envelopes"
                        / f"{self.ENVELOPE}.json", envelope)
        self.write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": self.ENVELOPE, "task": self.TASK,
                         "status": "CORRECTION_REQUIRED",
                         "merge_commit": self.merge_commit}]})
        for kind, extra in (("ENVELOPE_NEW", {"task": self.TASK}),
                            ("QUEUE_ADD", {"task": self.TASK}),
                            ("MERGE_START", {}),
                            ("MERGE", {"merge_commit": self.merge_commit}),
                            ("POST_MERGE_FAILED", {"result": "PASS"})):
            tower_envelope.append_supervision_ledger(
                self.root, kind, "supervision",
                {"envelope": self.ENVELOPE, **extra})
        for args in (("add", "--all"),
                     ("-c", "commit.gpgsign=false", "commit", "-m", "state")):
            self.git(*args)
        self.cli("authority-set", "--supervisor", "sup-probe",
                 "--decision", "D-PROBE", "--by", "mac")
        for args in (("add", "--all"),
                     ("-c", "commit.gpgsign=false", "commit", "-m", "authority")):
            self.git(*args)

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, **GIT_ENV))

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, **GIT_ENV))

    def events(self, kind: str | None = None) -> list[dict]:
        ledger = self.root / "ledger" / "supervision.jsonl"
        rows = [json.loads(line) for line in
                ledger.read_text(encoding="utf-8").splitlines() if line]
        return [row for row in rows if kind is None or row["type"] == kind]

    def replay(self) -> str | None:
        return tower_ledger_replay.replay_envelope_statuses(
            self.root).get(self.ENVELOPE)

    def snapshot(self) -> tuple[bytes, ...]:
        paths = (self.root / "supervision" / "envelopes"
                 / f"{self.ENVELOPE}.json",
                 self.root / "supervision" / "MERGE_QUEUE.json",
                 self.root / "ledger" / "supervision.jsonl")
        return tuple(path.read_bytes() for path in paths)


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    with tempfile.TemporaryDirectory(prefix="tower-probe-077-") as name:
        kit, root, _ = build_fixture(Path(name))

        # 1. byte round trip, including an added and a deleted file
        before = state_bytes(root)
        snapshot = tower_cli.snapshot_state(root, {"task": TASK_ID})
        (root / "supervision" / "envelopes" / "ENV-PROBE-999.json").write_text(
            "{}", encoding="utf-8")
        (root / "tasks" / TASK_ID / "record.json").unlink()
        tower_cli.restore_state(root, snapshot)
        check("snapshot/restore bytes", state_bytes(root) == before,
              "all five state files byte-identical")
        check("snapshot drops added envelope",
              not (root / "supervision" / "envelopes"
                   / "ENV-PROBE-999.json").exists())

        # 2. failing child that mutates state: restore happens before correction
        failing = (kit / "tests" / "test_probe.py")
        failing.write_text(MUTATE_CHILD, encoding="utf-8")
        subprocess.run(["git", "-C", str(kit), "add", "--all"],
                       capture_output=True, env=dict(os.environ, **GIT_ENV))
        subprocess.run(["git", "-C", str(kit), "-c", "commit.gpgsign=false",
                        "commit", "-m", "mutating child"], capture_output=True,
                       env=dict(os.environ, **GIT_ENV))
        before = state_bytes(root)
        fail = post_merge(root)
        after = state_bytes(root)
        envelope_after = json.loads(after["envelope"])
        ledger_after = [json.loads(line) for line in
                        after["ledger"].decode("utf-8").splitlines() if line]
        check("failing run exits 2", fail.returncode == 2,
              f"exit {fail.returncode}")
        check("failing run keeps board/record bytes",
              after["board"] == before["board"]
              and after["record"] == before["record"])
        check("failing run writes only the correction",
              envelope_after["status"] == "CORRECTION_REQUIRED"
              and b"MUTATED" not in after["envelope"]
              and [row["type"] for row in ledger_after] == ["POST_MERGE_FAILED"])

        # 3. a green run: the child sees MERGED and the marker, then verifies
        failing.write_text(OBSERVE_CHILD, encoding="utf-8")
        root.joinpath("supervision", "envelopes",
                      f"{ENVELOPE_ID}.json").write_text(
            json.dumps({**json.loads(before["envelope"]), "status": "MERGED"},
                       indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(kit), "add", "--all"],
                       capture_output=True, env=dict(os.environ, **GIT_ENV))
        subprocess.run(["git", "-C", str(kit), "-c", "commit.gpgsign=false",
                        "commit", "-m", "merged again"], capture_output=True,
                       env=dict(os.environ, **GIT_ENV))
        ok_run = post_merge(root)
        ok_status = json.loads(state_bytes(root)["envelope"])["status"]
        check("green run verifies", ok_run.returncode == 0
              and ok_status == "POST_MERGE_VERIFIED",
              f"exit {ok_run.returncode}, status {ok_status}")

    # 4. root gate recursion is blocked under TOWER_POST_MERGE=1
    with tempfile.TemporaryDirectory(prefix="tower-probe-gate-") as name:
        repo = Path(name) / "repo"
        (repo / "tests").mkdir(parents=True)
        (repo / "tower-dsh" / "tools").mkdir(parents=True)
        shutil.copyfile(WORKTREE / "tests" / "test_tower_gates.py",
                        repo / "tests" / "test_tower_gates.py")
        (repo / "tower-dsh" / "tools" / "run_tests.py").write_text(
            "import pathlib, sys\n"
            "pathlib.Path(__file__).resolve().parents[1].joinpath("
            "'recursed.txt').write_text('ran')\n"
            "sys.stderr.write('Ran 9 tests in 0.1s\\n')\n", encoding="utf-8")
        env = dict(os.environ, TOWER_POST_MERGE="1")
        env.pop("TOWER_POST_MERGE_ROOT", None)
        cp = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests",
             "-p", "test_tower_gates.py", "-v"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
            env=env)
        check("TOWER_POST_MERGE blocks recursion",
              cp.returncode == 0 and "TOWER_TEST_TMP=" not in cp.stdout + cp.stderr
              and not (repo / "tower-dsh" / "recursed.txt").exists(),
              f"exit {cp.returncode}, tower suite not entered")

    # 5. the 076 shape: a recorded MERGE + failing tail recovers to a real MERGED
    with tempfile.TemporaryDirectory(prefix="tower-probe-recover-") as name:
        probe = RecoverProbe(Path(name))
        before = probe.replay()
        recovered = probe.cli("envelope-recover", "--envelope", "ENV-PILOT-076",
                              "--merge-commit", probe.merge_commit,
                              "--reason", "076 recovered tail")
        after = probe.replay()
        verify = json.loads(probe.cli("state-verify").stdout)
        tail = [row["type"] for row in probe.events()][-2:]
        merges = probe.events("MERGE")
        check("076 recovery re-folds the replay",
              before == "CORRECTION_REQUIRED" and recovered.returncode == 0
              and after == "MERGED", f"{before} -> {after}")
        check("076 recovery appends one recovered tail",
              tail == ["MERGE_START", "MERGE"]
              and [row["payload"].get("recovered") for row in probe.events()][-2:]
              == [True, True]
              and len(merges) == 2
              and {row["payload"]["merge_commit"] for row in merges}
              == {probe.merge_commit}
              and not probe.events("POST_MERGE_VERIFIED"))
        check("076 recovery leaves state-verify at zero drift",
              verify["ok"] and verify["drift"] == [])
        before_second = probe.snapshot()
        second = probe.cli("envelope-recover", "--envelope", "ENV-PILOT-076",
                           "--merge-commit", probe.merge_commit,
                           "--reason", "again")
        check("second recovery writes nothing",
              second.returncode == 2 and probe.snapshot() == before_second)

    broken = [item for item in checks if not item[1]]
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    print(f"PROBE {'OK' if not broken else 'FAIL'} {len(checks) - len(broken)}/{len(checks)}")
    return 0 if not broken else 2


if __name__ == "__main__":
    raise SystemExit(main())
