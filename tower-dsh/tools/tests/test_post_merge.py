"""Regression tests for ``towerctl post-merge`` (PILOT-003).

The bug under test: ``post-merge`` used to write
``supervision/reviews/<env>-post-merge.txt`` *before* running
``git status --porcelain``.  The tower root lives inside the verified kit
repository (``repository: ".."``), so that review file made the working tree
dirty on every run -- including the retry after a ``CORRECTION_REQUIRED``
failure, which could never escape the correction state.

Each test builds an isolated tower root plus a real throw-away git repository
under ``%TEMP%`` and drives the CLI through ``subprocess`` so exit codes are
asserted exactly as a caller observes them.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
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
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import towerctl  # noqa: E402  (needs TOOLS_DIR on sys.path)

TCLI = TOOLS_DIR / "towerctl.py"
TOWER_NAME = "tower-dsh"
TASK_ID = "TEST-PM-001"
ENVELOPE_ID = "ENV-TEST-PM-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE_ID}.json"
BASE = "main"
BRANCH = "feature/post-merge"
FIXED_TIME = "2026-10-19T00:00:00+08:00"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


class PostMergeTestCase(unittest.TestCase):
    """Fixture: ``kit`` git repo at tmp root, tower root nested as ``kit/tower-dsh``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-post-merge-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / TOWER_NAME
        for d in ("supervision/envelopes", "supervision/reviews",
                  "supervision/outbox/corrections", "tasks", "ledger"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.write_static_tower_files()
        self.init_repo()
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit)
        self.write_queue(status="MERGED")
        self.commit_all("supervision state")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(self.kit), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def commit_all(self, message: str) -> str:
        add = self.git("add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def write_static_tower_files(self) -> None:
        self.write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "tower_id": TOWER_NAME,
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-test"},
        })
        self.write_json(self.root / "tasks" / TASK_ID / "record.json", {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "post-merge regression",
            "status": "closed",
            "executor": "exec-test",
            "review": {"reviewer": "rev-test", "verdict": "PASS"},
        })
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")
        # A stale review from an earlier attempt must not break the clean check.
        self.review_file().write_text("stale review from an earlier attempt\n",
                                      encoding="utf-8")

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        init = self.git("init")
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        self.assertEqual(self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        tests_dir = self.kit / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_smoke.py").write_text(
            "import unittest\n\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.kit / "merge-envelopes").mkdir()
        self.write_json(self.kit / ENVELOPE_PATH, {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
        })
        self.commit_all("base")
        self.assertEqual(self.git("checkout", "-b", BRANCH).returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        self.assertEqual(self.git("checkout", BASE).returncode, 0)
        merge = self.git("-c", "commit.gpgsign=false", "merge", "--no-ff",
                         "-m", f"merge: {TASK_ID} ({ENVELOPE_ID})", BRANCH)
        self.assertEqual(merge.returncode, 0, msg=merge.stdout + merge.stderr)
        self.merge_commit = self.git("rev-parse", "HEAD").stdout.strip()

    def write_envelope(self, *, status: str, merge_commit: str | None,
                       tests_baseline: int | None = 1,
                       tower_tests_baseline: int | None = None) -> None:
        envelope = {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
            "repository": "..",  # the verified kit repo is the tower root's parent
            "branch": BRANCH,
            "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.merge_commit,
            "status": status,
            "merge_commit": merge_commit,
        }
        if tests_baseline is not None:
            envelope["tests_baseline"] = tests_baseline
        if tower_tests_baseline is not None:
            envelope["tower_tests_baseline"] = tower_tests_baseline
        self.write_json(self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json",
                        envelope)

    def write_tower_suite(self, test_count: int, *, failing: bool = False) -> str:
        """Write and commit a tiny ``tools/tests`` suite under the tower root.

        The tower root is the parent of ``tools``, exactly like the real tower,
        so ``post-merge`` discovers this suite with ``-s tools/tests``.
        """
        tests_dir = self.root / "tools" / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        lines = ["import unittest", "", "",
                 "class TowerSmokeTest(unittest.TestCase):"]
        for index in range(test_count):
            lines += [f"    def test_tower_{index}(self):",
                      "        self.assertTrue(True)", ""]
        if failing:
            lines += ["class TowerFailingTest(unittest.TestCase):",
                      "    def test_tower_failure(self):",
                      "        self.assertTrue(False)", ""]
        (tests_dir / "test_tower_smoke.py").write_text("\n".join(lines),
                                                       encoding="utf-8")
        return self.commit_all("tower suite fixture")

    def write_queue(self, *, status: str) -> None:
        self.write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": ENVELOPE_ID,
                "task": TASK_ID,
                "branch": BRANCH,
                "base": BASE,
                "status": status,
                "added_at": FIXED_TIME,
                "merge_commit": self.merge_commit,
            }],
            "updated_at": FIXED_TIME,
        })

    # -- assertions -------------------------------------------------------
    def run_post_merge(self, result: str = "PASS") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "post-merge", "--envelope", ENVELOPE_ID, "--result", result],
            capture_output=True, text=True, encoding="utf-8",
        )

    def envelope(self) -> dict:
        path = self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def queue_entry(self) -> dict:
        path = self.root / "supervision" / "MERGE_QUEUE.json"
        queue = json.loads(path.read_text(encoding="utf-8"))
        return next(e for e in queue["entries"] if e["envelope_id"] == ENVELOPE_ID)

    def review_file(self) -> Path:
        return self.root / "supervision" / "reviews" / f"{ENVELOPE_ID}-post-merge.txt"

    def ledger_events(self) -> list[dict]:
        path = self.root / "ledger" / "supervision.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def check(self, cp: subprocess.CompletedProcess, name: str) -> dict:
        payload = json.loads(cp.stdout)
        return next(c for c in payload["checks"] if c["name"] == name)

    # -- 1. review artefact does not dirty the verified tree --------------
    def test_preexisting_review_file_does_not_fail_clean_check(self) -> None:
        review = self.review_file()
        review.write_text("different review text left by an earlier attempt\n",
                          encoding="utf-8")
        outbox = (self.root / "supervision" / "outbox" / "corrections"
                  / f"{ENVELOPE_ID}-post-merge-retry.md")
        outbox.write_text("# correction note\n", encoding="utf-8")

        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")

        clean = self.check(cp, "working tree clean")
        self.assertTrue(clean["ok"], clean)
        self.assertIn("ignored tool-owned", clean["detail"])
        self.assertIn(f"{TOWER_NAME}/supervision/reviews", clean["detail"])
        self.assertEqual(self.envelope()["status"], "POST_MERGE_VERIFIED")
        self.assertEqual(self.queue_entry()["status"], "POST_MERGE_VERIFIED")
        self.assertTrue(review.read_text(encoding="utf-8").startswith(
            f"# {ENVELOPE_ID} post-merge verification"))

    # -- 2. FAIL then retry PASS escapes CORRECTION_REQUIRED --------------
    def test_fail_is_retryable_after_correction(self) -> None:
        first = self.run_post_merge("FAIL")
        self.assertEqual(first.returncode, 2, msg=first.stdout + first.stderr)
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        self.assertIn("- result: FAIL", self.review_file().read_text(encoding="utf-8"))
        merge_commit = self.envelope()["merge_commit"]

        # Supervision records the corrected state in the kit repo before the
        # retry, exactly as the real merge cycle does.
        self.commit_all("state after failed post-merge")

        second = self.run_post_merge("PASS")
        self.assertEqual(second.returncode, 0,
                         msg=f"stdout={second.stdout}\nstderr={second.stderr}")
        envelope = self.envelope()
        self.assertEqual(envelope["status"], "POST_MERGE_VERIFIED")
        self.assertEqual(envelope["merge_commit"], merge_commit)
        self.assertEqual(self.queue_entry()["status"], "POST_MERGE_VERIFIED")
        self.assertIn("- result: PASS", self.review_file().read_text(encoding="utf-8"))

    # -- 3. failure appends a failed ledger event -------------------------
    def test_failure_appends_ledger_event(self) -> None:
        cp = self.run_post_merge("FAIL")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        events = self.ledger_events()
        failed = [e for e in events if e["type"] == "POST_MERGE_FAILED"]
        self.assertEqual(len(failed), 1, events)
        self.assertEqual(failed[0]["payload"]["envelope"], ENVELOPE_ID)
        self.assertEqual(failed[0]["payload"]["result"], "FAIL")
        self.assertFalse([e for e in events if e["type"] == "POST_MERGE_VERIFIED"])

    # -- 4. success appends the verified ledger event ---------------------
    def test_success_appends_ledger_event(self) -> None:
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        events = self.ledger_events()
        verified = [e for e in events if e["type"] == "POST_MERGE_VERIFIED"]
        self.assertEqual(len(verified), 1, events)
        self.assertEqual(verified[0]["payload"]["envelope"], ENVELOPE_ID)
        self.assertFalse([e for e in events if e["type"] == "POST_MERGE_FAILED"])

    # -- 5. real dirt still blocks ---------------------------------------
    def test_unrelated_dirty_file_still_blocks(self) -> None:
        (self.kit / "README.md").write_text("uncommitted implementation change\n",
                                            encoding="utf-8")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        clean = self.check(cp, "working tree clean")
        self.assertFalse(clean["ok"], clean)
        self.assertIn("README.md", clean["detail"])
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        self.assertIn("working_tree_clean: False",
                      self.review_file().read_text(encoding="utf-8"))

    # -- 6. status guard: only MERGED / CORRECTION_REQUIRED may run -------
    def test_rejects_envelope_that_was_never_merged(self) -> None:
        self.write_envelope(status="DRAFT", merge_commit=None)
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("not MERGED or CORRECTION_REQUIRED", cp.stdout)
        self.assertEqual(self.envelope()["status"], "DRAFT")
        self.assertEqual(self.queue_entry()["status"], "MERGED")
        self.assertEqual(self.ledger_events(), [])

    # -- 7. count gate: an explicit baseline is met ----------------------
    def test_count_gate_passes_when_baseline_met(self) -> None:
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["tests_count"], 1)
        count = self.check(cp, "tests count >= baseline")
        self.assertTrue(count["ok"], count)
        self.assertEqual(count["detail"], "ran 1, baseline 1")
        self.assertEqual(self.envelope()["tests_count"], 1)
        review = self.review_file().read_text(encoding="utf-8")
        self.assertIn("- tests_count: 1", review)
        self.assertIn("- tests_baseline: 1", review)

    # -- 8. count gate: a shrunken suite fails below the baseline --------
    def test_count_gate_fails_when_suite_is_below_baseline(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=2)
        self.commit_all("envelope with a two-test baseline")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["status"], "CORRECTION_REQUIRED")
        self.assertEqual(payload["tests_count"], 1)
        count = self.check(cp, "tests count >= baseline")
        self.assertFalse(count["ok"], count)
        self.assertEqual(count["detail"], "ran 1, baseline 2")
        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertEqual(envelope["tests_count"], 1)
        self.assertFalse([e for e in self.ledger_events()
                          if e["type"] == "POST_MERGE_VERIFIED"])

    # -- 9. count gate: legacy envelope without a baseline still passes ---
    def test_legacy_envelope_without_baseline_passes(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=None)
        self.commit_all("legacy envelope without tests_baseline")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        count = self.check(cp, "tests count present")
        self.assertTrue(count["ok"], count)
        self.assertEqual(count["detail"], "ran 1, baseline not set")
        self.assertEqual(self.envelope()["tests_count"], 1)
        self.assertIn("- tests_baseline: not set",
                      self.review_file().read_text(encoding="utf-8"))

    # -- 10. count gate: an empty tests/ dir must not pass ----------------
    def test_legacy_envelope_fails_when_no_tests_remain(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=None)
        (self.kit / "tests" / "test_smoke.py").unlink()
        self.commit_all("delete the smoke test")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        count = self.check(cp, "tests count present")
        self.assertFalse(count["ok"], count)
        self.assertEqual(count["detail"], "ran 0, baseline not set")
        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertEqual(envelope["tests_count"], 0)
        self.assertIn("- tests_count: 0",
                      self.review_file().read_text(encoding="utf-8"))

    # -- 11. parse_test_count unit contract ------------------------------
    def test_parse_test_count_unit_cases(self) -> None:
        cases = [
            ("Ran 236 tests in 76s", None, 236),
            ("Ran 1 test", None, 1),
            ("Ran 3 tests\nsome noise\nRan 7 tests\n", None, 7),
            ("stdout says nothing", "Ran 11 tests in 0.1s", 11),
            ("no summary line at all", None, None),
            (None, None, None),
        ]
        for stdout, stderr, expected in cases:
            with self.subTest(stdout=stdout, stderr=stderr):
                self.assertEqual(towerctl.parse_test_count(stdout, stderr), expected)

    # -- 12. tower gate: an explicit baseline is met ---------------------
    def test_tower_count_gate_passes_when_baseline_met(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=1, tower_tests_baseline=1)
        self.write_tower_suite(1)
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertEqual([c["name"] for c in payload["checks"]], [
            "post-merge tests pass",
            "tests count >= baseline",
            "tower tests count >= baseline",
            "implementation is ancestor of base",
            "envelope file exists on base",
            "working tree clean",
        ])
        tower = self.check(cp, "tower tests count >= baseline")
        self.assertTrue(tower["ok"], tower)
        self.assertEqual(tower["detail"], "exit 0, ran 1, baseline 1")
        self.assertEqual(self.envelope()["tower_tests_count"], 1)
        review = self.review_file().read_text(encoding="utf-8")
        self.assertIn("- tower_tests_count: 1", review)
        self.assertIn("- tower_tests_baseline: 1", review)
        verified = [e for e in self.ledger_events()
                    if e["type"] == "POST_MERGE_VERIFIED"]
        self.assertEqual(len(verified), 1, verified)
        self.assertEqual(verified[0]["payload"]["tower_tests_count"], 1)

    # -- 13. tower gate: a shrunken tower suite fails ---------------------
    def test_tower_count_gate_fails_when_suite_is_below_baseline(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=1, tower_tests_baseline=2)
        self.write_tower_suite(1)
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["status"], "CORRECTION_REQUIRED")
        tower = self.check(cp, "tower tests count >= baseline")
        self.assertFalse(tower["ok"], tower)
        self.assertEqual(tower["detail"], "exit 0, ran 1, baseline 2")
        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertEqual(envelope["tower_tests_count"], 1)
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        events = self.ledger_events()
        self.assertFalse([e for e in events if e["type"] == "POST_MERGE_VERIFIED"])
        failed = [e for e in events if e["type"] == "POST_MERGE_FAILED"]
        self.assertEqual(len(failed), 1, events)
        self.assertEqual(failed[0]["payload"]["tower_tests_count"], 1)

    # -- 14. tower gate: a missing tools/tests directory must fail --------
    def test_tower_count_gate_fails_when_tools_tests_missing(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=1, tower_tests_baseline=1)
        self.commit_all("envelope with a tower baseline but no tower suite")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        tower = self.check(cp, "tower tests count >= baseline")
        self.assertFalse(tower["ok"], tower)
        self.assertIn("ran unknown", tower["detail"])
        self.assertIsNone(self.envelope()["tower_tests_count"])
        self.assertIn("- tower_tests_count: unknown",
                      self.review_file().read_text(encoding="utf-8"))

    # -- 15. legacy envelope: no tower baseline, no tower run -------------
    def test_legacy_envelope_without_tower_baseline_skips_gate(self) -> None:
        # setUp already committed a MERGED envelope with no tower baseline.
        self.assertNotIn("tower_tests_baseline", self.envelope())
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        names = [c["name"] for c in json.loads(cp.stdout)["checks"]]
        self.assertNotIn("tower tests count >= baseline", names)
        self.assertEqual(names, [
            "post-merge tests pass",
            "tests count >= baseline",
            "implementation is ancestor of base",
            "envelope file exists on base",
            "working tree clean",
        ])
        self.assertNotIn("tower_tests_count", self.envelope())
        review = self.review_file().read_text(encoding="utf-8")
        self.assertIn("- tower_tests_count: unknown", review)
        self.assertIn("- tower_tests_baseline: not set", review)

    # -- 16. tower gate: a failing suite fails despite a high count -------
    def test_tower_count_gate_fails_when_suite_exits_nonzero(self) -> None:
        self.write_envelope(status="MERGED", merge_commit=self.merge_commit,
                            tests_baseline=1, tower_tests_baseline=1)
        self.write_tower_suite(2, failing=True)
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        tower = self.check(cp, "tower tests count >= baseline")
        self.assertFalse(tower["ok"], tower)
        self.assertEqual(tower["detail"], "exit 1, ran 3, baseline 1")
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
