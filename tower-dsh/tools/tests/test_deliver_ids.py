"""Regression tests for evidence ids assigned by ``towerctl deliver``.

``deliver`` replaces the entry for an already-recorded path before appending
the new one, so the list length does not grow on a re-delivery.  Numbering
from that length while appending therefore reused an id (PILOT-017 ended up
with six ``E-006`` entries).  These tests build an isolated tower root and
drive the real CLI through ``subprocess``, asserting that every delivery
leaves a contiguous, unique ``E-001..E-00N`` sequence in list order.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
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
TASK_ID = "TEST-001"
FIXED_TIME = "2026-10-19T00:00:00+08:00"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliverIdsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-deliver-ids-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for d in ("primary", "ledger", "work", f"tasks/{TASK_ID}/evidence"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / "primary" / "CURRENT_STATE.json").write_text(
            json.dumps({
                "schema": "tower/current-state@1",
                "role": "primary",
                "primary": {"id": "ctl-test"},
                "owner": {"name": "mac"},
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.root / "primary" / "TASK_BOARD.json").write_text(
            json.dumps({"schema": "tower/task-board@1", "tasks": []},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")
        self.record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "deliver id regression",
            "status": "dispatched",
            "authority": "workspace_write",
            "scope": ["exercise deliver evidence ids"],
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "executor": "exec-a",
            "dispatch": {"executor": "exec-a", "worktree": None, "at": FIXED_TIME},
            "evidence": [],
            "review": None,
            "decision": None,
            "closeout": None,
            "created_at": FIXED_TIME,
            "updated_at": FIXED_TIME,
            "next": "等待 executor 交付",
        }
        self.write_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixtures ---------------------------------------------------------
    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        path = self.root / "tasks" / TASK_ID / "record.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.record = data

    def load_record(self) -> dict:
        path = self.root / "tasks" / TASK_ID / "record.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def write_source(self, name: str, text: str) -> Path:
        path = self.root / "work" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8",
        )

    def deliver(self, *names: str) -> subprocess.CompletedProcess:
        args = ["deliver", "--task", TASK_ID]
        for name in names:
            args += ["--evidence", f"work/{name}"]
        cp = self.run_cli(*args)
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        return cp

    def delivery_lines(self) -> list[list[str]]:
        text = (self.root / "tasks" / TASK_ID / "DELIVERY.md").read_text(
            encoding="utf-8")
        rows = []
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0].startswith("E-"):
                rows.append(cells)
        return rows

    # -- 1. the same path delivered twice keeps a single id -------------
    def test_same_path_delivered_twice_keeps_one_id(self) -> None:
        self.write_source("proof.txt", "first version\n")
        first = self.deliver("proof.txt")
        payload = json.loads(first.stdout)
        self.assertTrue({"ok", "task", "status", "evidence"} <= set(payload))
        self.assertEqual(payload.get("scope_check"), "skipped (no git repo)")
        record = self.load_record()
        self.assertEqual([e["id"] for e in record["evidence"]], ["E-001"])

        self.write_source("proof.txt", "second version\n")
        self.deliver("proof.txt")
        record = self.load_record()
        self.assertEqual(len(record["evidence"]), 1)
        self.assertEqual([e["id"] for e in record["evidence"]], ["E-001"])
        self.assertEqual(record["evidence"][0]["sha256"],
                         sha256_file(self.root / "work" / "proof.txt"))

    # -- 2. three files in one delivery are numbered in argument order ---
    def test_three_files_in_one_delivery_are_numbered_in_order(self) -> None:
        sources = {name: self.write_source(name, f"{name}\n")
                   for name in ("a.txt", "b.txt", "c.txt")}
        self.deliver("a.txt", "b.txt", "c.txt")
        evidence = self.load_record()["evidence"]
        self.assertEqual([e["id"] for e in evidence],
                         ["E-001", "E-002", "E-003"])
        self.assertEqual([e["path"] for e in evidence],
                         [f"tasks/{TASK_ID}/evidence/{name}"
                          for name in ("a.txt", "b.txt", "c.txt")])
        for entry, (name, source) in zip(evidence, sources.items()):
            self.assertEqual(entry["sha256"], sha256_file(source),
                             msg=f"hash mismatch for {name}")
            self.assertEqual(entry["bytes"], source.stat().st_size,
                             msg=f"size mismatch for {name}")

    # -- 3. a changed re-delivery keeps the count and refreshes the hash --
    def test_redelivery_after_content_change_updates_hash_only(self) -> None:
        self.write_source("report.txt", "v1\n")
        self.deliver("report.txt")
        old_sha = self.load_record()["evidence"][0]["sha256"]

        self.write_source("report.txt", "v2, longer than v1\n")
        self.deliver("report.txt")
        evidence = self.load_record()["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual([e["id"] for e in evidence], ["E-001"])
        self.assertNotEqual(evidence[0]["sha256"], old_sha)
        self.assertEqual(evidence[0]["sha256"],
                         sha256_file(self.root / "work" / "report.txt"))
        self.assertEqual(evidence[0]["bytes"],
                         (self.root / "work" / "report.txt").stat().st_size)

    # -- 4. mixed re-delivery stays contiguous and matches DELIVERY.md ---
    def test_redelivery_mixed_order_keeps_ids_unique_and_delivery_consistent(
            self) -> None:
        self.write_source("a.txt", "A\n")
        self.write_source("b.txt", "B\n")
        self.deliver("a.txt")
        self.deliver("b.txt")
        self.write_source("a.txt", "A again\n")
        self.deliver("a.txt")

        record = self.load_record()
        evidence = record["evidence"]
        ids = [e["id"] for e in evidence]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(len(ids), len(set(ids)), msg=f"duplicate ids: {ids}")
        self.assertEqual(ids, [f"E-{i:03d}" for i in range(1, len(ids) + 1)])
        self.assertEqual({e["path"] for e in evidence},
                         {f"tasks/{TASK_ID}/evidence/a.txt",
                          f"tasks/{TASK_ID}/evidence/b.txt"})

        rows = self.delivery_lines()
        self.assertEqual([row[0] for row in rows], ids)
        for row, entry in zip(rows, evidence):
            self.assertEqual(row[1], f"`{entry['path']}`")
            self.assertEqual(row[2], f"`{entry['sha256']}`")

    # -- 5. a record with legacy duplicate ids is renumbered on delivery --
    def test_delivery_repairs_legacy_duplicate_ids(self) -> None:
        legacy = []
        for index, name in enumerate(("one.txt", "two.txt"), start=1):
            dest = self.root / "tasks" / TASK_ID / "evidence" / name
            dest.write_text(f"legacy {index}\n", encoding="utf-8")
            legacy.append({
                "id": "E-006",
                "path": f"tasks/{TASK_ID}/evidence/{name}",
                "sha256": sha256_file(dest),
                "bytes": dest.stat().st_size,
                "at": FIXED_TIME,
            })
        self.write_record(status="delivered", evidence=legacy)
        self.write_source("new.txt", "new\n")
        self.deliver("new.txt")

        ids = [e["id"] for e in self.load_record()["evidence"]]
        self.assertEqual(ids, ["E-001", "E-002", "E-003"])
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
