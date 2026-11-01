"""PILOT-059: per-card acceptance, the auto/manual split.

Every case builds its own throw-away tower root under the runner's ``TMP``
sandbox and drives the real CLI through ``subprocess``, so exit codes, written
files and the rendered table are asserted exactly as an operator observes
them::

    python -B -m unittest tools.tests.test_acceptance -v

The contract under test: ``task-new`` writes ``ACCEPTANCE.json`` plus the
rendered ``ACCEPTANCE.md``; ``acceptance-add`` appends or (with ``--replace``)
updates an item and refuses an id/kind collision; ``accept`` writes ACCEPT only
when every ``auto`` item is ``passed``, nothing is ``failed`` and any manual
item still ``pending`` was explicitly allowed by the owner with a note.  Cards
up to PILOT-058 have no list and stay acceptable.
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
SCHEMA = "tower/acceptance@1"
# Created after the PILOT-059 cutoff: its ACCEPTANCE.json is mandatory.
STAMP = "2026-11-01T21:30:00+08:00"
# A card from before the per-card list existed.
LEGACY_STAMP = "2026-10-01T00:00:00+08:00"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


class AcceptanceKit(unittest.TestCase):
    """One reviewed card with evidence, but no acceptance list yet."""

    TASK = "PILOT-701"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-acceptance-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs", "state",
                          f"tasks/{self.TASK}/evidence",
                          f"pilot/worktrees/{self.TASK}"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        self.proof = (self.root / "tasks" / self.TASK / "evidence" / "proof.txt")
        self.proof.write_text("proof of work\n", encoding="utf-8")
        self.record = {
            "schema": "tower/task@1", "id": self.TASK,
            "title": "acceptance fixture", "status": "reviewed",
            "authority": "workspace_write",
            "scope": ["exercise per-card acceptance"],
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"], "depends_on": [],
            "worktree": f"pilot/worktrees/{self.TASK}", "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{"path": f"tasks/{self.TASK}/evidence/proof.txt",
                          "sha256": digest(self.proof),
                          "bytes": self.proof.stat().st_size}],
            "decision": None, "closeout": None,
            "created_at": STAMP, "updated_at": STAMP, "next": "",
        }
        self.write_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, *args)

    def fails(self, cp: subprocess.CompletedProcess, *needles: str) -> dict:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = " ".join(payload["errors"]).lower()
        for needle in needles:
            self.assertIn(needle.lower(), blob, msg=str(payload["errors"]))
        return payload

    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / self.TASK / "record.json", data)
        self.record = data

    def record_on_disk(self, task: str | None = None) -> dict:
        path = self.root / "tasks" / (task or self.TASK) / "record.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def acceptance(self, task: str | None = None) -> dict:
        path = self.root / "tasks" / (task or self.TASK) / "ACCEPTANCE.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def md_text(self, task: str | None = None) -> str:
        return (self.root / "tasks" / (task or self.TASK) / "ACCEPTANCE.md"
                ).read_text(encoding="utf-8")

    def md_rows(self, task: str | None = None) -> list[list[str]]:
        """The table body of ``ACCEPTANCE.md`` as ``[id, kind, status, note]``."""
        rows = []
        for line in self.md_text(task).splitlines():
            line = line.strip()
            if not line.startswith("|") or set(line) <= {"|", "-", " "}:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and cells[0] == "ID":
                continue
            rows.append(cells)
        return rows

    def write_acceptance(self, items: list[dict]) -> None:
        write_json(self.root / "tasks" / self.TASK / "ACCEPTANCE.json",
                   {"schema": SCHEMA, "items": items})

    def install_card(self, task: str, **overrides) -> dict:
        """Write ``tasks/<task>/record.json`` (+ its own proof) for one card."""
        proof = self.root / "tasks" / task / "evidence" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("proof of work\n", encoding="utf-8")
        data = {**self.record, "id": task,
                "worktree": f"pilot/worktrees/{task}",
                "evidence": [{"path": f"tasks/{task}/evidence/proof.txt",
                              "sha256": digest(proof),
                              "bytes": proof.stat().st_size}]}
        data.update(overrides)
        write_json(self.root / "tasks" / task / "record.json", data)
        return data

    def snapshot(self) -> dict[str, bytes]:
        """Bytes of every task/ledger/board/state file (zero-write checks)."""
        seen: dict[str, bytes] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or "pilot" in path.parts:
                continue
            seen[path.relative_to(self.root).as_posix()] = path.read_bytes()
        return seen

    # -- command helpers --------------------------------------------------
    def add(self, item_id: str, kind: str, status: str, note: str = "",
            *extra: str) -> subprocess.CompletedProcess:
        return self.cli("acceptance-add", "--task", self.TASK, "--id", item_id,
                        "--kind", kind, "--status", status, "--note", note,
                        *extra)

    def accept(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("accept", "--task", self.TASK, "--decision", "D-059",
                        *extra)

    def accepted(self) -> bool:
        return self.record_on_disk()["status"] == "accepted"


class TaskNewAcceptanceCase(AcceptanceKit):
    """``task-new`` gives every new card the default A-01 auto pending item."""

    NEW = "PILOT-702"

    def write_spec(self) -> Path:
        data = {
            "schema": "tower/spec@2", "id": self.NEW,
            "title": f"{self.NEW} acceptance fixture",
            "authority": "workspace_write",
            "scope": ["exercise the per-card acceptance list"],
            "worktree": f"pilot/worktrees/{self.NEW}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "objective": {
                "problem": "one failed manual step blocks the whole card",
                "outcome": "each card lists its auto and manual items",
                "approach": "task-new writes the JSON, the MD is rendered",
                "non_goals_and_done": "no UI; done when accept reads the list",
            },
        }
        path = self.root / "specs" / f"{self.NEW}.spec.json"
        write_json(path, data)
        (self.root / "pilot" / "worktrees" / self.NEW).mkdir(
            parents=True, exist_ok=True)
        return path

    def test_task_new_writes_default_acceptance_json_and_md(self) -> None:
        spec = self.write_spec()
        cp = self.cli("task-new", "--spec", str(spec))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["acceptance_json"],
                         f"tasks/{self.NEW}/ACCEPTANCE.json")
        self.assertEqual(payload["acceptance_md"],
                         f"tasks/{self.NEW}/ACCEPTANCE.md")
        data = self.acceptance(self.NEW)
        self.assertEqual(data["schema"], SCHEMA)
        self.assertEqual(data["items"],
                         [{"id": "A-01", "kind": "auto",
                           "status": "pending", "note": ""}])
        self.assertTrue((self.root / "tasks" / self.NEW / "ACCEPTANCE.md")
                        .is_file())

    def test_task_new_json_and_md_agree(self) -> None:
        spec = self.write_spec()
        cp = self.cli("task-new", "--spec", str(spec))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        items = self.acceptance(self.NEW)["items"]
        self.assertEqual(self.md_rows(self.NEW),
                         [[item["id"], item["kind"], item["status"],
                           item["note"]] for item in items])
        self.assertIn(f"# {self.NEW}", self.md_text(self.NEW))


class AcceptanceAddCase(AcceptanceKit):
    """``acceptance-add`` grows the list and never silently overwrites an id."""

    def test_auto_passed_and_manual_passed_items_are_appended(self) -> None:
        self.write_acceptance([{"id": "A-01", "kind": "auto",
                                "status": "pending", "note": ""}])
        auto = self.add("A-02", "auto", "passed", "suite green")
        self.assertEqual(auto.returncode, 0, msg=auto.stdout + auto.stderr)
        manual = self.add("M-01", "manual", "passed", "smoke test done")
        self.assertEqual(manual.returncode, 0, msg=manual.stdout + manual.stderr)
        items = self.acceptance()["items"]
        self.assertEqual([item["id"] for item in items],
                         ["A-01", "A-02", "M-01"])
        self.assertEqual(items[1]["status"], "passed")
        self.assertEqual(items[2]["kind"], "manual")
        self.assertEqual(self.md_rows(), [
            ["A-01", "auto", "pending", ""],
            ["A-02", "auto", "passed", "suite green"],
            ["M-01", "manual", "passed", "smoke test done"]])

    def test_duplicate_id_without_replace_is_refused_with_zero_writes(self) -> None:
        self.write_acceptance([{"id": "A-01", "kind": "auto",
                                "status": "passed", "note": ""}])
        before = self.snapshot()
        cp = self.add("A-01", "auto", "failed", "flaky")
        self.fails(cp, "already exists", "replace")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.acceptance()["items"][0]["status"], "passed")

    def test_replace_updates_status_and_note(self) -> None:
        self.write_acceptance([{"id": "M-01", "kind": "manual",
                                "status": "pending", "note": ""}])
        cp = self.add("M-01", "manual", "passed", "checked by hand", "--replace")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["replaced"])
        item = self.acceptance()["items"][0]
        self.assertEqual(item["status"], "passed")
        self.assertEqual(item["note"], "checked by hand")

    def test_replace_cannot_change_kind(self) -> None:
        self.write_acceptance([{"id": "A-01", "kind": "auto",
                                "status": "passed", "note": ""}])
        before = self.snapshot()
        cp = self.add("A-01", "manual", "passed", "reclassified", "--replace")
        self.fails(cp, "kind", "cannot change")
        self.assertEqual(self.snapshot(), before)

    def test_unknown_task_is_refused_with_zero_writes(self) -> None:
        before = self.snapshot()
        cp = self.cli("acceptance-add", "--task", "PILOT-999", "--id", "A-01",
                      "--kind", "auto", "--status", "passed")
        self.fails(cp, "record missing")
        self.assertFalse((self.root / "tasks" / "PILOT-999").exists())
        self.assertEqual(self.snapshot(), before)


class AcceptGateCase(AcceptanceKit):
    """The accept gate: auto passed, nothing failed, manual pending by owner."""

    def test_pending_auto_item_blocks_accept(self) -> None:
        self.write_acceptance([{"id": "A-01", "kind": "auto",
                                "status": "pending", "note": ""}])
        cp = self.accept()
        self.fails(cp, "A-01", "auto", "passed")
        self.assertFalse(self.accepted())
        self.assertIsNone(self.record_on_disk()["decision"])

    def test_manual_pending_without_flag_is_refused(self) -> None:
        self.write_acceptance([
            {"id": "A-01", "kind": "auto", "status": "passed", "note": ""},
            {"id": "M-01", "kind": "manual", "status": "pending",
             "note": "waits for the owner"}])
        cp = self.accept()
        self.fails(cp, "M-01", "manual pending", "allow-manual-pending")
        self.assertFalse(self.accepted())

    def test_manual_pending_with_flag_still_needs_a_note(self) -> None:
        self.write_acceptance([
            {"id": "A-01", "kind": "auto", "status": "passed", "note": ""},
            {"id": "M-01", "kind": "manual", "status": "pending",
             "note": "   "}])
        cp = self.accept("--allow-manual-pending")
        self.fails(cp, "M-01", "without a note")
        self.assertFalse(self.accepted())

    def test_manual_pending_with_flag_and_note_accepts(self) -> None:
        self.write_acceptance([
            {"id": "A-01", "kind": "auto", "status": "passed", "note": ""},
            {"id": "M-01", "kind": "manual", "status": "pending",
             "note": "owner runs the smoke test after merge"}])
        cp = self.accept("--allow-manual-pending")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["status"], "accepted")
        self.assertTrue(self.accepted())

    def test_failed_item_blocks_accept(self) -> None:
        self.write_acceptance([
            {"id": "A-01", "kind": "auto", "status": "passed", "note": ""},
            {"id": "A-02", "kind": "auto", "status": "failed",
             "note": "suite red"}])
        cp = self.accept()
        self.fails(cp, "A-02", "failed")
        self.assertFalse(self.accepted())

    def test_new_card_without_acceptance_file_is_refused(self) -> None:
        self.assertFalse(
            (self.root / "tasks" / self.TASK / "ACCEPTANCE.json").exists())
        cp = self.accept()
        self.fails(cp, "ACCEPTANCE.json")
        self.assertFalse(self.accepted())

    def test_legacy_card_without_acceptance_file_accepts(self) -> None:
        self.install_card("PILOT-042", created_at=LEGACY_STAMP)
        self.assertFalse(
            (self.root / "tasks" / "PILOT-042" / "ACCEPTANCE.json").exists())
        cp = self.cli("accept", "--task", "PILOT-042", "--decision", "D-059")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record_on_disk("PILOT-042")["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
