"""PILOT-051: ``depends_on`` hard gate (structure / closure / acyclicity).

Every test builds a throw-away tower root and drives the real CLI through
``subprocess``, so exit codes and single-JSON payloads are asserted exactly as
an operator sees them.  Nothing here reads or writes the real tower.
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
FIXED_TIME = "2026-10-30T00:00:00+08:00"
DEP = "TEST-DEP"
NEW = "TEST-NEW"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DependencyGateCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-deps-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.write_board()
        self.write_spec(NEW)
        self.make_worktree(NEW)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ----------------------------------------------------------
    def make_worktree(self, task_id: str) -> None:
        (self.root / "pilot" / "worktrees" / task_id).mkdir(parents=True, exist_ok=True)

    def write_board(self, *entries) -> None:
        data = {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                "tasks": list(entries)}
        (self.root / "primary" / "TASK_BOARD.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def spec_data(self, task_id: str, depends_on=None) -> dict:
        data = {
            "schema": "tower/spec@2",
            "id": task_id,
            "title": f"{task_id} dependency fixture",
            "authority": "workspace_write",
            "scope": ["exercise depends_on gates"],
            "worktree": f"pilot/worktrees/{task_id}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "objective": {
                "problem": "depends_on is copied but never enforced",
                "outcome": "open dependencies block ready and dispatch",
                "approach": "structure, closure and acyclicity gates",
                "non_goals_and_done": "no spec graph; done when tests are green",
            },
        }
        if depends_on is not None:
            data["depends_on"] = depends_on
        return data

    def write_spec(self, task_id: str, depends_on=None) -> Path:
        path = self.root / "specs" / f"{task_id}.spec.json"
        path.write_text(
            json.dumps(self.spec_data(task_id, depends_on), ensure_ascii=False, indent=2),
            encoding="utf-8")
        return path

    def write_record(self, task_id: str, status: str = "ready",
                     depends_on=None) -> dict:
        self.make_worktree(task_id)
        spec_path = self.write_spec(task_id, depends_on)
        record = {
            "schema": "tower/task@1", "id": task_id, "title": f"{task_id} fixture",
            "status": status, "authority": "workspace_write",
            "scope": ["scope"], "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"], "acceptance": ["tests pass"],
            "depends_on": list(depends_on or []),
            "worktree": f"pilot/worktrees/{task_id}",
            "spec_path": spec_path.relative_to(self.root).as_posix(),
            "spec_sha256": sha256(spec_path), "spec_gate": "PASS",
            "executor": None, "dispatch": None, "evidence": [], "review": None,
            "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME, "next": "",
        }
        self.record_path(task_id).parent.mkdir(parents=True, exist_ok=True)
        self.record_path(task_id).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def prepare(self, task_id: str, status: str = "ready", depends_on=None) -> None:
        self.write_record(task_id, status, depends_on)
        self.write_task_md(task_id)

    def write_task_md(self, task_id: str) -> None:
        path = self.root / "tasks" / task_id / "TASK.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {task_id} fixture\n", encoding="utf-8")

    def record_path(self, task_id: str) -> Path:
        return self.root / "tasks" / task_id / "record.json"

    def record(self, task_id: str) -> dict:
        return json.loads(self.record_path(task_id).read_text(encoding="utf-8"))

    def board_bytes(self) -> bytes:
        return (self.root / "primary" / "TASK_BOARD.json").read_bytes()

    def ledger_bytes(self) -> bytes:
        path = self.root / "ledger" / "primary.jsonl"
        return path.read_bytes() if path.exists() else b""

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def assert_fails(self, cp: subprocess.CompletedProcess, *keywords: str) -> dict:
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = " ".join(payload["errors"]).lower()
        for keyword in keywords:
            self.assertIn(keyword.lower(), blob,
                          msg=f"missing {keyword!r} in {payload['errors']}")
        return payload

    def assert_zero_write(self, task_id: str, ledger_before: bytes) -> None:
        self.assertFalse((self.root / "tasks" / task_id).exists())
        self.assertEqual(self.ledger_bytes(), ledger_before)

    # -- semantic A: task-new structure -----------------------------------
    def test_task_new_accepts_empty_depends_on(self) -> None:
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        record = self.record(NEW)
        self.assertEqual(record["depends_on"], [])
        self.assertEqual(record["status"], "ready")

    def test_task_new_accepts_dependency_on_ready_card(self) -> None:
        self.write_record(DEP, status="ready")
        self.write_spec(NEW, depends_on=[DEP])
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record(NEW)["depends_on"], [DEP])

    def test_task_new_rejects_self_dependency(self) -> None:
        self.write_spec(NEW, depends_on=[NEW])
        ledger_before = self.ledger_bytes()
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assert_fails(cp, "depends_on.self", NEW)
        self.assert_zero_write(NEW, ledger_before)

    def test_task_new_rejects_duplicate_dependency(self) -> None:
        self.write_record(DEP, status="ready")
        self.write_spec(NEW, depends_on=[DEP, DEP])
        ledger_before = self.ledger_bytes()
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assert_fails(cp, "depends_on.duplicate", DEP)
        self.assert_zero_write(NEW, ledger_before)

    def test_task_new_rejects_missing_dependency(self) -> None:
        self.write_spec(NEW, depends_on=["TEST-999"])
        ledger_before = self.ledger_bytes()
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assert_fails(cp, "depends_on.missing", "TEST-999")
        self.assert_zero_write(NEW, ledger_before)

    def test_task_new_rejects_non_list_depends_on(self) -> None:
        self.write_spec(NEW, depends_on=DEP)
        ledger_before = self.ledger_bytes()
        cp = self.run_cli("task-new", "--spec", f"specs/{NEW}.spec.json")
        self.assert_fails(cp, "depends_on.invalid")
        self.assert_zero_write(NEW, ledger_before)

    # -- semantic B: check --phase ready closure ---------------------------
    def test_check_ready_rejects_open_dependency(self) -> None:
        self.prepare(DEP, status="ready")
        self.prepare(NEW, depends_on=[DEP])
        cp = self.run_cli("check", "--task", NEW, "--phase", "ready")
        self.assert_fails(cp, f"depends_on.{DEP}", "ready")

    def test_check_ready_accepts_closed_dependency(self) -> None:
        self.prepare(DEP, status="closed")
        self.prepare(NEW, depends_on=[DEP])
        cp = self.run_cli("check", "--task", NEW, "--phase", "ready")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["ok"])

    def test_check_ready_reports_missing_dependency_target(self) -> None:
        self.prepare(NEW, depends_on=["TEST-999"])
        cp = self.run_cli("check", "--task", NEW, "--phase", "ready")
        self.assert_fails(cp, "depends_on.test-999", "missing")

    # -- semantic C: dispatch closure --------------------------------------
    def test_dispatch_rejects_open_dependency_without_writes(self) -> None:
        self.prepare(DEP, status="ready")
        self.prepare(NEW, depends_on=[DEP])
        record_before = self.record_path(NEW).read_bytes()
        ledger_before = self.ledger_bytes()
        board_before = self.board_bytes()
        cp = self.run_cli("dispatch", "--task", NEW, "--executor", "exec-a")
        self.assert_fails(cp, f"depends_on.{DEP}")
        self.assertEqual(self.record_path(NEW).read_bytes(), record_before)
        self.assertEqual(self.ledger_bytes(), ledger_before)
        self.assertEqual(self.board_bytes(), board_before)

    def test_dispatch_accepts_closed_dependency(self) -> None:
        self.prepare(DEP, status="closed")
        self.prepare(NEW, depends_on=[DEP])
        cp = self.run_cli("dispatch", "--task", NEW, "--executor", "exec-a")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record(NEW)["status"], "dispatched")
        self.assertIn("DISPATCH", (self.root / "ledger" / "primary.jsonl")
                      .read_text(encoding="utf-8"))

    # -- semantic D: acyclicity --------------------------------------------
    def test_check_ready_rejects_cycle(self) -> None:
        self.prepare("TEST-A", status="ready", depends_on=["TEST-B"])
        self.prepare("TEST-B", status="closed", depends_on=["TEST-A"])
        cp = self.run_cli("check", "--task", "TEST-A", "--phase", "ready")
        payload = self.assert_fails(cp, "depends_on.cycle",
                                    "TEST-A -> TEST-B -> TEST-A")
        self.assertEqual(len(payload["errors"]), 1)

    def test_check_ready_rejects_self_cycle(self) -> None:
        self.prepare("TEST-SELF", status="ready", depends_on=["TEST-SELF"])
        cp = self.run_cli("check", "--task", "TEST-SELF", "--phase", "ready")
        self.assert_fails(cp, "depends_on.cycle", "TEST-SELF -> TEST-SELF")

    def test_dispatch_rejects_cycle_without_writes(self) -> None:
        self.prepare("TEST-A", status="ready", depends_on=["TEST-B"])
        self.prepare("TEST-B", status="closed", depends_on=["TEST-A"])
        record_before = self.record_path("TEST-A").read_bytes()
        ledger_before = self.ledger_bytes()
        cp = self.run_cli("dispatch", "--task", "TEST-A", "--executor", "exec-a")
        self.assert_fails(cp, "depends_on.cycle", "TEST-A -> TEST-B -> TEST-A")
        self.assertEqual(self.record_path("TEST-A").read_bytes(), record_before)
        self.assertEqual(self.ledger_bytes(), ledger_before)

    # -- legacy cards ------------------------------------------------------
    def test_legacy_empty_depends_on_passes_ready_and_dispatch(self) -> None:
        self.prepare(NEW, depends_on=[])
        cp = self.run_cli("check", "--task", NEW, "--phase", "ready")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.run_cli("dispatch", "--task", NEW, "--executor", "exec-a")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def test_legacy_missing_depends_on_key_passes(self) -> None:
        self.prepare(NEW, depends_on=[])
        record = self.record(NEW)
        record.pop("depends_on")
        self.record_path(NEW).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        cp = self.run_cli("check", "--task", NEW, "--phase", "ready")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)


if __name__ == "__main__":
    unittest.main()
