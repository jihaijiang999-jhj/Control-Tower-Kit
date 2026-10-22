"""``state-verify``: replay both ledgers and report observed state drift.

Every test builds an isolated tower root with ``tempfile`` so the real tower
is never touched.  Ledger rows are appended through the real ``towerctl``
helpers (hash chain included) and the command under test is always driven
through the CLI, exactly like the control plane does.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class StateVerifyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-state-verify-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("ledger", "primary", "tasks",
                          "supervision", "supervision/envelopes"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- builders --------------------------------------------------------
    def primary(self, event_type: str, **payload) -> dict:
        return towerctl.append_ledger(
            self.root, event_type, "primary", payload)

    def supervision(self, event_type: str, **payload) -> dict:
        return towerctl.append_supervision_ledger(
            self.root, event_type, "supervision", payload)

    def put_record(self, task_id: str, status: str) -> None:
        write_json(self.root / "tasks" / task_id / "record.json",
                   {"schema": "tower/task@1", "id": task_id,
                    "title": task_id, "status": status})

    def write_board(self, statuses: dict[str, str]) -> None:
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                    "tasks": [{"id": task_id, "title": task_id,
                               "status": status}
                              for task_id, status in statuses.items()]})

    def write_queue(self, statuses: dict[str, str]) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1",
                    "entries": [{"envelope_id": envelope_id,
                                 "task": "T-001", "status": status}
                                for envelope_id, status in statuses.items()]})

    def put_envelope(self, envelope_id: str, status: str) -> None:
        write_json(self.root / "supervision" / "envelopes" / f"{envelope_id}.json",
                   {"schema": "tower/merge-envelope@1",
                    "envelope_id": envelope_id, "status": status})

    def write_raw(self, relative: str, text: str) -> None:
        """Write arbitrary bytes to a tower file (used for broken JSON)."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def remove_file(self, relative: str) -> None:
        (self.root / relative).unlink()

    # -- evidence/spec builders ------------------------------------------
    def write_evidence_file(self, relative: str, content: bytes) -> dict:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content)}

    def put_record_with_evidence(self, task_id: str, status: str,
                                 evidence, **extra) -> None:
        record = {"schema": "tower/task@1", "id": task_id,
                  "title": task_id, "status": status, "evidence": evidence}
        record.update(extra)
        write_json(self.root / "tasks" / task_id / "record.json", record)

    def put_spec(self, task_id: str,
                 content: bytes = b'{"spec": "frozen"}\n') -> dict:
        relative = f"pilot/{task_id}.spec.json"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"spec_path": relative,
                "spec_sha256": hashlib.sha256(content).hexdigest()}

    def build_evidence_tower(self) -> list[dict]:
        """Base tower plus three evidence files and a frozen spec.

        T-001 owns two evidence files and a spec; T-002 owns one evidence
        file.  The records keep the replayed statuses so evidence is the only
        variable under test.
        """
        self.build_base_tower()
        t1 = [
            self.write_evidence_file("tasks/T-001/evidence/one.txt",
                                     b"alpha\n"),
            self.write_evidence_file("tasks/T-001/evidence/two.bin",
                                     b"\x00\x01\x02"),
        ]
        t2 = [
            self.write_evidence_file("tasks/T-002/evidence/three.txt",
                                     b"gamma\n"),
        ]
        self.put_record_with_evidence("T-001", "closed", t1,
                                      **self.put_spec("T-001"))
        self.put_record_with_evidence("T-002", "reviewed", t2)
        return t1 + t2

    def read_record(self, task_id: str) -> dict:
        return json.loads((self.root / "tasks" / task_id / "record.json")
                          .read_text(encoding="utf-8"))

    def write_record(self, task_id: str, record: dict) -> None:
        write_json(self.root / "tasks" / task_id / "record.json", record)

    def build_base_tower(self) -> None:
        """Two consistent tasks and two consistent envelopes.

        T-001 is closed and T-002 only reviewed (CHECKBACK PASS, no ACCEPT),
        so the baseline also pins down the "no ACCEPT means not accepted"
        fold.  ENV-T-002 ends in CORRECTION_REQUIRED through POST_MERGE_FAILED
        after its MERGE.  Non-lifecycle events (SPEC_APPROVED / CHECK /
        TASK_NEXT / PHASE) are mixed in and must not change the replay.
        """
        for event_type in ("TASK_NEW", "SPEC_APPROVED", "CHECK", "DISPATCH",
                           "DELIVER"):
            self.primary(event_type, task="T-001")
        self.primary("CHECKBACK", task="T-001", verdict="PASS")
        self.primary("ACCEPT", task="T-001", decision="D-001")
        self.primary("CLOSEOUT", task="T-001", closeout="tasks/T-001/CLOSEOUT.md")
        self.primary("TASK_NEXT", task="T-001", next="merged")
        self.primary("PHASE", **{"from": "G2", "to": "G3", "next": "merge"})

        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
            self.primary(event_type, task="T-002")
        self.primary("CHECKBACK", task="T-002", verdict="PASS")

        for event_type in ("ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START"):
            self.supervision(event_type, envelope="ENV-T-001")
        self.supervision("MERGE", envelope="ENV-T-001", merge_commit="abc")
        self.supervision("POST_MERGE_VERIFIED", envelope="ENV-T-001")

        self.supervision("ENVELOPE_NEW", envelope="ENV-T-002")
        self.supervision("QUEUE_ADD", envelope="ENV-T-002")
        self.supervision("MERGE_START", envelope="ENV-T-002")
        self.supervision("MERGE", envelope="ENV-T-002", merge_commit="def")
        self.supervision("POST_MERGE_FAILED", envelope="ENV-T-002")

        self.put_record("T-001", "closed")
        self.put_record("T-002", "reviewed")
        self.write_board({"T-001": "closed", "T-002": "reviewed"})
        self.write_queue({"ENV-T-001": "POST_MERGE_VERIFIED",
                          "ENV-T-002": "CORRECTION_REQUIRED"})
        self.put_envelope("ENV-T-001", "POST_MERGE_VERIFIED")
        self.put_envelope("ENV-T-002", "CORRECTION_REQUIRED")

    # -- CLI -------------------------------------------------------------
    def state_verify(self) -> tuple[dict, int]:
        proc = subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "state-verify"],
            capture_output=True, text=True, encoding="utf-8")
        return json.loads(proc.stdout), proc.returncode

    def drift_kinds(self, out: dict) -> list[str]:
        return sorted(item["kind"] for item in out["drift"])

    def snapshot(self) -> dict[str, str]:
        """Relative path -> SHA-256 for every file under the tower root."""
        return {
            path.relative_to(self.root).as_posix(): hashlib.sha256(
                path.read_bytes()).hexdigest()
            for path in self.root.rglob("*") if path.is_file()
        }

    # -- 1. consistent tower --------------------------------------------
    def test_consistent_tower_exits_zero(self) -> None:
        self.build_base_tower()
        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["tasks"], 2)
        self.assertEqual(out["envelopes"], 2)

    # -- 2. record status drift -----------------------------------------
    def test_record_status_drift_is_reported(self) -> None:
        self.build_base_tower()
        # Keep the board on the replayed value so the only drift is the
        # record-vs-replay one under test.
        self.put_record("T-001", "rework")
        self.write_board({"T-001": "closed", "T-002": "reviewed"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertFalse(out["ok"], out)
        self.assertEqual(self.drift_kinds(out), ["task_status"])
        self.assertEqual(out["drift"][0]["target"], "T-001")
        self.assertEqual(out["drift"][0]["expected"], "closed")
        self.assertEqual(out["drift"][0]["actual"], "rework")

    # -- 2b. board expected value comes from the replay ------------------
    def test_record_and_board_same_wrong_value_report_both(self) -> None:
        self.build_base_tower()
        # Record and board agree with each other but both disagree with the
        # replay: board_status must compare against the replayed status, not
        # against record.status (otherwise it would be silently suppressed).
        self.put_record("T-001", "rework")
        self.write_board({"T-001": "rework", "T-002": "reviewed"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["board_status", "task_status"])
        by_kind = {item["kind"]: item for item in out["drift"]}
        self.assertEqual(by_kind["task_status"]["target"], "T-001")
        self.assertEqual(by_kind["task_status"]["expected"], "closed")
        self.assertEqual(by_kind["task_status"]["actual"], "rework")
        self.assertEqual(by_kind["board_status"]["target"], "T-001")
        self.assertEqual(by_kind["board_status"]["expected"], "closed",
                         "board_status.expected must be the replayed status")
        self.assertNotEqual(by_kind["board_status"]["expected"], "rework")
        self.assertEqual(by_kind["board_status"]["actual"], "rework")

    # -- 3. board status drift ------------------------------------------
    def test_board_status_drift_is_reported(self) -> None:
        self.build_base_tower()
        # The record still matches the replay; only the board lags behind.
        self.write_board({"T-001": "delivered", "T-002": "reviewed"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["board_status"])
        self.assertEqual(out["drift"][0]["target"], "T-001")
        self.assertEqual(out["drift"][0]["expected"], "closed")
        self.assertEqual(out["drift"][0]["actual"], "delivered")

    # -- 4. queue status drift ------------------------------------------
    def test_queue_status_drift_is_reported(self) -> None:
        self.build_base_tower()
        self.write_queue({"ENV-T-001": "WAITING",
                          "ENV-T-002": "CORRECTION_REQUIRED"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["queue_status"])
        self.assertEqual(out["drift"][0]["target"], "ENV-T-001")
        self.assertEqual(out["drift"][0]["expected"], "POST_MERGE_VERIFIED")
        self.assertEqual(out["drift"][0]["actual"], "WAITING")

    # -- 5. envelope file status drift ----------------------------------
    def test_envelope_status_drift_is_reported(self) -> None:
        self.build_base_tower()
        # Only the envelope file is touched; queue and replay still agree.
        self.put_envelope("ENV-T-002", "POST_MERGE_VERIFIED")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["envelope_status"])
        self.assertEqual(out["drift"][0]["target"], "ENV-T-002")
        self.assertEqual(out["drift"][0]["expected"], "CORRECTION_REQUIRED")
        self.assertEqual(out["drift"][0]["actual"], "POST_MERGE_VERIFIED")

    # -- 6. skip rules ---------------------------------------------------
    def test_entities_without_events_or_files_are_skipped(self) -> None:
        self.build_base_tower()
        # T-003 has a record and a board row but no primary events: skipped.
        self.put_record("T-003", "ready")
        # T-004 has a TASK_NEW event and a record but no board row: the board
        # comparison is skipped, the record still matches the replay.
        self.primary("TASK_NEW", task="T-004")
        self.put_record("T-004", "ready")
        # T-005 has events and a record but no board row: board comparison is
        # skipped (and reported), the record matches the replay.
        self.primary("TASK_NEW", task="T-005")
        self.put_record("T-005", "ready")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "ready"})
        # ENV-T-009 has a queue entry and an envelope file but no events:
        # skipped.
        self.write_queue({"ENV-T-001": "POST_MERGE_VERIFIED",
                          "ENV-T-002": "CORRECTION_REQUIRED",
                          "ENV-T-009": "WAITING"})
        self.put_envelope("ENV-T-009", "DRAFT")

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["tasks"], 4)
        self.assertEqual(out["envelopes"], 2)
        self.assertEqual(out["skipped"], [
            {"kind": "envelope", "target": "ENV-T-009",
             "reason": "no_lifecycle_events"},
            {"kind": "task", "target": "T-003",
             "reason": "no_lifecycle_events"},
            {"kind": "task", "target": "T-004",
             "reason": "board_entry_missing"},
            {"kind": "task", "target": "T-005",
             "reason": "board_entry_missing"},
        ])
        self.assertEqual(out["skipped_count"], 4)

    # -- 7. strict read-only proof --------------------------------------
    def test_state_verify_never_writes(self) -> None:
        self.build_base_tower()
        before = self.snapshot()
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before,
                         "state-verify changed files on a consistent tower")

        # A drifting tower must be reported, not repaired.
        self.put_record("T-001", "rework")
        self.write_board({"T-001": "rework", "T-002": "reviewed"})
        before = self.snapshot()
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.snapshot(), before,
                         "state-verify repaired drift instead of reporting it")
        self.assertEqual(out["drift"][0]["actual"], "rework")

    # -- 8. CHECKBACK FAIL folds to rework, never to accepted ------------
    def test_checkback_fail_replays_rework_not_accepted(self) -> None:
        self.build_base_tower()
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
            self.primary(event_type, task="T-003")
        self.primary("CHECKBACK", task="T-003", verdict="FAIL")
        self.put_record("T-003", "rework")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "rework"})

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)

        # No ACCEPT event was appended: the replay must stay at rework and a
        # record claiming "accepted" must be reported as drift against it.
        # The board stays on the replayed value so only the record drifts.
        self.put_record("T-003", "accepted")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "rework"})
        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["task_status"])
        self.assertEqual(out["drift"][0]["target"], "T-003")
        self.assertEqual(out["drift"][0]["expected"], "rework")
        self.assertEqual(out["drift"][0]["actual"], "accepted")

    # -- 9. correction folding and MERGE_START no-op ---------------------
    def test_correction_events_fold_and_merge_start_is_ignored(self) -> None:
        self.build_base_tower()
        # MERGE_BLOCKED also asks for a correction.
        self.supervision("ENVELOPE_NEW", envelope="ENV-T-003")
        self.supervision("QUEUE_ADD", envelope="ENV-T-003")
        self.supervision("MERGE_BLOCKED", envelope="ENV-T-003")
        # A later MERGE_START must not clear the correction.
        self.supervision("MERGE_START", envelope="ENV-T-003")
        self.put_envelope("ENV-T-003", "CORRECTION_REQUIRED")
        self.write_queue({"ENV-T-001": "POST_MERGE_VERIFIED",
                          "ENV-T-002": "CORRECTION_REQUIRED",
                          "ENV-T-003": "CORRECTION_REQUIRED"})

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["envelopes"], 3)

        # A retried merge followed by verification overrides the correction.
        self.supervision("MERGE", envelope="ENV-T-003", merge_commit="ghi")
        self.supervision("POST_MERGE_VERIFIED", envelope="ENV-T-003")
        self.put_envelope("ENV-T-003", "POST_MERGE_VERIFIED")
        self.write_queue({"ENV-T-001": "POST_MERGE_VERIFIED",
                          "ENV-T-002": "CORRECTION_REQUIRED",
                          "ENV-T-003": "POST_MERGE_VERIFIED"})

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])

    # -- 10. missing / unreadable record files --------------------------
    def test_deleted_record_is_record_missing(self) -> None:
        self.build_base_tower()
        self.remove_file("tasks/T-001/record.json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertFalse(out["ok"], out)
        self.assertEqual(self.drift_kinds(out), ["record_missing"])
        self.assertEqual(out["drift"][0], {
            "kind": "record_missing", "target": "T-001",
            "expected": "closed", "actual": None})
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["skipped_count"], 0)

    def test_broken_record_is_record_unreadable(self) -> None:
        self.build_base_tower()
        self.write_raw("tasks/T-001/record.json", "{not valid json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["record_unreadable"])
        self.assertEqual(out["drift"][0], {
            "kind": "record_unreadable", "target": "T-001",
            "expected": "closed", "actual": None})

        # A parseable but non-object record is just as unusable.
        write_json(self.root / "tasks" / "T-001" / "record.json", ["closed"])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["record_unreadable"])

    # -- 11. missing / unreadable board ---------------------------------
    def test_deleted_board_is_one_board_unreadable(self) -> None:
        self.build_base_tower()
        self.remove_file("primary/TASK_BOARD.json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["drift"], [{
            "kind": "board_unreadable", "target": "TASK_BOARD.json",
            "expected": "parseable JSON object", "actual": "missing"}])
        # No per-entity board noise and no board_entry_missing skip.
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["skipped_count"], 0)

    def test_broken_board_is_one_board_unreadable(self) -> None:
        self.build_base_tower()
        self.write_raw("primary/TASK_BOARD.json", "{not json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(out["drift"], [{
            "kind": "board_unreadable", "target": "TASK_BOARD.json",
            "expected": "parseable JSON object", "actual": "unparseable"}])

        # A parseable non-object board is unusable too: still exactly one.
        write_json(self.root / "primary" / "TASK_BOARD.json", [])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["board_unreadable"])
        self.assertEqual(out["drift"][0]["actual"], "unparseable")
        self.assertNotIn("board_status", self.drift_kinds(out))

    # -- 12. missing / unreadable queue ---------------------------------
    def test_deleted_queue_is_one_queue_unreadable(self) -> None:
        self.build_base_tower()
        self.remove_file("supervision/MERGE_QUEUE.json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(out["drift"], [{
            "kind": "queue_unreadable", "target": "MERGE_QUEUE.json",
            "expected": "parseable JSON object", "actual": "missing"}])
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["skipped_count"], 0)

    def test_broken_queue_is_one_queue_unreadable(self) -> None:
        self.build_base_tower()
        self.write_raw("supervision/MERGE_QUEUE.json", "{not json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(out["drift"], [{
            "kind": "queue_unreadable", "target": "MERGE_QUEUE.json",
            "expected": "parseable JSON object", "actual": "unparseable"}])
        self.assertNotIn("queue_status", self.drift_kinds(out))

    # -- 13. missing / unreadable envelope files ------------------------
    def test_deleted_envelope_is_envelope_missing(self) -> None:
        self.build_base_tower()
        self.remove_file("supervision/envelopes/ENV-T-001.json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["envelope_missing"])
        self.assertEqual(out["drift"][0], {
            "kind": "envelope_missing", "target": "ENV-T-001",
            "expected": "POST_MERGE_VERIFIED", "actual": None})

    def test_broken_envelope_is_envelope_unreadable(self) -> None:
        self.build_base_tower()
        self.write_raw("supervision/envelopes/ENV-T-001.json", "not json")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["envelope_unreadable"])
        self.assertEqual(out["drift"][0], {
            "kind": "envelope_unreadable", "target": "ENV-T-001",
            "expected": "POST_MERGE_VERIFIED", "actual": None})

    # -- 14. skipped output is informational only -----------------------
    def test_skipped_reports_no_events_and_missing_rows(self) -> None:
        self.build_base_tower()
        # T-003 replays but is absent from the board: board_entry_missing.
        for event_type in ("TASK_NEW", "DISPATCH"):
            self.primary(event_type, task="T-003")
        self.put_record("T-003", "dispatched")
        # T-004 only has a record: no_lifecycle_events.
        self.put_record("T-004", "ready")
        # ENV-T-003 replays but has no queue row: queue_entry_missing.
        self.supervision("ENVELOPE_NEW", envelope="ENV-T-003")
        self.put_envelope("ENV-T-003", "DRAFT")
        # ENV-T-009 only has a queue row and a file: no_lifecycle_events.
        self.write_queue({"ENV-T-001": "POST_MERGE_VERIFIED",
                          "ENV-T-002": "CORRECTION_REQUIRED",
                          "ENV-T-009": "WAITING"})
        self.put_envelope("ENV-T-009", "DRAFT")

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["tasks"], 3)
        self.assertEqual(out["envelopes"], 3)
        self.assertEqual(out["skipped"], [
            {"kind": "envelope", "target": "ENV-T-003",
             "reason": "queue_entry_missing"},
            {"kind": "envelope", "target": "ENV-T-009",
             "reason": "no_lifecycle_events"},
            {"kind": "task", "target": "T-003",
             "reason": "board_entry_missing"},
            {"kind": "task", "target": "T-004",
             "reason": "no_lifecycle_events"},
        ])
        self.assertEqual(out["skipped_count"], 4)

    # -- 15. read-only proof under bad files ----------------------------
    def test_state_verify_never_writes_with_bad_files(self) -> None:
        self.build_base_tower()
        self.remove_file("tasks/T-001/record.json")
        self.write_raw("primary/TASK_BOARD.json", "{broken board")
        self.write_raw("supervision/MERGE_QUEUE.json", "{broken queue")
        self.write_raw("supervision/envelopes/ENV-T-001.json", "not json")
        before = self.snapshot()

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.snapshot(), before,
                         "state-verify repaired bad files instead of "
                         "reporting them")
        for kind in ("board_unreadable", "envelope_unreadable",
                     "queue_unreadable", "record_missing"):
            self.assertIn(kind, self.drift_kinds(out))

    # -- 16. broken ledger short-circuits -------------------------------
    def test_broken_ledger_reports_errors_without_replay(self) -> None:
        self.build_base_tower()
        ledger = self.root / "ledger" / "primary.jsonl"
        events = [json.loads(line) for line in
                  ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        events[0]["payload"] = {"task": "T-001", "tampered": True}
        ledger.write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n"
                    for event in events),
            encoding="utf-8", newline="\n")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertFalse(out["ok"], out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["skipped_count"], 0)
        self.assertEqual(out["tasks"], 0)
        self.assertEqual(out["envelopes"], 0)
        self.assertEqual(out["evidence_checked"], 0)
        self.assertTrue(out["ledger_errors"], out)
        self.assertTrue(any("hash mismatch" in error
                            for error in out["ledger_errors"]), out)

    # -- 17. clean evidence + spec --------------------------------------
    def test_clean_evidence_and_spec_exit_zero(self) -> None:
        entries = self.build_evidence_tower()

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["evidence_checked"], 3)
        self.assertEqual(out["evidence_checked"], len(entries))

    # -- 18. rewritten evidence, same length ----------------------------
    def test_evidence_content_rewritten_same_length_is_hash_mismatch(self) -> None:
        self.build_evidence_tower()
        recorded = self.read_record("T-001")["evidence"][0]
        path = self.root / recorded["path"]
        path.write_bytes(b"ALPHA\n")
        self.assertEqual(path.stat().st_size, recorded["bytes"],
                         "fixture must keep the length so only the hash drifts")

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_hash_mismatch"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], recorded["path"])
        self.assertEqual(drift["expected"], recorded["sha256"])
        self.assertEqual(drift["actual"], hashlib.sha256(b"ALPHA\n").hexdigest())
        self.assertEqual(out["evidence_checked"], 3)

    # -- 19. the documented MAP blind spot: only record.sha256 changes --
    def test_record_sha256_only_changed_is_hash_mismatch(self) -> None:
        # The file is untouched, so only re-hashing the claimed path can
        # expose this: comparing record.sha256 with the package hash cannot.
        self.build_evidence_tower()
        record = self.read_record("T-001")
        entry = record["evidence"][0]
        actual = hashlib.sha256((self.root / entry["path"]).read_bytes()).hexdigest()
        wrong = "0" * 64
        self.assertNotEqual(wrong, actual)
        entry["sha256"] = wrong
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_hash_mismatch"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], entry["path"])
        self.assertEqual(drift["expected"], wrong)
        self.assertEqual(drift["actual"], actual)
        self.assertEqual(out["evidence_checked"], 3)

    # -- 20. deleted evidence -------------------------------------------
    def test_evidence_file_deleted_is_missing(self) -> None:
        self.build_evidence_tower()
        recorded = self.read_record("T-001")["evidence"][0]
        (self.root / recorded["path"]).unlink()

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_missing"])
        drift = out["drift"][0]
        self.assertEqual(drift["kind"], "evidence_missing")
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], recorded["path"])
        self.assertEqual(drift["actual"], "missing")
        self.assertEqual(out["evidence_checked"], 2,
                         "missing entries must not count as checked")

    # -- 21. bytes mismatch only ----------------------------------------
    def test_record_bytes_only_changed_is_bytes_mismatch(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-002")
        entry = record["evidence"][0]
        size = (self.root / entry["path"]).stat().st_size
        entry["bytes"] = size + 5
        self.write_record("T-002", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_bytes_mismatch"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-002")
        self.assertEqual(drift["path"], entry["path"])
        self.assertEqual(drift["expected"], size + 5)
        self.assertEqual(drift["actual"], size)
        self.assertEqual(out["evidence_checked"], 3)

    # -- 22. one file can yield both hash and bytes drift ---------------
    def test_hash_and_bytes_drift_can_both_be_reported(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        entry = record["evidence"][1]
        actual = hashlib.sha256((self.root / entry["path"]).read_bytes()).hexdigest()
        entry["sha256"] = "a" * 64
        self.assertNotEqual(entry["sha256"], actual)
        entry["bytes"] = entry["bytes"] + 7
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out),
                         ["evidence_bytes_mismatch", "evidence_hash_mismatch"])
        self.assertEqual({item["path"] for item in out["drift"]},
                         {entry["path"]})
        by_kind = {item["kind"]: item for item in out["drift"]}
        self.assertEqual(by_kind["evidence_hash_mismatch"]["actual"], actual)
        self.assertEqual(by_kind["evidence_bytes_mismatch"]["expected"],
                         entry["bytes"])
        self.assertEqual(out["evidence_checked"], 3)

    # -- 23. escaping evidence path is never opened ---------------------
    def test_evidence_path_escape_is_not_opened(self) -> None:
        self.build_evidence_tower()
        bait = self.root.parent / f"{self.root.name}-bait.txt"
        bait.write_bytes(b"bait-original\n")
        self.addCleanup(bait.unlink, missing_ok=True)
        before = bait.read_bytes()
        recorded_sha = self.read_record("T-001")["evidence"][0]["sha256"]

        record = self.read_record("T-001")
        record["evidence"][0]["path"] = f"../{bait.name}"
        record["evidence"][0]["sha256"] = recorded_sha
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_path_escape"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], f"../{bait.name}")
        self.assertEqual(bait.read_bytes(), before,
                         "state-verify hashed or wrote the escaped bait file")
        self.assertEqual(out["evidence_checked"], 2,
                         "escaped entries must not count as checked")
        self.assertTrue(bait.exists())

    # -- 24. absolute outside path is an escape too ---------------------
    def test_evidence_absolute_path_outside_is_escape(self) -> None:
        self.build_evidence_tower()
        bait = self.root.parent / f"{self.root.name}-abs-bait.txt"
        bait.write_bytes(b"absolute-bait\n")
        self.addCleanup(bait.unlink, missing_ok=True)
        before = bait.read_bytes()

        record = self.read_record("T-001")
        record["evidence"][0]["path"] = str(bait)
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_path_escape"])
        self.assertEqual(out["drift"][0]["path"], str(bait))
        self.assertEqual(bait.read_bytes(), before,
                         "state-verify hashed or wrote the escaped bait file")
        self.assertEqual(out["evidence_checked"], 2)

    # -- 25. malformed entries ------------------------------------------
    def test_non_dict_evidence_entry_is_unreadable(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        record["evidence"][0] = "not-an-entry"
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_unreadable"])
        self.assertEqual(out["drift"][0], {
            "kind": "evidence_unreadable", "target": "T-001", "path": None,
            "expected": "well-formed evidence entry", "actual": "invalid entry"})
        self.assertEqual(out["evidence_checked"], 2)

    def test_evidence_entry_without_path_is_unreadable(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        record["evidence"][0] = {"sha256": "a" * 64, "bytes": 1}
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_unreadable"])
        self.assertEqual(out["drift"][0]["path"], None)
        self.assertEqual(out["drift"][0]["actual"], "invalid path")
        self.assertEqual(out["evidence_checked"], 2)

        # An empty path is just as unusable.
        record = self.read_record("T-001")
        record["evidence"][0] = {"path": "", "sha256": "a" * 64}
        self.write_record("T-001", record)
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(out["drift"][0]["actual"], "invalid path")
        self.assertEqual(out["evidence_checked"], 2)

    def test_invalid_sha256_evidence_entry_is_unreadable(self) -> None:
        self.build_evidence_tower()
        recorded_path = self.read_record("T-001")["evidence"][0]["path"]
        for bad in (None, "abc", "z" * 64, "a" * 64 + "\n"):
            with self.subTest(sha256=bad):
                record = self.read_record("T-001")
                entry = record["evidence"][0]
                if bad is None:
                    entry.pop("sha256")
                else:
                    entry["sha256"] = bad
                self.write_record("T-001", record)

                out, code = self.state_verify()

                self.assertEqual(code, 2, out)
                self.assertEqual(self.drift_kinds(out), ["evidence_unreadable"])
                self.assertEqual(out["drift"][0]["path"], recorded_path)
                self.assertEqual(out["drift"][0]["actual"], "invalid sha256")
                self.assertEqual(out["evidence_checked"], 2)

    # -- 26. frozen spec integrity --------------------------------------
    def test_spec_modified_is_hash_mismatch(self) -> None:
        self.build_evidence_tower()
        recorded = self.read_record("T-001")["spec_sha256"]
        spec = self.root / "pilot" / "T-001.spec.json"
        spec.write_bytes(b'{"spec": "thawed"}\n')  # same length as the fixture

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["spec_hash_mismatch"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], "pilot/T-001.spec.json")
        self.assertEqual(drift["expected"], recorded)
        self.assertEqual(drift["actual"],
                         hashlib.sha256(b'{"spec": "thawed"}\n').hexdigest())
        self.assertEqual(out["evidence_checked"], 3)

    def test_spec_deleted_is_spec_missing(self) -> None:
        self.build_evidence_tower()
        (self.root / "pilot" / "T-001.spec.json").unlink()

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["spec_missing"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertEqual(drift["path"], "pilot/T-001.spec.json")
        self.assertEqual(drift["actual"], "missing")
        self.assertEqual(out["evidence_checked"], 3)

    def test_spec_path_escape_is_not_opened(self) -> None:
        self.build_evidence_tower()
        bait = self.root.parent / f"{self.root.name}-spec-bait.json"
        bait.write_bytes(b'{"spec": "outside"}\n')
        self.addCleanup(bait.unlink, missing_ok=True)
        before = bait.read_bytes()

        record = self.read_record("T-001")
        record["spec_path"] = f"../{bait.name}"
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["spec_path_escape"])
        self.assertEqual(out["drift"][0]["path"], f"../{bait.name}")
        self.assertEqual(bait.read_bytes(), before,
                         "state-verify hashed or wrote the escaped spec bait")
        self.assertEqual(out["evidence_checked"], 3)

    def test_spec_checked_only_when_both_fields_exist(self) -> None:
        self.build_evidence_tower()
        (self.root / "pilot" / "T-001.spec.json").write_bytes(b"tampered spec")
        record = self.read_record("T-001")
        record.pop("spec_sha256")
        self.write_record("T-001", record)

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["evidence_checked"], 3)

        record = self.read_record("T-001")
        record.pop("spec_path")
        record["spec_sha256"] = "0" * 64
        self.write_record("T-001", record)
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)

    # -- 27. absent/empty/non-list evidence is unchanged semantics ------
    def test_absent_empty_or_non_list_evidence_is_ignored(self) -> None:
        self.build_base_tower()  # records carry no evidence at all

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["evidence_checked"], 0)

        record = self.read_record("T-001")
        record["evidence"] = []
        self.write_record("T-001", record)
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["evidence_checked"], 0)

        # A non-list evidence value is not a list of entries: no checks, no
        # drift, even when it looks malicious.
        record["evidence"] = {"path": "../outside.txt", "sha256": "a" * 64}
        self.write_record("T-001", record)
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["evidence_checked"], 0)

    # -- 28. deterministic drift order ----------------------------------
    def test_evidence_drift_sorted_by_kind_target_path(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        for entry in record["evidence"]:
            (self.root / entry["path"]).unlink()
        record2 = self.read_record("T-002")
        record2["evidence"][0]["sha256"] = "0" * 64
        self.write_record("T-002", record2)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(
            [(item["kind"], item["target"], item["path"])
             for item in out["drift"]],
            [("evidence_hash_mismatch", "T-002",
              "tasks/T-002/evidence/three.txt"),
             ("evidence_missing", "T-001", "tasks/T-001/evidence/one.txt"),
             ("evidence_missing", "T-001", "tasks/T-001/evidence/two.bin")])
        self.assertEqual(out["evidence_checked"], 1)

    # -- 29. read-only proof with evidence and spec ---------------------
    def test_evidence_and_spec_verify_never_writes(self) -> None:
        self.build_evidence_tower()
        before = self.snapshot()
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before,
                         "state-verify changed files on a clean evidence tower")

        # Tampered evidence and spec must be reported, not repaired.
        (self.root / "tasks" / "T-001" / "evidence" / "one.txt").write_bytes(
            b"ALPHA\n")
        (self.root / "pilot" / "T-001.spec.json").write_bytes(
            b'{"spec": "thawed"}\n')
        before = self.snapshot()
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.snapshot(), before,
                         "state-verify repaired evidence/spec instead of "
                         "reporting it")
        self.assertEqual(self.drift_kinds(out),
                         ["evidence_hash_mismatch", "spec_hash_mismatch"])

    # -- 30. containment is lexical: zero filesystem access on escape ----
    def test_escape_path_never_touches_filesystem(self) -> None:
        self.build_evidence_tower()
        bait = self.root.parent / f"{self.root.name}-no-stat-bait.txt"
        bait.write_bytes(b"do-not-touch\n")
        self.addCleanup(bait.unlink, missing_ok=True)
        record = self.read_record("T-001")
        record["evidence"][0]["path"] = f"../{bait.name}"
        self.write_record("T-001", record)

        marker = bait.name
        touched: list[str] = []
        real_stat, real_lstat = os.stat, os.lstat
        real_open, real_io_open = os.open, io.open
        real_realpath, real_islink = os.path.realpath, os.path.islink

        def guard(name, original):
            def wrapper(path, *args, **kwargs):
                try:
                    text = os.fsdecode(path)
                except TypeError:
                    text = str(path)
                if marker in text:
                    touched.append(f"{name}:{text}")
                    raise AssertionError(
                        f"filesystem access ({name}) on escaping path: {text}")
                return original(path, *args, **kwargs)
            return wrapper

        with mock.patch("os.stat", guard("stat", real_stat)), \
                mock.patch("os.lstat", guard("lstat", real_lstat)), \
                mock.patch("os.open", guard("open", real_open)), \
                mock.patch("io.open", guard("io.open", real_io_open)), \
                mock.patch("os.path.realpath", guard("realpath", real_realpath)), \
                mock.patch("os.path.islink", guard("islink", real_islink)):
            result = towerctl.state_verify_drift(self.root)

        self.assertEqual(touched, [],
                         "the escaping path was stat'ed/opened/realpath'ed")
        self.assertEqual([item["kind"] for item in result["drift"]],
                         ["evidence_path_escape"])
        self.assertEqual(result["evidence_checked"], 2)

    # -- 31. NUL path cannot crash state-verify --------------------------
    def test_nul_byte_evidence_path_is_unreadable_not_crash(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        record["evidence"][0]["path"] = "tasks/T-001/evidence/one\x00.txt"
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertFalse(out["ok"], out)
        self.assertEqual(self.drift_kinds(out), ["evidence_unreadable"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "T-001")
        self.assertIsNone(drift["path"])
        self.assertEqual(drift["actual"], "invalid path")
        self.assertEqual(out["evidence_checked"], 2)

    def test_nul_byte_spec_path_is_unreadable_not_crash(self) -> None:
        self.build_evidence_tower()
        record = self.read_record("T-001")
        record["spec_path"] = "pilot/T-001\x00.spec.json"
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["spec_unreadable"])
        self.assertIsNone(out["drift"][0]["path"])
        self.assertEqual(out["drift"][0]["actual"], "invalid path")
        self.assertEqual(out["evidence_checked"], 3)

    # -- 32. a symlinked candidate is rejected, never followed -----------
    def test_symlink_escape_is_reported_without_hashing(self) -> None:
        self.build_evidence_tower()
        bait = self.root.parent / f"{self.root.name}-symlink-bait.txt"
        bait.write_bytes(b"symlink-bait\n")
        self.addCleanup(bait.unlink, missing_ok=True)
        before = bait.read_bytes()
        link = self.root / "tasks" / "T-001" / "evidence" / "link.txt"
        try:
            link.symlink_to(bait)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"platform refuses symlink creation: {exc}")
        self.addCleanup(link.unlink, missing_ok=True)

        record = self.read_record("T-001")
        record["evidence"][0]["path"] = "tasks/T-001/evidence/link.txt"
        self.write_record("T-001", record)

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["evidence_path_escape"])
        self.assertEqual(out["drift"][0]["path"],
                         "tasks/T-001/evidence/link.txt")
        self.assertEqual(bait.read_bytes(), before,
                         "state-verify followed the symlink and hashed outside")
        self.assertEqual(out["evidence_checked"], 2)

    # -- 33. illegal task transitions ------------------------------------
    def illegal_transitions(self, out: dict) -> list[dict]:
        return [item for item in out["drift"]
                if item["kind"] == "illegal_transition"]

    def test_closeout_after_task_new_is_illegal_transition(self) -> None:
        # ∅10's blind spot: replay is last-writer-wins, so without transition
        # checks TASK_NEW -> CLOSEOUT would simply fold to "closed".
        self.build_base_tower()
        self.primary("TASK_NEW", task="T-003")
        self.primary("CLOSEOUT", task="T-003")
        self.put_record("T-003", "closed")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "closed"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": "T-003",
            "event": "CLOSEOUT", "expected": ["accepted"],
            "actual": "ready"}])
        self.assertNotIn("path", self.illegal_transitions(out)[0])
        # The replay itself is unchanged: it still folds to "closed".
        self.assertEqual(self.drift_kinds(out), ["illegal_transition"])

    def test_accept_without_reviewed_checkback_is_illegal(self) -> None:
        self.build_base_tower()
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER", "ACCEPT"):
            self.primary(event_type, task="T-003")
        self.put_record("T-003", "accepted")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "accepted"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": "T-003",
            "event": "ACCEPT", "expected": ["reviewed"],
            "actual": "delivered"}])
        self.assertEqual(self.drift_kinds(out), ["illegal_transition"])

    # -- 34. illegal envelope transitions --------------------------------
    def test_merge_without_merge_start_is_illegal(self) -> None:
        self.write_board({})
        self.supervision("ENVELOPE_NEW", envelope="ENV-T-003")
        self.supervision("QUEUE_ADD", envelope="ENV-T-003")
        self.supervision("MERGE", envelope="ENV-T-003", merge_commit="abc")
        self.put_envelope("ENV-T-003", "MERGED")
        self.write_queue({"ENV-T-003": "MERGED"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": "ENV-T-003",
            "event": "MERGE", "expected": ["MERGING"],
            "actual": "WAITING"}])
        self.assertEqual(out["envelopes"], 1)

    def test_post_merge_verified_from_waiting_is_illegal(self) -> None:
        self.write_board({})
        self.supervision("ENVELOPE_NEW", envelope="ENV-T-003")
        self.supervision("QUEUE_ADD", envelope="ENV-T-003")
        self.supervision("POST_MERGE_VERIFIED", envelope="ENV-T-003")
        self.put_envelope("ENV-T-003", "POST_MERGE_VERIFIED")
        self.write_queue({"ENV-T-003": "POST_MERGE_VERIFIED"})

        out, code = self.state_verify()

        self.assertEqual(code, 2, out)
        self.assertEqual(self.illegal_transitions(out), [{
            "kind": "illegal_transition", "target": "ENV-T-003",
            "event": "POST_MERGE_VERIFIED",
            "expected": ["CORRECTION_REQUIRED", "MERGED"],
            "actual": "WAITING"}])

    # -- 35. real-ledger precedents stay legal --------------------------
    def test_task_new_rebuild_from_dispatched_is_legal(self) -> None:
        # PILOT-025 precedent: a rebuilt card starts over with TASK_NEW.
        self.build_base_tower()
        for event_type in ("TASK_NEW", "DISPATCH", "TASK_NEW"):
            self.primary(event_type, task="T-003")
        self.put_record("T-003", "ready")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "ready"})

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(self.illegal_transitions(out), [])

    def test_redelivery_from_delivered_is_legal(self) -> None:
        # PILOT-001 precedent: DELIVER landed twice on a delivered card.
        self.build_base_tower()
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER", "DELIVER"):
            self.primary(event_type, task="T-003")
        self.put_record("T-003", "delivered")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "delivered"})

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])

    def test_correction_retry_transitions_are_legal(self) -> None:
        # MERGE_START from CORRECTION_REQUIRED and POST_MERGE_VERIFIED from
        # CORRECTION_REQUIRED are both real retry shapes.
        self.write_board({})
        for event_type in ("ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START"):
            self.supervision(event_type, envelope="ENV-T-003")
        self.supervision("MERGE", envelope="ENV-T-003", merge_commit="abc")
        self.supervision("POST_MERGE_FAILED", envelope="ENV-T-003")
        self.supervision("MERGE_START", envelope="ENV-T-003")
        self.supervision("MERGE", envelope="ENV-T-003", merge_commit="def")
        self.supervision("POST_MERGE_VERIFIED", envelope="ENV-T-003")

        for event_type in ("ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START"):
            self.supervision(event_type, envelope="ENV-T-004")
        self.supervision("MERGE", envelope="ENV-T-004", merge_commit="ghi")
        self.supervision("POST_MERGE_FAILED", envelope="ENV-T-004")
        self.supervision("POST_MERGE_VERIFIED", envelope="ENV-T-004")

        for envelope_id in ("ENV-T-003", "ENV-T-004"):
            self.put_envelope(envelope_id, "POST_MERGE_VERIFIED")
        self.write_queue({"ENV-T-003": "POST_MERGE_VERIFIED",
                          "ENV-T-004": "POST_MERGE_VERIFIED"})

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["envelopes"], 2)

    # -- 36. unknown events are ignored ---------------------------------
    def test_unknown_event_types_are_ignored(self) -> None:
        self.build_base_tower()
        self.primary("TASK_NEW", task="T-003")
        self.primary("MYSTERY_EVENT", task="T-003")
        self.supervision("MYSTERY_ENVELOPE_EVENT", envelope="ENV-T-003")
        self.put_record("T-003", "ready")
        self.write_board({"T-001": "closed", "T-002": "reviewed",
                          "T-003": "ready"})

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(out["tasks"], 3)
        self.assertEqual(out["envelopes"], 2)

    # -- 37. clean full tower: every transition is inside the tables -----
    def test_clean_tower_has_no_illegal_transition(self) -> None:
        self.build_base_tower()

        out, code = self.state_verify()

        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual(self.illegal_transitions(out), [])


if __name__ == "__main__":
    unittest.main()
