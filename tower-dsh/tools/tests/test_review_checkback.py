"""PILOT-076: REVIEW.json is re-checked against the last CHECKBACK event.

The ledger ``CHECKBACK`` event is the authority -- append-only and
hash-chained -- while ``tasks/<id>/REVIEW.json`` is only its snapshot.  This
module pins the reconciliation:

* ``state-verify`` reports ``review_unbacked`` drift when the snapshot's
  ``reviewer`` / ``verdict`` / ``head`` / ``base`` no longer equals the last
  head-bearing ``CHECKBACK``;
* ``merge-check`` decides the ``review bound to head`` check from that same
  last event, so a rewritten snapshot is refused instead of trusted.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_review_checkback -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
sys.path.insert(0, str(TOOLS_DIR))
from tower_ledger import append_ledger  # noqa: E402  (TOOLS_DIR must lead sys.path)
TASK = "PILOT-078"
WORKTREE = f"pilot/worktrees/{TASK}"
ENVELOPE = "ENV-PILOT-078"
REVIEWER = "rev-076"
EXECUTOR = "exec-076"
FIXED_TIME = "2026-11-03T00:00:00+08:00"
HEAD_ONE = "1" * 40
HEAD_TWO = "2" * 40
BASE_ONE = "a" * 40
BASE_TWO = "b" * 40
REVIEW_CHECK = "review bound to head"


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ReviewCheckbackCase(unittest.TestCase):
    """A reviewed card, its REVIEW.json snapshot and its merge envelope."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-review-unbacked-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower"
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-review",
            "role": "primary", "primary": {"id": "ctl-076"},
            "owner": {"name": "mac"}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": "review binding",
            "status": "delivered", "authority": "workspace_write",
            "scope": ["review binding"], "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge"], "acceptance": ["tests pass"],
            "depends_on": [], "worktree": f"pilot/worktrees/{TASK}",
            "executor": EXECUTOR, "evidence": [], "review": None,
            "dispatch": {"executor": EXECUTOR, "worktree": WORKTREE,
                         "base_sha": BASE_ONE, "at": FIXED_TIME},
            "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME, "next": ""})
        # Seed the lifecycle the record claims, so replay agrees with it and
        # only the review/CHECKBACK pair is under test.
        append_ledger(self.root, "TASK_NEW", "primary",
                      {"task": TASK, "title": "review binding"})
        append_ledger(self.root, "DISPATCH", "primary", {
            "task": TASK, "executor": EXECUTOR,
            "worktree": f"pilot/worktrees/{TASK}", "base_sha": BASE_ONE,
            "at": FIXED_TIME})
        append_ledger(self.root, "DELIVER", "primary",
                      {"task": TASK, "evidence": 0})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- commands ---------------------------------------------------------
    def checkback(self, head: str = HEAD_ONE,
                  base: str = BASE_ONE) -> subprocess.CompletedProcess:
        return run_cli(self.root, "checkback", "--task", TASK,
                       "--reviewer", REVIEWER, "--verdict", "PASS",
                       "--head", head, "--base", base)

    def reviewed(self, head: str = HEAD_ONE, base: str = BASE_ONE) -> dict:
        cp = self.checkback(head, base)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.review()

    def review(self) -> dict:
        return read_json(self.root / "tasks" / TASK / "REVIEW.json")

    def write_review(self, **changes) -> None:
        review = self.review()
        review.update(changes)
        write_json(self.root / "tasks" / TASK / "REVIEW.json", review)

    def state_verify(self) -> subprocess.CompletedProcess:
        return run_cli(self.root, "state-verify")

    def merge_check(self) -> subprocess.CompletedProcess:
        return run_cli(self.root, "merge-check", "--envelope", ENVELOPE)

    def write_envelope(self, head: str) -> None:
        """A legacy (baseline-free) envelope + queue entry for merge-check."""
        write_json(self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": ".", "branch": "feature/review",
            "base": "main", "envelope_path": f"merge-envelopes/{ENVELOPE}.json",
            "implementation_head_sha": head, "status": "DRAFT"})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": "feature/review", "base": "main",
                         "status": "WAITING", "added_at": FIXED_TIME}]})

    def merge_check_check(self, cp: subprocess.CompletedProcess) -> dict | None:
        """The ``review bound to head`` error row, or None when it passed."""
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        return next((item for item in errors if item["name"] == REVIEW_CHECK), None)

    # -- 1. a matching review verifies clean ------------------------------
    def test_matching_review_is_clean_state(self) -> None:
        review = self.reviewed()
        self.assertEqual(review["reviewer"], REVIEWER)
        self.assertEqual(review["verdict"], "PASS")
        self.assertEqual(review["head"], HEAD_ONE)
        self.assertEqual(review["base"], BASE_ONE)
        cp = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["drift"], [])

    # -- 1b. a missing snapshot is drift, not a legacy skip ---------------
    def test_missing_review_json_is_review_unbacked_drift(self) -> None:
        self.reviewed()
        self.write_envelope(HEAD_ONE)
        (self.root / "tasks" / TASK / "REVIEW.json").unlink()
        cp = self.state_verify()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        drift = json.loads(cp.stdout)["drift"]
        rows = [row for row in drift
                if row["kind"] == "review_unbacked" and row["target"] == TASK]
        self.assertEqual(len(rows), 1, msg=drift)
        self.assertEqual(rows[0]["actual"], "missing")
        self.assertIn("CHECKBACK", rows[0]["expected"])
        failure = self.merge_check_check(self.merge_check())
        self.assertIsNotNone(failure)
        self.assertIn("stale review", failure["detail"])

    # -- 2. every rewritten field is review_unbacked drift ----------------
    def test_rewritten_fields_are_review_unbacked_drift(self) -> None:
        self.reviewed()
        rewrites = {"reviewer": "rev-forged", "verdict": "FAIL",
                    "head": "3" * 40, "base": "4" * 40}
        for field, value in rewrites.items():
            with self.subTest(field=field):
                self.reviewed()
                self.write_review(**{field: value})
                cp = self.state_verify()
                self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
                drift = json.loads(cp.stdout)["drift"]
                rows = [row for row in drift
                        if row["kind"] == "review_unbacked"
                        and row["target"] == TASK]
                self.assertEqual(len(rows), 1, msg=drift)
                self.assertIn(field, rows[0]["fields"])
                self.assertNotEqual(rows[0]["expected"][field],
                                    rows[0]["actual"][field])

    # -- 3. the last CHECKBACK decides, not the earlier one ---------------
    def test_last_checkback_is_the_authority(self) -> None:
        self.reviewed(HEAD_ONE, BASE_ONE)
        second = self.reviewed(HEAD_TWO, BASE_ONE)
        self.assertEqual(second["head"], HEAD_TWO)
        self.write_envelope(HEAD_TWO)
        cp = self.merge_check()
        self.assertIsNone(self.merge_check_check(cp),
                          msg="the snapshot still matches the last CHECKBACK")
        # A snapshot pinned back to the first review is now unbacked.
        self.write_review(head=HEAD_ONE, base=BASE_ONE)
        failure = self.merge_check_check(self.merge_check())
        self.assertIsNotNone(failure)
        self.assertIn("review_unbacked", failure["detail"])
        self.assertIn("head", failure["detail"])

    # -- 4. merge-check refuses a rewritten snapshot ----------------------
    def test_merge_check_reports_review_unbacked(self) -> None:
        self.reviewed()
        self.write_envelope(HEAD_ONE)
        self.write_review(verdict="FAIL")
        failure = self.merge_check_check(self.merge_check())
        self.assertIsNotNone(failure)
        self.assertIn("review_unbacked", failure["detail"])
        self.assertIn("verdict", failure["detail"])


if __name__ == "__main__":
    unittest.main()
