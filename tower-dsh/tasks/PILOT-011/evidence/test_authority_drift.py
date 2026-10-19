"""Dirty-authority-state detection tests (PILOT-011).

``status`` / ``startup`` must report uncommitted authority state
(``primary/``, ``supervision/``, ``ledger/``, ``handoffs/``, ``shared/``)
relative to the surrounding git repository, and ``handoff-activate`` must ask
for a commit without ever performing one.

Every test builds a throw-away tower root *inside* a throw-away git repository
under ``tempfile`` and drives the real CLI through ``subprocess``, so no test
depends on the live tower's working-tree state.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
FIXED_TIME = "2026-10-19T00:00:00+08:00"
PACKAGE = "HANDOFF-TEST-011"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class AuthorityDriftTestCase(unittest.TestCase):
    """Fixture: ``<tmp>/kit`` is a git repo and ``<tmp>/kit/tower-dsh`` a tower."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-authority-", ignore_cleanup_errors=True)
        self.base = Path(self._tmp.name)
        self.kit = self.base / "kit"
        self.root = self.kit / "tower-dsh"

        for name in ("primary", "supervision/reviews", "supervision/outbox",
                     "ledger", "handoffs", "shared"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

        for name in ("TOWER.md", "AGENTS.md", "START-HERE.md"):
            (self.root / name).write_text(f"# {name}\n", encoding="utf-8")
        write_json(self.root / "shared" / "PROJECT_PROFILE.json",
                   {"schema": "tower/project-profile@1", "name": "tower-test"})
        write_json(self.root / "shared" / "AUTHORITY_MODEL.json",
                   {"schema": "tower/authority-model@1", "levels": []})
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-test",
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": "ctl-test"},
            "owner": {"name": "mac"},
            "next_action": "test",
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-test"},
        })
        # Tracked placeholders keep the tool-owned directories real git paths.
        for name in ("supervision/reviews", "supervision/outbox"):
            (self.root / name / ".gitkeep").write_text("", encoding="utf-8")
        # ``handoffs`` needs a tracked file so that deleting the whole
        # directory registers as a tracked deletion rather than a no-op.
        (self.root / "handoffs" / ".gitkeep").write_text("", encoding="utf-8")
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")

        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.git(self.kit, "init").returncode, 0)
        self.assertEqual(
            self.git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        self.commit_all("initial tower state")
        # The fixture must start clean, otherwise every drift assertion is moot.
        self.assertEqual((self.root / "ledger" / "primary.jsonl").stat().st_size, 0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def commit_all(self, message: str) -> str:
        add = self.git(self.kit, "add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        commit = self.git(self.kit, "-c", "commit.gpgsign=false",
                          "commit", "-m", message)
        self.assertEqual(commit.returncode, 0,
                         msg=commit.stdout + commit.stderr)
        return self.git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def run_cli(self, *args: str, root: Path | None = None,
                env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        # The child would otherwise encode stdout with the Windows locale code
        # page (GBK here) while this harness decodes as UTF-8.  Pinning the
        # child's stream encoding keeps non-ASCII path assertions exact.
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(root or self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def status_json(self, root: Path | None = None,
                    env_extra: dict | None = None) -> dict:
        cp = self.run_cli("status", root=root, env_extra=env_extra)
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        return json.loads(cp.stdout)

    def setUpMissingRepo(self) -> Path:
        """A tower root that is deliberately not inside any git repository."""
        root = self.base / "loose" / "tower-dsh"
        for name in ("primary", "ledger", "supervision", "handoffs", "shared"):
            (root / name).mkdir(parents=True, exist_ok=True)
        write_json(root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-loose",
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": "ctl-loose"},
            "owner": {"name": "mac"},
        })
        write_json(root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")
        return root

    # -- 1. clean repository ---------------------------------------------
    def test_status_clean_repository_reports_empty_drift(self) -> None:
        data = self.status_json()
        self.assertEqual(data["authority_dirty"], [])
        self.assertEqual(data["authority_dirty_count"], 0)

    # -- 2. modified authority file --------------------------------------
    def test_status_reports_uncommitted_primary_state(self) -> None:
        state = self.root / "primary" / "CURRENT_STATE.json"
        state.write_text(state.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        data = self.status_json()
        self.assertIn("tower-dsh/primary/CURRENT_STATE.json", data["authority_dirty"])
        self.assertGreaterEqual(data["authority_dirty_count"], 1)
        self.assertEqual(data["authority_dirty_count"], len(data["authority_dirty"]))

    # -- 3. tower root outside a git repository --------------------------
    def test_status_outside_git_repository_reports_null(self) -> None:
        root = self.setUpMissingRepo()
        # GIT_CEILING_DIRECTORIES makes the "not a repository" condition
        # deterministic even if the temp directory happens to sit below a repo.
        data = self.status_json(root=root,
                                env_extra={"GIT_CEILING_DIRECTORIES": str(root)})
        self.assertIsNone(data["authority_dirty"])
        self.assertIsNone(data["authority_dirty_count"])

    # -- 4. startup count matches status ---------------------------------
    def test_startup_count_matches_status_count(self) -> None:
        target = self.root / "shared" / "PROJECT_PROFILE.json"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        status = self.status_json()
        cp = self.run_cli("startup")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        startup = json.loads(cp.stdout)
        self.assertEqual(startup["authority_dirty_count"],
                         status["authority_dirty_count"])
        self.assertGreaterEqual(startup["authority_dirty_count"], 1)

    def test_startup_count_zero_on_clean_repository(self) -> None:
        cp = self.run_cli("startup")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["authority_dirty_count"], 0)

    # -- 5. handoff-activate asks for a commit but never commits ---------
    def test_handoff_activate_requires_commit_without_committing(self) -> None:
        pkgdir = self.root / "handoffs" / PACKAGE
        write_json(pkgdir / "package.json", {
            "schema": "tower/handoff@1",
            "package_id": PACKAGE,
            "status": "ACCEPTED",
            "source_controller": "ctl-src",
            "acceptance": {"receiver": "rev-1", "accepted_at": FIXED_TIME},
        })
        head_before = self.commit_all("prepare accepted package")
        self.assertEqual(self.status_json()["authority_dirty_count"], 0)

        cp = self.run_cli("handoff-activate", "--package", PACKAGE,
                          "--controller", "rev-1")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertIs(out["commit_required"], True)
        self.assertTrue(out["commit_hint"].strip(),
                        msg="dirty activation must carry a commit hint")
        self.assertIn("add", out["commit_hint"])
        self.assertIn("commit", out["commit_hint"])
        self.assertIn(f"tower-dsh/handoffs/{PACKAGE}", out["commit_hint"])

        # The tool reports; it must not decide the commit boundary itself.
        self.assertEqual(self.git(self.kit, "rev-parse", "HEAD").stdout.strip(),
                         head_before)
        data = self.status_json()
        self.assertIn(f"tower-dsh/handoffs/{PACKAGE}/ACTIVATION.json",
                      data["authority_dirty"])
        self.assertGreaterEqual(data["authority_dirty_count"], 1)

    # -- 6. tool-owned output directories are ignored --------------------
    def test_uncommitted_review_file_is_not_authority_drift(self) -> None:
        reviews = self.root / "supervision" / "reviews"
        (reviews / "PILOT-999-review.md").write_text("verdict: PASS\n",
                                                     encoding="utf-8")
        outbox = self.root / "supervision" / "outbox" / "corrections"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / "C-1.md").write_text("correction\n", encoding="utf-8")

        data = self.status_json()
        self.assertEqual(data["authority_dirty"], [])
        self.assertEqual(data["authority_dirty_count"], 0)

    def test_supervision_state_outside_owned_dirs_still_counts(self) -> None:
        # The exclusion is narrow: only reviews/ and outbox/ are tool-owned.
        target = self.root / "supervision" / "CURRENT_STATE.json"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        data = self.status_json()
        self.assertIn("tower-dsh/supervision/CURRENT_STATE.json",
                      data["authority_dirty"])

    # -- 7. ledger/ and handoffs/ are watched ----------------------------
    def test_ledger_and_handoffs_changes_are_reported(self) -> None:
        ledger = self.root / "ledger" / "primary.jsonl"
        ledger.write_text(json.dumps({"seq": 1, "type": "TEST"}) + "\n",
                          encoding="utf-8")
        write_json(self.root / "handoffs" / PACKAGE / "package.json", {
            "schema": "tower/handoff@1",
            "package_id": PACKAGE,
            "status": "PREPARED",
        })
        data = self.status_json()
        dirty = data["authority_dirty"]
        self.assertIn("tower-dsh/ledger/primary.jsonl", dirty)
        self.assertIn(f"tower-dsh/handoffs/{PACKAGE}/package.json", dirty)
        self.assertEqual(data["authority_dirty_count"], len(dirty))

    # -- 8. deleted authority directories are still drift ----------------
    def test_deleting_handoffs_directory_is_reported(self) -> None:
        shutil.rmtree(self.root / "handoffs")
        data = self.status_json()
        self.assertTrue(any(path.startswith("tower-dsh/handoffs/")
                            for path in data["authority_dirty"]),
                        msg=f"deleted handoffs/ not reported: {data['authority_dirty']}")
        self.assertGreaterEqual(data["authority_dirty_count"], 1)

    def test_deleting_ledger_directory_is_reported(self) -> None:
        shutil.rmtree(self.root / "ledger")
        data = self.status_json()
        self.assertIn("tower-dsh/ledger/primary.jsonl", data["authority_dirty"])
        self.assertGreaterEqual(data["authority_dirty_count"], 1)

    # -- 9. non-ASCII paths are reported literally ----------------------
    def test_non_ascii_path_is_reported_without_escapes(self) -> None:
        target = self.root / "primary" / "中文.json"
        target.write_text("{}\n", encoding="utf-8")
        data = self.status_json()
        self.assertIn("tower-dsh/primary/中文.json", data["authority_dirty"])
        joined = " ".join(data["authority_dirty"])
        self.assertNotIn("\\344", joined,
                         msg=f"path was octal-escaped: {joined}")


if __name__ == "__main__":
    unittest.main()
