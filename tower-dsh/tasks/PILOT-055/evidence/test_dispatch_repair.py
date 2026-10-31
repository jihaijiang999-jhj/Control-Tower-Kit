"""PILOT-055: re-dispatch from ``dispatched`` is legal (executor replacement).

The real ledger dispatched PILOT-055 twice: a placeholder executor first, then
the real one.  Replaying the second ``DISPATCH`` from ``dispatched`` produced
one ``illegal_transition``.  Owner choice A legalises exactly that source: a
second ``DISPATCH`` replaces the executor instead of restarting the lifecycle.
``cmd_dispatch`` mirrors the table, and no other status is relaxed.

Every test builds a throw-away tower root and drives the real CLI through
``subprocess``; the real tower is never read or written.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
TASK_ID = "TEST-055"
FIXED_TIME = "2026-11-01T00:00:00+08:00"
# Sorted exactly like ``_sorted_states``: "dispatched" joins the two corners.
DISPATCH_ALLOWED = ["dispatched", "ready", "rework"]

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DispatchRepairCase(unittest.TestCase):
    """One isolated tower plus the builders each scenario needs."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-redispatch-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("ledger", "primary", "tasks",
                          "supervision", "supervision/envelopes"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        self.write_board({})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- builders ---------------------------------------------------------
    def primary(self, event_type: str, **payload) -> dict:
        return towerctl.append_ledger(self.root, event_type, "primary", payload)

    def write_board(self, statuses: dict[str, str]) -> None:
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                    "tasks": [{"id": task_id, "title": task_id,
                               "status": status}
                              for task_id, status in statuses.items()]})

    def put_record(self, task_id: str, status: str, **extra) -> None:
        record = {"schema": "tower/task@1", "id": task_id, "title": task_id,
                  "status": status, "executor": None, "dispatch": None,
                  "evidence": [], "depends_on": [], "review": None,
                  "decision": None, "closeout": None,
                  "created_at": FIXED_TIME, "updated_at": FIXED_TIME, "next": ""}
        record.update(extra)
        write_json(self.root / "tasks" / task_id / "record.json", record)

    def record(self, task_id: str) -> dict:
        path = self.root / "tasks" / task_id / "record.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def build_ready_task(self, task_id: str = TASK_ID) -> None:
        """A ready card ``dispatch`` accepts: spec, worktree and TASK.md."""
        spec_rel = f"pilot/{task_id}.spec.json"
        write_json(self.root / spec_rel, {"schema": "tower/spec@2",
                                          "id": task_id})
        (self.root / "pilot" / "worktrees" / task_id).mkdir(
            parents=True, exist_ok=True)
        (self.root / "tasks" / task_id).mkdir(parents=True, exist_ok=True)
        (self.root / "tasks" / task_id / "TASK.md").write_text(
            f"# {task_id} fixture\n", encoding="utf-8")
        self.put_record(
            task_id, "ready", authority="workspace_write", scope=["fixture"],
            allowed_paths=["tools/example.py"], forbidden=["merge"],
            acceptance=["tests pass"],
            worktree=f"pilot/worktrees/{task_id}", spec_path=spec_rel,
            spec_sha256=file_sha256(self.root / spec_rel), spec_gate="PASS")
        self.write_board({task_id: "ready"})
        self.primary("TASK_NEW", task=task_id)

    # -- driver -----------------------------------------------------------
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def state_verify(self) -> tuple[dict, int]:
        cp = self.run_cli("state-verify")
        return json.loads(cp.stdout), cp.returncode

    def dispatch_events(self, task_id: str) -> list[dict]:
        grouped = towerctl.ledger_payloads_by_task(self.root, "DISPATCH")
        return grouped.get(task_id, [])

    def illegal_transitions(self, out: dict) -> list[dict]:
        return [item for item in out["drift"]
                if item["kind"] == "illegal_transition"]

    # -- replay: the repaired shape --------------------------------------
    def test_replay_two_consecutive_dispatches_is_legal(self) -> None:
        self.primary("TASK_NEW", task=TASK_ID)
        self.primary("DISPATCH", task=TASK_ID, executor="placeholder")
        self.primary("DISPATCH", task=TASK_ID, executor="real-executor")
        self.put_record(TASK_ID, "dispatched")
        self.write_board({TASK_ID: "dispatched"})

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        transitions: list[dict] = []
        states = towerctl.replay_task_statuses(self.root, transitions)
        self.assertEqual(states[TASK_ID], "dispatched")
        self.assertEqual(transitions, [])

    # -- table: only one source state was added --------------------------
    def test_dispatch_table_adds_only_dispatched(self) -> None:
        self.assertEqual(frozenset(towerctl.TASK_TRANSITIONS["DISPATCH"]),
                         frozenset({"ready", "rework", "dispatched"}))
        for state in ("delivered", "reviewed", "accepted", "closed"):
            self.assertNotIn(state, towerctl.TASK_TRANSITIONS["DISPATCH"],
                             msg=f"DISPATCH must not accept {state}")

    # -- command: re-dispatch replaces the executor ----------------------
    def test_redispatch_command_replaces_executor(self) -> None:
        self.build_ready_task()
        first = self.run_cli("dispatch", "--task", TASK_ID,
                             "--executor", "placeholder")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.record(TASK_ID)["status"], "dispatched")

        second = self.run_cli("dispatch", "--task", TASK_ID,
                              "--executor", "real-executor")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        record = self.record(TASK_ID)
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["executor"], "real-executor")
        self.assertEqual(record["dispatch"]["executor"], "real-executor")
        self.assertEqual([event["executor"] for event
                          in self.dispatch_events(TASK_ID)],
                         ["placeholder", "real-executor"])

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(self.illegal_transitions(out), [])

    # -- the existing ready -> dispatched path is untouched --------------
    def test_first_dispatch_from_ready_is_still_clean(self) -> None:
        self.build_ready_task()
        cp = self.run_cli("dispatch", "--task", TASK_ID,
                          "--executor", "exec-a")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(self.illegal_transitions(out), [])

    # -- replay: reviewed is still an illegal source ---------------------
    def test_replay_dispatch_from_reviewed_is_illegal(self) -> None:
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
            self.primary(event_type, task=TASK_ID)
        self.primary("CHECKBACK", task=TASK_ID, verdict="PASS")
        self.primary("DISPATCH", task=TASK_ID, executor="real-executor")
        self.put_record(TASK_ID, "dispatched")
        self.write_board({TASK_ID: "dispatched"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": TASK_ID,
            "event": "DISPATCH", "expected": DISPATCH_ALLOWED,
            "actual": "reviewed"}])

    # -- replay: closed is still an illegal source -----------------------
    def test_replay_dispatch_from_closed_is_illegal(self) -> None:
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
            self.primary(event_type, task=TASK_ID)
        self.primary("CHECKBACK", task=TASK_ID, verdict="PASS")
        self.primary("ACCEPT", task=TASK_ID, decision="D-001")
        self.primary("CLOSEOUT", task=TASK_ID,
                     closeout=f"tasks/{TASK_ID}/CLOSEOUT.md")
        self.primary("DISPATCH", task=TASK_ID, executor="real-executor")
        self.put_record(TASK_ID, "dispatched")
        self.write_board({TASK_ID: "dispatched"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": TASK_ID,
            "event": "DISPATCH", "expected": DISPATCH_ALLOWED,
            "actual": "closed"}])

    # -- command: non-sources still refuse without writing ---------------
    def test_dispatch_command_refuses_other_statuses(self) -> None:
        for status in ("delivered", "reviewed", "accepted", "closed"):
            with self.subTest(status=status):
                self.put_record(TASK_ID, status)
                record_path = (self.root / "tasks" / TASK_ID / "record.json")
                record_before = record_path.read_bytes()
                ledger_before = (self.root / "ledger" / "primary.jsonl").read_bytes()

                cp = self.run_cli("dispatch", "--task", TASK_ID,
                                  "--executor", "exec-x")

                self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
                payload = json.loads(cp.stdout)
                self.assertFalse(payload["ok"])
                self.assertIn("cannot dispatch", " ".join(payload["errors"]))
                self.assertEqual(record_path.read_bytes(), record_before)
                self.assertEqual(
                    (self.root / "ledger" / "primary.jsonl").read_bytes(),
                    ledger_before)


if __name__ == "__main__":
    unittest.main()
