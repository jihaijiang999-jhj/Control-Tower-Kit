"""PILOT-060: a repeated ``MERGE_START`` may retry from ``MERGING``.

The 056 failure: ``merge`` wrote ``MERGE_START`` and then aborted before the
actual merge because the working tree was dirty.  The retry wrote a second
``MERGE_START`` from the internal ``MERGING`` state; the old transition table
only allowed ``WAITING`` / ``CORRECTION_REQUIRED`` there, so ``state-verify``
reported ``illegal_transition`` and the real tower's drift never returned to
zero.

The contract pinned here:

* ``MERGE_START`` is legal from ``WAITING``, ``CORRECTION_REQUIRED`` and the
  internal ``MERGING`` state a retry replays from;
* ``DRAFT`` / ``MERGED`` / ``POST_MERGE_VERIFIED`` still cannot start a merge;
* ``ENVELOPE_NEW`` / ``QUEUE_ADD`` / ``MERGE`` keep their exact from-states;
* the 056 duplicate in the real tower history no longer produces an
  ``illegal_transition`` row.

Every case builds a throw-away tower root under the runner's ``TMP`` sandbox;
the state-verify cases drive the real CLI, exactly like the control plane does::

    python -B -m unittest tools.tests.test_envelope_retry -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import towerctl  # noqa: E402  (needs TOOLS_DIR on sys.path)

TCLI = TOOLS_DIR / "towerctl.py"
# The allowed from-states in ``_illegal_transition``'s sorted order.
MERGE_START_ALLOWED = ["CORRECTION_REQUIRED", "MERGING", "WAITING"]
ENVELOPE = "ENV-TEST-RETRY-001"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class EnvelopeRetryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-envelope-retry-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("ledger", "primary", "supervision",
                          "supervision/envelopes"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                    "tasks": []})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- builders ---------------------------------------------------------
    def append(self, event_type: str, envelope: str = ENVELOPE) -> dict:
        """Append one supervision lifecycle event with a real hash chain."""
        return towerctl.append_supervision_ledger(
            self.root, event_type, "supervision", {"envelope": envelope})

    def settle(self, status: str, envelope: str = ENVELOPE) -> None:
        """Write the queue entry and envelope file a settled status needs."""
        write_json(self.root / "supervision" / "envelopes" / f"{envelope}.json",
                   {"schema": "tower/merge-envelope@1",
                    "envelope_id": envelope, "status": status})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1",
                    "entries": [{"envelope_id": envelope, "task": "T-060",
                                 "status": status}]})

    def illegal_rows(self) -> list[dict]:
        transitions: list[dict] = []
        towerctl.replay_envelope_statuses(self.root, transitions)
        return [row for row in transitions
                if row["kind"] == "illegal_transition"]

    def state_verify(self, root: Path | None = None) -> tuple:
        cp = subprocess.run(
            [sys.executable, "-B", str(TCLI),
             "--root", str(root or self.root), "state-verify"],
            capture_output=True, text=True, encoding="utf-8")
        return cp, json.loads(cp.stdout)

    # -- 1. WAITING -> MERGING -> MERGING, and state-verify stays clean ----
    def test_waiting_retry_from_merging_is_legal_and_clean(self) -> None:
        self.append("ENVELOPE_NEW")
        self.append("QUEUE_ADD")
        self.append("MERGE_START")
        self.append("MERGE_START")  # the 056 retry
        self.settle("WAITING")

        self.assertEqual(self.illegal_rows(), [])
        # MERGE_START pins the internal state only: the folded status is still
        # the queued one, so a following MERGE is checked against MERGING.
        self.assertEqual(towerctl.replay_envelope_statuses(self.root),
                         {ENVELOPE: "WAITING"})
        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])
        self.assertEqual(payload["envelopes"], 1)

    # -- 2. CORRECTION_REQUIRED -> MERGING is still legal ------------------
    def test_correction_required_to_merging_still_legal(self) -> None:
        self.append("ENVELOPE_NEW")
        self.append("QUEUE_ADD")
        self.append("MERGE_START")
        self.append("MERGE_BLOCKED")
        self.append("MERGE_START")  # retry after the correction
        self.settle("CORRECTION_REQUIRED")

        self.assertEqual(self.illegal_rows(), [])
        self.assertEqual(towerctl.replay_envelope_statuses(self.root),
                         {ENVELOPE: "CORRECTION_REQUIRED"})
        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

    # -- 3. DRAFT / MERGED / POST_MERGE_VERIFIED still refuse MERGE_START --
    def test_draft_merged_and_verified_still_refused(self) -> None:
        history = {
            "ENV-TEST-DRAFT": ("ENVELOPE_NEW",),
            "ENV-TEST-MERGED": ("ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START",
                                "MERGE"),
            "ENV-TEST-VERIFIED": ("ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START",
                                  "MERGE", "POST_MERGE_VERIFIED"),
        }
        for envelope, events in history.items():
            for event_type in events:
                self.append(event_type, envelope=envelope)
            self.append("MERGE_START", envelope=envelope)

        self.assertEqual(self.illegal_rows(), [
            {"kind": "illegal_transition", "target": "ENV-TEST-DRAFT",
             "event": "MERGE_START", "expected": MERGE_START_ALLOWED,
             "actual": "DRAFT"},
            {"kind": "illegal_transition", "target": "ENV-TEST-MERGED",
             "event": "MERGE_START", "expected": MERGE_START_ALLOWED,
             "actual": "MERGED"},
            {"kind": "illegal_transition", "target": "ENV-TEST-VERIFIED",
             "event": "MERGE_START", "expected": MERGE_START_ALLOWED,
             "actual": "POST_MERGE_VERIFIED"},
        ])

    def test_transition_table_only_adds_the_retry(self) -> None:
        table = towerctl.ENVELOPE_TRANSITIONS
        self.assertEqual(table["MERGE_START"], frozenset(MERGE_START_ALLOWED))
        # The non-goals are pinned: nothing else was widened.
        self.assertEqual(table["ENVELOPE_NEW"],
                         frozenset({None, "DRAFT", "WAITING",
                                    "CORRECTION_REQUIRED"}))
        self.assertEqual(table["QUEUE_ADD"], frozenset({"DRAFT"}))
        self.assertEqual(table["MERGE"], frozenset({"MERGING"}))
        self.assertEqual(table["POST_MERGE_VERIFIED"],
                         frozenset({"MERGED", "CORRECTION_REQUIRED"}))

    # -- 4. the real 056 duplicate no longer reports illegal_transition ----
    def test_real_056_retry_has_no_illegal_transition(self) -> None:
        ledger = TOWER_ROOT / "ledger" / "supervision.jsonl"
        events = [json.loads(line) for line in
                  ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        starts = [event for event in events
                  if event.get("type") == "MERGE_START"
                  and isinstance(event.get("payload"), dict)
                  and event["payload"].get("envelope") == "ENV-PILOT-056"]
        self.assertGreaterEqual(len(starts), 2,
                                msg="056's duplicate MERGE_START is missing")

        transitions: list[dict] = []
        towerctl.replay_envelope_statuses(TOWER_ROOT, transitions)
        illegal = [row for row in transitions
                   if row["kind"] == "illegal_transition"]
        self.assertEqual([row for row in illegal
                          if row["target"] == "ENV-PILOT-056"], [])
        self.assertEqual(illegal, [])

        cp, payload = self.state_verify(root=TOWER_ROOT)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])


if __name__ == "__main__":
    unittest.main()
