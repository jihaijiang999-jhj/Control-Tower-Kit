"""PILOT-066: post-merge resolves a base-side envelope under the tower root.

``envelope-new --base-side`` commits the envelope file on the base branch
*inside* the tower root, so in the repository it lives at
``tower-dsh/merge-envelopes/<ENV>.json``.  ``post-merge`` nevertheless looked
for ``merge-envelopes/<ENV>.json`` at the repository root, and ENV-PILOT-065
only passed because a duplicate envelope file (a shim) had been committed at
the repository root.  That shim is duplicate state and is removed.

``post-merge`` now derives the repository path of a base-side envelope from
``git rev-parse --show-prefix`` plus ``envelope_path``; a legacy branch-side
envelope keeps the repository-root lookup.  The check detail always names the
repository path that was actually probed (``<base>:<repo_path>``), so a
missing or misplaced envelope can be located from the output alone.

Each case builds an isolated tower root (``kit/tower-dsh``) plus a real
throw-away git repository (``kit``) under ``%TEMP%``; ``repository: ".."``
points the envelope at the kit repository exactly as the real tower does.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_post_merge_envelope_path -v
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
TOWER_NAME = "tower-dsh"
TASK_ID = "TEST-PM-PATH-001"
ENVELOPE_ID = "ENV-TEST-PM-PATH-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE_ID}.json"
BASE = "main"
BRANCH = "feature/post-merge-envelope-path"
FIXED_TIME = "2026-11-03T00:00:00+08:00"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


class PostMergeEnvelopePathCase(unittest.TestCase):
    """Fixture: ``kit`` git repo at tmp root, tower root nested as ``kit/tower-dsh``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-post-merge-env-path-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / TOWER_NAME
        for d in ("supervision/envelopes", "supervision/reviews", "tasks", "ledger"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.write_static_tower_files()
        self.init_repo()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.kit), *args], capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, **GIT_IDENTITY))

    def commit_state(self, message: str) -> str:
        """Stage every change in the kit repo and commit it on the base branch."""
        add = self.git("add", "--all")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")

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
            "title": "post-merge envelope path",
            "status": "closed",
            "executor": "exec-test",
            "review": {"reviewer": "rev-test", "verdict": "PASS"},
        })
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        init = self.git("init")
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
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
        # The first commit is the base: it already carries the tower state, so
        # every per-case envelope commit below is the only later change.
        self.base_sha = self.commit_state("base")
        self.assertEqual(self.git("checkout", "-b", BRANCH).returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_state("implementation")
        self.assertEqual(self.git("checkout", BASE).returncode, 0)
        merge = self.git("-c", "commit.gpgsign=false", "merge", "--no-ff",
                         "-m", f"merge: {TASK_ID} ({ENVELOPE_ID})", BRANCH)
        self.assertEqual(merge.returncode, 0, msg=merge.stdout + merge.stderr)
        self.merge_commit = self.git("rev-parse", "HEAD").stdout.strip()

    # -- per-case state ---------------------------------------------------
    def tower_envelope_file(self) -> Path:
        return self.root / ENVELOPE_PATH

    def repo_envelope_file(self) -> Path:
        return self.kit / ENVELOPE_PATH

    def write_envelope_file(self, where: str) -> None:
        target = self.root / ENVELOPE_PATH if where == "tower" else self.kit / ENVELOPE_PATH
        self.write_json(target, {"schema": "tower/merge-envelope@1",
                                 "envelope_id": ENVELOPE_ID, "task": TASK_ID})

    def write_envelope_record(self, base_side: bool) -> None:
        envelope = {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
            "repository": "..",  # the verified kit repository is the tower parent
            "branch": BRANCH,
            "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.merge_commit,
            "status": "MERGED",
            "merge_commit": self.merge_commit,
            "tests_baseline": 1,
        }
        if base_side:
            envelope["base_side"] = True
        self.write_json(
            self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json", envelope)

    def write_queue(self) -> None:
        self.write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": ENVELOPE_ID,
                "task": TASK_ID,
                "branch": BRANCH,
                "base": BASE,
                "status": "MERGED",
                "added_at": FIXED_TIME,
                "merge_commit": self.merge_commit,
            }],
            "updated_at": FIXED_TIME,
        })

    def prepare(self, *, base_side: bool, placement: str | None) -> None:
        """Commit the envelope file (if any), the record and the queue entry."""
        if placement is not None:
            self.write_envelope_file(placement)
        self.write_envelope_record(base_side)
        self.write_queue()
        self.commit_state("post-merge state")

    # -- assertions -------------------------------------------------------
    def run_post_merge(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "post-merge", "--envelope", ENVELOPE_ID, "--result", "PASS"],
            capture_output=True, text=True, encoding="utf-8",
        )

    def check(self, cp: subprocess.CompletedProcess) -> dict:
        payload = json.loads(cp.stdout)
        return next(c for c in payload["checks"]
                    if c["name"] == "envelope file exists on base")

    def envelope_record(self) -> dict:
        path = self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # -- 1. base-side file under the tower root, no repo-root copy --------
    def test_base_side_envelope_under_tower_root_verifies(self) -> None:
        self.prepare(base_side=True, placement="tower")
        self.assertFalse(self.repo_envelope_file().exists())

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        check = self.check(cp)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["detail"],
                         f"{BASE}:{TOWER_NAME}/{ENVELOPE_PATH}")
        self.assertEqual(self.envelope_record()["status"], "POST_MERGE_VERIFIED")

    # -- 2. legacy branch-side file at the repository root ----------------
    def test_legacy_branch_side_envelope_at_repo_root_verifies(self) -> None:
        self.prepare(base_side=False, placement="repo")
        self.assertFalse(self.tower_envelope_file().exists())

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        check = self.check(cp)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["detail"], f"{BASE}:{ENVELOPE_PATH}")
        self.assertEqual(self.envelope_record()["status"], "POST_MERGE_VERIFIED")

    # -- 3. base-side file *only* at the repository root is refused -------
    def test_base_side_copy_only_at_repo_root_is_rejected(self) -> None:
        self.prepare(base_side=True, placement="repo")
        self.assertFalse(self.tower_envelope_file().exists())

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = self.check(cp)
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["detail"],
                         f"{BASE}:{TOWER_NAME}/{ENVELOPE_PATH}")
        self.assertEqual(self.envelope_record()["status"], "CORRECTION_REQUIRED")
        self.assertTrue(self.repo_envelope_file().exists())

    # -- 4. a base-side file that is missing everywhere is refused --------
    def test_base_side_missing_envelope_is_rejected(self) -> None:
        self.prepare(base_side=True, placement=None)
        self.assertFalse(self.tower_envelope_file().exists())
        self.assertFalse(self.repo_envelope_file().exists())

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = self.check(cp)
        self.assertFalse(check["ok"], check)
        self.assertEqual(self.envelope_record()["status"], "CORRECTION_REQUIRED")

    # -- 5. the refusal names the repository path that was probed ---------
    def test_rejection_message_carries_repo_path(self) -> None:
        self.prepare(base_side=True, placement="repo")

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn(f"{BASE}:{TOWER_NAME}/{ENVELOPE_PATH}", cp.stdout)
        self.assertIn(f"{TOWER_NAME}/{ENVELOPE_PATH}", cp.stdout)
        self.assertNotIn(f"{BASE}:{TOWER_NAME}/{TOWER_NAME}/", cp.stdout)

    # -- 6. a missing legacy branch-side file keeps the repo-root path ----
    def test_legacy_missing_envelope_keeps_repo_root_path(self) -> None:
        self.prepare(base_side=False, placement=None)

        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = self.check(cp)
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["detail"], f"{BASE}:{ENVELOPE_PATH}")


if __name__ == "__main__":
    unittest.main()
