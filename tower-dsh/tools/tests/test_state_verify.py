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
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertTrue(out["ledger_errors"], out)
        self.assertTrue(any("hash mismatch" in error
                            for error in out["ledger_errors"]), out)


if __name__ == "__main__":
    unittest.main()
