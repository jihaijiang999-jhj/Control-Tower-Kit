"""PILOT-062: ``envelope-abandon`` -- the supervisor tombstone.

043's envelope is stuck at ``CORRECTION_REQUIRED`` with its queue entry still
present, and no legal exit existed: deleting the queue/ledger rows is
forbidden, and a merged envelope can never be reopened.  This card adds one
explicit exit::

    towerctl envelope-abandon --envelope <ENV> --reason <text> [--by <owner>]

Only the merge authority (never the primary) may invoke it.  A live envelope
(``WAITING`` / ``CORRECTION_REQUIRED`` / ``MERGE_BLOCKED`` / ``MERGING``)
becomes ``ABANDONED`` on the envelope file and on its queue entry, and one
append-only ``ENVELOPE_ABANDON`` supervision event records envelope, reason,
by and at.  ``MERGED`` / ``POST_MERGE_VERIFIED`` are refused with zero writes,
and a repeated abandon is idempotent with zero writes.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_envelope_abandon -v
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
TASK = "PILOT-062"
ENVELOPE = "ENV-PILOT-062"
SUPERVISOR = "sup-062"
PRIMARY = "ctl-062"
ABANDON = "ENVELOPE_ABANDON"
LEDGER_REL = ("ledger", "supervision.jsonl")
QUEUE_REL = ("supervision", "MERGE_QUEUE.json")

# The ledger history that folds to each source status.  ``MERGING`` keeps the
# envelope at WAITING (MERGE_START only pins the internal state) while its queue
# entry is MERGING, exactly like a merge that died after MERGE_START.
SOURCES = {
    "WAITING": ("WAITING", "WAITING",
                ["ENVELOPE_NEW", "QUEUE_ADD"]),
    "CORRECTION_REQUIRED": ("CORRECTION_REQUIRED", "CORRECTION_REQUIRED",
                            ["ENVELOPE_NEW", "QUEUE_ADD", "MERGE_BLOCKED"]),
    "MERGING": ("WAITING", "MERGING",
                ["ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START"]),
    "MERGED": ("MERGED", "MERGED",
               ["ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START", "MERGE"]),
    "POST_MERGE_VERIFIED": (
        "POST_MERGE_VERIFIED", "POST_MERGE_VERIFIED",
        ["ENVELOPE_NEW", "QUEUE_ADD", "MERGE_START", "MERGE",
         "POST_MERGE_VERIFIED"]),
}


def dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class AbandonCase(unittest.TestCase):
    """A bare tower root (no git): the tombstone is a pure state transition."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-abandon-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        dump(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "TEST", "owner": {"name": "mac"},
            "primary": {"id": PRIMARY},
        })
        dump(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "TEST",
            "supervisor": {"id": SUPERVISOR},
        })
        dump(self.root / "primary" / "TASK_BOARD.json",
             {"schema": "tower/task-board@1", "tasks": []})
        dump(self.root / "supervision" / "MERGE_QUEUE.json",
             {"schema": "tower/merge-queue@1", "entries": []})
        for name in ("primary.jsonl", "supervision.jsonl"):
            (self.root / "ledger" / name).write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ---------------------------------------------------------
    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"

    def queue_path(self) -> Path:
        return self.root.joinpath(*QUEUE_REL)

    def ledger_path(self) -> Path:
        return self.root.joinpath(*LEDGER_REL)

    def seed(self, source: str, queue_status: str | None = None) -> None:
        """Write one consistent envelope/queue/ledger triple from ``SOURCES``."""
        env_status, entry_status, events = SOURCES[source]
        for event in events:
            towerctl.append_supervision_ledger(
                self.root, event, "primary" if event.startswith("ENVELOPE")
                else "supervision",
                {"envelope": ENVELOPE, "task": TASK, "head": "a" * 40})
        dump(self.envelope_path(), {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "status": env_status, "merge_commit": "b" * 40,
        })
        dump(self.queue_path(), {"schema": "tower/merge-queue@1", "entries": [{
            "envelope_id": ENVELOPE, "task": TASK, "status":
            queue_status or entry_status, "added_at": "2026-11-02T00:00:00+08:00",
        }]})

    def seed_draft(self) -> None:
        towerctl.append_supervision_ledger(
            self.root, "ENVELOPE_NEW", "primary",
            {"envelope": ENVELOPE, "task": TASK})
        towerctl.append_supervision_ledger(
            self.root, "QUEUE_ADD", "primary",
            {"envelope": ENVELOPE, "task": TASK})
        dump(self.envelope_path(), {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "status": "DRAFT"})

    # -- CLI / state accessors -------------------------------------------
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    def abandon(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("envelope-abandon", "--envelope", ENVELOPE,
                        "--reason", "043 tombstone", *extra)

    def envelope(self) -> dict:
        return json.loads(self.envelope_path().read_text(encoding="utf-8"))

    def entry(self) -> dict:
        queue = json.loads(self.queue_path().read_text(encoding="utf-8"))
        return next(item for item in queue["entries"]
                    if item["envelope_id"] == ENVELOPE)

    def events(self, event_type: str | None = None) -> list[dict]:
        rows = [json.loads(line) for line in
                self.ledger_path().read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return [row for row in rows
                if event_type is None or row.get("type") == event_type]

    def state_verify(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.cli("state-verify")
        return cp, json.loads(cp.stdout)

    def assert_verify_clean(self) -> None:
        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

    def snapshot(self) -> tuple[bytes, bytes, bytes]:
        return (self.envelope_path().read_bytes(),
                self.queue_path().read_bytes(),
                self.ledger_path().read_bytes())

    def assert_refused(self, cp: subprocess.CompletedProcess,
                       before: tuple[bytes, bytes, bytes]) -> None:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertFalse(json.loads(cp.stdout)["ok"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.events(ABANDON), [])

    # -- 1. each live source status is abandonable -----------------------
    def test_waiting_envelope_becomes_abandoned_on_every_layer(self) -> None:
        self.seed("WAITING")
        cp = self.abandon("--by", SUPERVISOR)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "ABANDONED")
        self.assertEqual(self.entry()["status"], "ABANDONED")
        tombstones = self.events(ABANDON)
        self.assertEqual(len(tombstones), 1)
        payload = tombstones[0]["payload"]
        self.assertEqual(sorted(payload), ["at", "by", "envelope", "reason"])
        self.assertEqual(payload["envelope"], ENVELOPE)
        self.assertEqual(payload["reason"], "043 tombstone")
        self.assertEqual(payload["by"], SUPERVISOR)
        # History is kept: the queue entry and every earlier event remain.
        self.assertEqual([row["type"] for row in self.events()],
                         ["ENVELOPE_NEW", "QUEUE_ADD", ABANDON])
        self.assert_verify_clean()

    def test_correction_required_envelope_is_abandoned(self) -> None:
        self.seed("CORRECTION_REQUIRED")
        cp = self.abandon("--by", SUPERVISOR)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "ABANDONED")
        self.assertEqual(self.entry()["status"], "ABANDONED")
        self.assert_verify_clean()

    def test_envelope_merging_after_merge_start_is_abandoned(self) -> None:
        self.seed("MERGING")
        # A crashed merge leaves the queue at MERGING before the tombstone.
        self.assertEqual(self.entry()["status"], "MERGING")
        cp = self.abandon("--by", SUPERVISOR)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "ABANDONED")
        self.assertEqual(self.entry()["status"], "ABANDONED")
        self.assert_verify_clean()

    def test_merging_source_is_legal_in_the_transition_table(self) -> None:
        self.seed("MERGING")
        self.assertEqual(self.abandon("--by", SUPERVISOR).returncode, 0)
        transitions: list[dict] = []
        towerctl.replay_envelope_statuses(self.root, transitions)
        self.assertEqual([row for row in transitions
                          if row["kind"] == "illegal_transition"], [])

    # -- 2. terminal statuses are refused with zero writes ---------------
    def test_merged_envelope_is_refused_with_zero_writes(self) -> None:
        self.seed("MERGED")
        before = self.snapshot()
        cp = self.abandon("--by", SUPERVISOR)
        self.assert_refused(cp, before)
        self.assertIn("cannot be abandoned", cp.stdout)
        self.assertIn("MERGED", cp.stdout)

    def test_post_merge_verified_envelope_is_refused_with_zero_writes(self) -> None:
        self.seed("POST_MERGE_VERIFIED")
        before = self.snapshot()
        cp = self.abandon("--by", SUPERVISOR)
        self.assert_refused(cp, before)
        self.assertIn("cannot be abandoned", cp.stdout)
        self.assertIn("POST_MERGE_VERIFIED", cp.stdout)

    # -- 3. a repeated abandon is idempotent ------------------------------
    def test_repeated_abandon_is_idempotent_and_never_duplicates(self) -> None:
        self.seed("WAITING")
        first = self.abandon("--by", SUPERVISOR)
        self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
        before = self.snapshot()
        second = self.abandon("--by", SUPERVISOR)
        self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
        self.assertTrue(json.loads(second.stdout)["already"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.events(ABANDON)), 1)

    # -- 4. only the pinned merge authority may abandon -------------------
    def test_configured_authority_refuses_strangers_and_the_primary(self) -> None:
        cp = self.cli("authority-set", "--supervisor", SUPERVISOR,
                      "--decision", "D-PILOT-062", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.seed("WAITING")
        before = self.snapshot()
        stranger = self.abandon("--by", "someone-else")
        self.assert_refused(stranger, before)
        self.assertIn("may abandon", stranger.stdout)
        primary = self.abandon("--by", PRIMARY)
        self.assert_refused(primary, before)
        self.assertIn("primary cannot abandon", primary.stdout)
        self.assertEqual(self.abandon().returncode, 0)  # --by defaults to pin
        self.assert_verify_clean()

    def test_legacy_tower_accepts_only_its_registered_supervisor(self) -> None:
        self.seed("WAITING")
        before = self.snapshot()
        stranger = self.abandon("--by", "someone-else")
        self.assert_refused(stranger, before)
        self.assertIn(SUPERVISOR, stranger.stdout)
        self.assertEqual(self.abandon().returncode, 0)
        self.assert_verify_clean()

    # -- 5. non-live / unqueued envelopes are refused --------------------
    def test_draft_and_unqueued_envelopes_are_refused(self) -> None:
        self.seed_draft()
        entry = {"envelope_id": ENVELOPE, "task": TASK, "status": "WAITING",
                 "added_at": "2026-11-02T00:00:00+08:00"}
        dump(self.queue_path(), {"schema": "tower/merge-queue@1",
                                 "entries": [entry]})
        before = self.snapshot()
        draft = self.abandon("--by", SUPERVISOR)
        self.assert_refused(draft, before)
        self.assertIn("cannot be abandoned", draft.stdout)
        dump(self.queue_path(), {"schema": "tower/merge-queue@1",
                                 "entries": []})
        before = self.snapshot()
        unqueued = self.abandon("--by", SUPERVISOR)
        self.assert_refused(unqueued, before)
        self.assertIn("not queued", unqueued.stdout)

    # -- 6. catalog + replay agree, and the table is not widened ---------
    def test_catalog_and_replay_cover_envelope_abandon(self) -> None:
        catalog = json.loads((TOWER_ROOT / "EVENT_CATALOG.json").read_text(
            encoding="utf-8"))
        entries = [item for item in catalog["events"]
                   if item["type"] == ABANDON]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ledger"], "supervision")
        self.assertEqual(entries[0]["producer"], "envelope-abandon")
        self.assertIs(entries[0]["state_verify"], True)
        self.assertEqual(sorted(entries[0]["payload_required"]),
                         ["at", "by", "envelope", "reason"])

        rows = [
            ("ENV-A", "ENVELOPE_NEW"), ("ENV-A", "QUEUE_ADD"),
            ("ENV-A", ABANDON),
            ("ENV-B", "ENVELOPE_NEW"), ("ENV-B", "QUEUE_ADD"),
            ("ENV-B", "MERGE_BLOCKED"), ("ENV-B", ABANDON),
            ("ENV-C", "ENVELOPE_NEW"), ("ENV-C", "QUEUE_ADD"),
            ("ENV-C", "MERGE_START"), ("ENV-C", ABANDON),
            ("ENV-D", "ENVELOPE_NEW"), ("ENV-D", "QUEUE_ADD"),
            ("ENV-D", "MERGE_START"), ("ENV-D", "MERGE"), ("ENV-D", ABANDON),
        ]
        self.ledger_path().write_text("".join(
            json.dumps({"seq": index, "type": event_type,
                        "payload": {"envelope": envelope}}) + "\n"
            for index, (envelope, event_type) in enumerate(rows, 1)),
            encoding="utf-8")
        states = towerctl.replay_envelope_statuses(self.root)
        self.assertEqual(states, {"ENV-A": "ABANDONED", "ENV-B": "ABANDONED",
                                  "ENV-C": "ABANDONED", "ENV-D": "ABANDONED"})
        transitions: list[dict] = []
        towerctl.replay_envelope_statuses(self.root, transitions)
        illegal = [row["target"] for row in transitions
                   if row["kind"] == "illegal_transition"]
        self.assertEqual(illegal, ["ENV-D"])  # MERGED is never abandonable
        self.assertEqual(transitions[0]["event"], ABANDON)


if __name__ == "__main__":
    unittest.main()
