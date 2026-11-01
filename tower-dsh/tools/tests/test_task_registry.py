"""PILOT-057: ``state/TASK_IDS.json`` and the no-reuse gate.

Each case builds a throw-away tower root under the runner's ``TMP`` sandbox and
drives the real CLI through ``subprocess``, so exit codes, written bytes and the
registry are asserted exactly as an operator observes them::

    python -B tools/run_tests.py --pattern test_task_registry.py

The cases cover the whole contract: ``task-ids-init`` backfill (``-VOID`` dirs
included, byte-stable on re-run), ``task-new`` registering ``active`` then
``close`` flipping it to ``closed``, every registered status refusing a second
``task-new`` with zero writes, ``task-ids-reserve`` holding a draft id, the
``check --phase spec`` registry/title gate and the missing-registry bootstrap
that keeps pre-PILOT-057 fixtures working.
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
SCHEMA = "tower/task-ids@1"
REGISTRY = Path("state") / "TASK_IDS.json"
STAMP = "2026-10-01T00:00:00+08:00"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(title: str, status: str, spec_path=None) -> dict:
    """One registry entry with fixed timestamps, for hand-written fixtures."""
    return {"title": title, "status": status, "spec_path": spec_path,
            "created_at": STAMP, "updated_at": STAMP}


class TaskRegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-ids-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for name in ("primary", "ledger", "specs", "tasks", "state"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ----------------------------------------------------------
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def fails(self, cp: subprocess.CompletedProcess, *needles: str) -> dict:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = " ".join(payload["errors"]).lower()
        for needle in needles:
            self.assertIn(needle.lower(), blob, msg=str(payload["errors"]))
        return payload

    def registry(self) -> dict:
        return json.loads((self.root / REGISTRY).read_text(encoding="utf-8"))

    def registry_ids(self) -> dict:
        return self.registry()["ids"]

    def write_registry(self, ids: dict) -> None:
        path = self.root / REGISTRY
        path.write_text(json.dumps({"schema": SCHEMA, "ids": ids},
                                   ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def written(self) -> dict[str, bytes]:
        """Bytes of every file the commands under test may write."""
        snapshot: dict[str, bytes] = {}
        for base in ("tasks", "primary", "ledger", "state"):
            for path in sorted((self.root / base).rglob("*")):
                if path.is_file():
                    key = f"{base}/{path.relative_to(self.root / base).as_posix()}"
                    snapshot[key] = path.read_bytes()
        return snapshot

    def card(self, tid: str, status: str = "closed", suffix: str = "",
             title: str | None = None) -> None:
        """Write ``tasks/<tid><suffix>/record.json`` for an init scan."""
        tdir = self.root / "tasks" / f"{tid}{suffix}"
        tdir.mkdir(parents=True, exist_ok=True)
        record = {"schema": "tower/task@1", "id": tid,
                  "title": title or f"{tid} card {suffix or 'main'}",
                  "status": status, "spec_path": f"pilot/{tid}.spec.json",
                  "created_at": STAMP, "updated_at": STAMP}
        (tdir / "record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def spec(self, tid: str, title: str | None = None) -> Path:
        """A valid ``tower/spec@2`` card plus the worktree it names."""
        data = {
            "schema": "tower/spec@2", "id": tid,
            "title": title or f"{tid} objective",
            "authority": "workspace_write",
            "scope": ["exercise the id registry"],
            "worktree": f"pilot/worktrees/{tid}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "objective": {
                "problem": "an archived card lets its task id be handed out twice",
                "outcome": "task-new refuses every id the registry already knows",
                "approach": "task-ids-init backfills, task-ids-reserve holds drafts",
                "non_goals_and_done": "no id service; done when the gates are green",
            },
        }
        path = self.root / "specs" / f"{tid}.spec.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        (self.root / "pilot" / "worktrees" / tid).mkdir(
            parents=True, exist_ok=True)
        return path

    def record(self, tid: str) -> dict:
        path = self.root / "tasks" / tid / "record.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # -- 1. init backfill -------------------------------------------------
    def test_init_backfills_void_dirs_and_is_byte_stable(self) -> None:
        self.card("PILOT-101", "closed")
        self.card("PILOT-102", "delivered")
        self.card("PILOT-102", "ready", suffix="-VOID")
        self.card("PILOT-103", "dispatched", suffix="-VOID2")
        self.card("PILOT-104", "closed")
        self.card("PILOT-104", "ready", suffix="-VOID")
        first = self.cli("task-ids-init")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["scanned"], 4)
        self.assertEqual(payload["added"], 4)
        ids = self.registry_ids()
        self.assertEqual(sorted(ids),
                         ["PILOT-101", "PILOT-102", "PILOT-103", "PILOT-104"])
        self.assertEqual(ids["PILOT-101"]["status"], "closed")
        self.assertEqual(ids["PILOT-102"]["status"], "active")
        self.assertEqual(ids["PILOT-103"]["status"], "void")
        self.assertEqual(ids["PILOT-104"]["status"], "closed")
        self.assertEqual(ids["PILOT-104"]["title"], "PILOT-104 card main")
        self.assertEqual(ids["PILOT-103"]["spec_path"], "pilot/PILOT-103.spec.json")
        before = (self.root / REGISTRY).read_bytes()
        again = self.cli("task-ids-init")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(json.loads(again.stdout)["added"], 0)
        self.assertEqual((self.root / REGISTRY).read_bytes(), before)

    def test_init_on_empty_tower_writes_an_empty_registry(self) -> None:
        cp = self.cli("task-ids-init")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["added"], 0)
        self.assertEqual(self.registry(), {"schema": SCHEMA, "ids": {}})

    # -- 2. task-new / close ----------------------------------------------
    def test_task_new_registers_active_and_close_marks_closed(self) -> None:
        tid = "PILOT-701"
        self.spec(tid)
        cp = self.cli("task-new", "--spec", f"specs/{tid}.spec.json")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        registered = self.registry_ids()[tid]
        self.assertEqual(registered["status"], "active")
        self.assertEqual(registered["title"], f"{tid} objective")
        self.assertEqual(registered["spec_path"], f"specs/{tid}.spec.json")
        evidence = self.root / "tasks" / tid / "evidence" / "proof.txt"
        evidence.write_text("proof\n", encoding="utf-8")
        record = self.record(tid)
        record.update({
            "status": "accepted", "executor": "exec-701",
            "review": {"reviewer": "rev-701", "verdict": "PASS"},
            "decision": {"id": "D-701"},
            "evidence": [{"path": f"tasks/{tid}/evidence/proof.txt",
                          "sha256": sha256(evidence)}]})
        (self.root / "tasks" / tid / "record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        cp = self.cli("close", "--task", tid)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(self.registry_ids()[tid]["status"], "closed")

    # -- 3. duplicate ids -------------------------------------------------
    def test_task_new_refuses_every_registered_status_with_no_writes(self) -> None:
        held = {"PILOT-801": "active", "PILOT-802": "closed",
                "PILOT-803": "void"}
        self.write_registry({tid: entry("held", status)
                             for tid, status in held.items()})
        snapshot = self.written()
        for tid, status in held.items():
            with self.subTest(status=status):
                self.spec(tid)
                cp = self.cli("task-new", "--spec", f"specs/{tid}.spec.json")
                self.fails(cp, "already registered", tid)
                self.assertFalse((self.root / "tasks" / tid).exists())
        self.assertEqual(self.written(), snapshot)

    # -- 4. reserve -------------------------------------------------------
    def test_reserved_id_is_claimed_by_task_new(self) -> None:
        tid = "PILOT-901"
        first = self.cli("task-ids-reserve", "--id", tid,
                         "--title", "draft 056", "--spec", "pilot/056.spec.json")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        registered = self.registry_ids()[tid]
        self.assertEqual(registered["status"], "reserved")
        self.assertEqual(registered["title"], "draft 056")
        self.assertEqual(registered["spec_path"], "pilot/056.spec.json")
        before = (self.root / REGISTRY).read_bytes()
        again = self.cli("task-ids-reserve", "--id", tid, "--title", "again")
        self.fails(again, "already registered", tid)
        self.assertEqual((self.root / REGISTRY).read_bytes(), before)
        self.spec(tid)
        claim = self.cli("task-new", "--spec", f"specs/{tid}.spec.json")
        self.assertEqual(claim.returncode, 0, claim.stdout + claim.stderr)
        self.assertTrue((self.root / "tasks" / tid).exists())
        self.assertEqual(self.registry_ids()[tid]["status"], "active")
        # The reservation is consumed: a second card is refused.
        self.spec(tid)
        duplicate = self.cli("task-new", "--spec", f"specs/{tid}.spec.json")
        self.fails(duplicate, "already", tid)

    # -- 5. check --phase spec --------------------------------------------
    def prepare_ready_card(self, tid: str, title: str) -> None:
        spec_path = self.spec(tid, title)
        tdir = self.root / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "tower/task@1", "id": tid, "title": title,
            "status": "ready", "authority": "workspace_write",
            "scope": ["x"], "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"], "depends_on": [],
            "worktree": f"pilot/worktrees/{tid}",
            "spec_path": f"specs/{tid}.spec.json",
            "spec_sha256": sha256(spec_path), "spec_gate": None,
            "executor": None, "dispatch": None, "evidence": [],
            "review": None, "decision": None, "closeout": None,
            "created_at": STAMP, "updated_at": STAMP, "next": "",
        }
        (tdir / "record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (tdir / "TASK.md").write_text(f"# {tid}\n", encoding="utf-8")
        (self.root / "ledger" / "primary.jsonl").write_text(
            json.dumps({"seq": 1, "at": STAMP, "type": "SPEC_APPROVED",
                        "actor": "rev-950",
                        "payload": {"task": tid, "by": "rev-950"}}) + "\n",
            encoding="utf-8")

    def test_check_spec_requires_registration_and_matching_title(self) -> None:
        tid = "PILOT-950"
        self.prepare_ready_card(tid, "registered title")
        self.write_registry({})
        self.fails(self.cli("check", "--task", tid, "--phase", "spec"),
                   "not registered", tid)
        self.write_registry({tid: entry("some other title", "active",
                                        f"specs/{tid}.spec.json")})
        self.fails(self.cli("check", "--task", tid, "--phase", "spec"),
                   "title mismatch", tid)
        self.write_registry({tid: entry("registered title", "active",
                                        f"specs/{tid}.spec.json")})
        cp = self.cli("check", "--task", tid, "--phase", "spec")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(self.record(tid)["spec_gate"], "PASS")

    def test_check_spec_reads_missing_registry_as_a_scan(self) -> None:
        tid = "PILOT-951"
        self.prepare_ready_card(tid, "legacy title")
        self.assertFalse((self.root / REGISTRY).exists())
        cp = self.cli("check", "--task", tid, "--phase", "spec")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertFalse((self.root / REGISTRY).exists())

    # -- 6. missing-registry bootstrap ------------------------------------
    def test_task_new_bootstraps_a_missing_registry(self) -> None:
        legacy = "PILOT-960"
        self.card(legacy, "closed", title="legacy closed card")
        tid = "PILOT-961"
        self.spec(tid)
        self.assertFalse((self.root / REGISTRY).exists())
        cp = self.cli("task-new", "--spec", f"specs/{tid}.spec.json")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        ids = self.registry_ids()
        self.assertEqual(sorted(ids), [legacy, tid])
        self.assertEqual(ids[legacy]["status"], "closed")
        self.assertEqual(ids[legacy]["title"], "legacy closed card")
        self.assertEqual(ids[tid]["status"], "active")
        self.assertEqual(ids[tid]["title"], f"{tid} objective")


if __name__ == "__main__":
    unittest.main()
