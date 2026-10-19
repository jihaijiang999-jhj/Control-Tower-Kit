"""Hardening round 2 regression tests (PILOT-010).

Covers four independent defects:

* path-escape protection for ``--task`` / ``--package`` / ``--envelope`` /
  ``--worktree`` / ``--spec`` / ``--file`` / ``--evidence`` and the envelope
  ``repository`` field (``repository: ".."`` stays valid for the kit layout);
* a single JSON object on stdout when ``merge-check`` runs against a missing
  task record (``envelope_checks`` must never emit from inside a check);
* closeout no longer claims "Merge: not performed" and points at the merge
  queue / ``tasks/<id>/MERGE.md``; a successful post-merge writes that record;
* the Windows ACL busy-wait: a persistent ``PermissionError`` with no lock file
  must hit the deadline instead of spinning forever.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"
TASK_ID = "T-001"
ENVELOPE_ID = "ENV-HARD-001"
FIXED_TIME = "2026-10-19T00:00:00+08:00"

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


# ---------------------------------------------------------------------------
# path confinement
# ---------------------------------------------------------------------------
class PathSafetyTestCase(unittest.TestCase):
    """Ids and paths must never point outside the tower root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-hardening2-", ignore_cleanup_errors=True)
        self.base = Path(self._tmp.name)
        self.root = self.base / "tower"
        self.outside = self.base / "outside"
        for directory in ("primary", "supervision/envelopes", "ledger", "specs",
                          "handoffs", f"tasks/{TASK_ID}/evidence",
                          f"pilot/worktrees/{TASK_ID}", "pilot/repo", "outside"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.outside.mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()

        self.spec_path = self.root / "specs" / "task.spec.json"
        write_json(self.spec_path, {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "hardening 2",
            "authority": "workspace_write",
            "scope": ["exercise path guards"],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
        })
        self.record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "hardening 2",
            "status": "ready",
            "authority": "workspace_write",
            "scope": ["exercise path guards"],
            "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "spec_path": "specs/task.spec.json",
            "spec_sha256": sha256_file(self.spec_path),
            "spec_gate": "PASS",
            "executor": None,
            "dispatch": None,
            "evidence": [],
            "review": None,
            "decision": None,
            "closeout": None,
            "created_at": FIXED_TIME,
            "updated_at": FIXED_TIME,
            "next": "",
        }
        self.write_record()
        (self.root / "tasks" / TASK_ID / "TASK.md").write_text(
            f"# {TASK_ID} — hardening 2\n", encoding="utf-8")
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
            "owner": {"name": "mac"}, "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": "sup-test"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.artifact = (self.root / "pilot" / "worktrees" / TASK_ID / "ART.txt")
        self.artifact.write_text("artifact inside the root\n", encoding="utf-8")
        self.outside_evidence = self.outside / "evidence.txt"
        self.outside_evidence.write_text("evidence outside the root\n",
                                         encoding="utf-8")
        self.outside_spec = self.outside / "task.spec.json"
        write_json(self.outside_spec, {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "outside",
            "authority": "workspace_write",
            "scope": ["outside"],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
        })
        self.outside_envelope = self.outside / "envelope.json"
        write_json(self.outside_envelope, {
            "envelope_id": "ENV-OUTSIDE", "task": TASK_ID})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / TASK_ID / "record.json", data)
        self.record = data

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def write_envelope(self, name: str = ENVELOPE_ID, **overrides) -> Path:
        envelope = {
            "schema": "tower/merge-envelope@1",
            "envelope_id": name,
            "task": TASK_ID,
            "repository": "pilot/repo",
            "branch": "feature",
            "base": "main",
            "envelope_path": f"merge-envelopes/{name}.json",
            "implementation_head_sha": "a" * 40,
            "envelope_head_sha": "b" * 40,
            "status": "DRAFT",
        }
        envelope.update(overrides)
        path = self.root / "supervision" / "envelopes" / f"{name}.json"
        write_json(path, envelope)
        return path

    def assert_fails(self, cp: subprocess.CompletedProcess, *keywords: str) -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = (cp.stdout + cp.stderr).lower()
        for keyword in keywords:
            self.assertIn(keyword.lower(), blob,
                          msg=f"missing {keyword!r} in stdout={cp.stdout}\n"
                              f"stderr={cp.stderr}")

    # -- 1. traversal in task ids ---------------------------------------
    def test_task_id_traversal_is_rejected(self) -> None:
        for bad in ("../x", "..\\x", "T/../../x"):
            cp = run_cli(self.root, "check", "--task", bad, "--phase", "ready")
            self.assert_fails(cp, "invalid id")

    # -- 2. traversal in package ids ------------------------------------
    def test_handoff_package_traversal_is_rejected(self) -> None:
        cp = run_cli(self.root, "handoff-check", "--package", "../x")
        self.assert_fails(cp, "invalid id")
        cp = run_cli(self.root, "handoff-new", "--package", "../x")
        self.assert_fails(cp, "invalid id")

    # -- 3. a regex-valid id may still not contain '..' -----------------
    def test_package_id_with_dotdot_segment_is_rejected(self) -> None:
        cp = run_cli(self.root, "handoff-check", "--package", "A..B")
        self.assert_fails(cp, "invalid id")
        cp = run_cli(self.root, "handoff-new", "--package", "A..B")
        self.assert_fails(cp, "invalid id")

    # -- 4. traversal in envelope ids -----------------------------------
    def test_envelope_id_traversal_is_rejected(self) -> None:
        cp = run_cli(self.root, "merge-check", "--envelope", "../x")
        self.assert_fails(cp, "invalid id")
        cp = run_cli(self.root, "queue-add", "--envelope", "../x")
        self.assert_fails(cp, "invalid id")
        cp = run_cli(self.root, "merge-check", "--envelope", "A..B")
        self.assert_fails(cp, "invalid id")

    # -- 5. --worktree must stay inside the root ------------------------
    def test_dispatch_rejects_worktree_outside_root(self) -> None:
        for bad in (str(self.outside), "../outside"):
            cp = run_cli(self.root, "dispatch", "--task", TASK_ID,
                         "--executor", "exec-a", "--worktree", bad)
            self.assert_fails(cp, "outside tower root")
            self.assertEqual(self.load_record()["status"], "ready")

    # -- 6. an in-root worktree still dispatches ------------------------
    def test_dispatch_accepts_worktree_inside_root(self) -> None:
        cp = run_cli(self.root, "dispatch", "--task", TASK_ID,
                     "--executor", "exec-a",
                     "--worktree", f"pilot/worktrees/{TASK_ID}")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["status"], "dispatched")

    # -- 7. --evidence must stay inside the root ------------------------
    def test_deliver_rejects_evidence_outside_root(self) -> None:
        self.write_record(status="dispatched", executor="exec-a")
        cp = run_cli(self.root, "deliver", "--task", TASK_ID,
                     "--evidence", str(self.outside_evidence))
        self.assert_fails(cp, "outside tower root")
        self.assertEqual(self.load_record()["evidence"], [])
        self.assertEqual(self.load_record()["status"], "dispatched")

    # -- 8. in-root evidence keeps working (pilot/worktrees/...) --------
    def test_deliver_accepts_evidence_inside_root(self) -> None:
        self.write_record(status="dispatched", executor="exec-a")
        cp = run_cli(self.root, "deliver", "--task", TASK_ID,
                     "--evidence", str(self.artifact))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        record = self.load_record()
        self.assertEqual(record["status"], "delivered")
        self.assertEqual(record["evidence"][0]["path"],
                         f"tasks/{TASK_ID}/evidence/ART.txt")

    # -- 8b. recorded evidence paths under pilot/worktrees stay valid ---
    def test_evidence_path_under_pilot_worktrees_is_accepted(self) -> None:
        record = {"evidence": [{
            "id": "E-001",
            "path": f"pilot/worktrees/{TASK_ID}/ART.txt",
            "sha256": sha256_file(self.artifact),
            "bytes": self.artifact.stat().st_size,
            "at": FIXED_TIME,
        }]}
        self.assertEqual(towerctl.check_evidence(self.root, record), [])

    # -- 9. --spec must stay inside the root ----------------------------
    def test_task_new_rejects_spec_outside_root(self) -> None:
        cp = run_cli(self.root, "task-new", "--spec", str(self.outside_spec))
        self.assert_fails(cp, "outside tower root")
        self.assertFalse((self.root / "tasks" / "T-OUTSIDE").exists())

    # -- 10. spec.worktree must stay inside the root --------------------
    def test_task_new_rejects_worktree_outside_root(self) -> None:
        spec = read_json(self.spec_path)
        spec["id"] = "T-NEW"
        spec["worktree"] = "../.."
        write_json(self.spec_path, spec)
        cp = run_cli(self.root, "task-new", "--spec",
                     str(self.root / "specs" / "task.spec.json"))
        self.assert_fails(cp, "outside tower root")

    # -- 11. --file must stay inside the root ---------------------------
    def test_envelope_new_rejects_file_outside_root(self) -> None:
        cp = run_cli(self.root, "envelope-new", "--task", TASK_ID,
                     "--file", str(self.outside_envelope))
        self.assert_fails(cp, "outside tower root")

    # -- 12. a traversal --task is rejected before the envelope gate ----
    def test_envelope_new_rejects_task_traversal(self) -> None:
        cp = run_cli(self.root, "envelope-new", "--task", "../x",
                     "--file", str(self.root / "specs" / "task.spec.json"))
        self.assert_fails(cp, "invalid id")

    # -- 13. repository outside root's parent is refused ----------------
    def test_envelope_repository_outside_parent_is_rejected(self) -> None:
        self.write_envelope("ENV-REPO", repository="../..")
        cp = run_cli(self.root, "merge-check", "--envelope", "ENV-REPO")
        self.assert_fails(cp, "outside tower root")

    # -- 14. repository '..' (kit layout) is still allowed --------------
    def test_envelope_repository_parent_is_allowed(self) -> None:
        self.write_envelope("ENV-PARENT", repository="..")
        cp = run_cli(self.root, "merge-check", "--envelope", "ENV-PARENT")
        self.assertEqual(cp.returncode, 2,
                         msg=f"git checks should still fail\n{cp.stdout}")
        self.assertNotIn("outside tower root", cp.stdout.lower())
        json.loads(cp.stdout)
        self.assertEqual(
            towerctl.ensure_within(self.root, self.base, allow_parent=True),
            self.base.resolve())

    # -- 15. missing record: exactly one JSON object, one task check ----
    def test_merge_check_missing_record_emits_single_json_object(self) -> None:
        self.write_envelope("ENV-MISSING", task="MISSING-001")
        cp = run_cli(self.root, "merge-check", "--envelope", "ENV-MISSING")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)  # raises on a second JSON object
        self.assertFalse(payload["ok"])
        self.assertEqual(cp.stdout.count('"task record"'), 1)
        self.assertNotIn("task accepted/closed", cp.stdout)
        task_checks = [c for c in payload["errors"] if c["name"] == "task record"]
        self.assertEqual(len(task_checks), 1)
        self.assertFalse(task_checks[0]["ok"])

    # -- 16. closeout points at the merge queue / MERGE.md --------------
    def test_close_closeout_has_no_not_performed(self) -> None:
        evidence = [{
            "id": "E-001",
            "path": f"pilot/worktrees/{TASK_ID}/ART.txt",
            "sha256": sha256_file(self.artifact),
            "bytes": self.artifact.stat().st_size,
            "at": FIXED_TIME,
        }]
        self.write_record(status="accepted", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          decision={"id": "D-1"}, evidence=evidence)
        cp = run_cli(self.root, "close", "--task", TASK_ID)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        text = (self.root / "tasks" / TASK_ID / "CLOSEOUT.md").read_text(
            encoding="utf-8")
        self.assertNotIn("not performed", text.lower())
        self.assertIn("supervision/MERGE_QUEUE.json", text)
        self.assertIn(f"tasks/{TASK_ID}/MERGE.md", text)
        self.assertIn("(owner gate)", text)
        self.assertEqual(self.load_record()["status"], "closed")


# ---------------------------------------------------------------------------
# post-merge MERGE.md artefact
# ---------------------------------------------------------------------------
class PostMergeArtifactTestCase(unittest.TestCase):
    """A verified merge writes ``tasks/<id>/MERGE.md`` for the closeout."""

    TASK = "T-PM-001"
    ENVELOPE = "ENV-PM-001"
    ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
    BRANCH = "feature/post-merge-artifact"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-merge-record-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{self.TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / self.TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / self.TASK / "record.json", {
            "schema": "tower/task@1",
            "id": self.TASK,
            "title": "post-merge artefact",
            "status": "accepted",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{self.TASK}/evidence/proof.txt",
                "sha256": sha256_file(proof),
                "bytes": proof.stat().st_size,
                "at": FIXED_TIME,
            }],
        })
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-primary"},
            "owner": {"name": "mac"}, "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": self.ENVELOPE, "task": self.TASK,
                "branch": self.BRANCH, "base": "main",
                "status": "WAITING", "added_at": FIXED_TIME,
            }],
        })
        self.init_repo()
        self.write_envelope()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def commit_all(self, message: str) -> str:
        add = run_git(self.kit, "add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        commit = run_git(self.kit, "-c", "commit.gpgsign=false",
                         "commit", "-m", message)
        self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(run_git(self.kit, "init").returncode, 0)
        self.assertEqual(
            run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode,
            0)
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
        self.commit_all("base")
        self.assertEqual(
            run_git(self.kit, "checkout", "-b", self.BRANCH).returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.kit / self.ENVELOPE_PATH, {"envelope_id": self.ENVELOPE})
        self.envelope_head = self.commit_all("envelope")
        self.assertEqual(run_git(self.kit, "checkout", "main").returncode, 0)

    def write_envelope(self) -> None:
        write_json(self.root / "supervision" / "envelopes"
                   / f"{self.ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1",
            "envelope_id": self.ENVELOPE,
            "task": self.TASK,
            "repository": "..",
            "branch": self.BRANCH,
            "base": "main",
            "envelope_path": self.ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head,
            "status": "DRAFT",
        })

    def test_post_merge_success_writes_merge_md(self) -> None:
        merged = run_cli(self.root, "merge", "--envelope", self.ENVELOPE,
                         "--role", "supervisor", "--supervisor", "sup-x")
        self.assertEqual(merged.returncode, 0,
                         msg=merged.stdout + merged.stderr)
        self.commit_all("state after merge")
        verified = run_cli(self.root, "post-merge", "--envelope", self.ENVELOPE,
                           "--result", "PASS")
        self.assertEqual(verified.returncode, 0,
                         msg=verified.stdout + verified.stderr)
        payload = json.loads(verified.stdout)
        merge_md = self.root / "tasks" / self.TASK / "MERGE.md"
        self.assertTrue(merge_md.exists(), msg=payload)
        self.assertEqual(payload["merge_record"],
                         f"tasks/{self.TASK}/MERGE.md")
        text = merge_md.read_text(encoding="utf-8")
        envelope = read_json(self.root / "supervision" / "envelopes"
                             / f"{self.ENVELOPE}.json")
        self.assertIn(f"`{self.ENVELOPE}`", text)
        self.assertIn(self.implementation_head, text)
        self.assertIn(envelope["merge_commit"], text)
        self.assertIn("POST_MERGE_VERIFIED", text)
        self.assertIn("Post-merge checks: 4/4", text)
        self.assertIn("Verified at:", text)


# ---------------------------------------------------------------------------
# ledger lock deadline (Windows ACL busy-wait)
# ---------------------------------------------------------------------------
class LedgerLockDeadlineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-lock-deadline-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        self.lock = self.root / "ledger" / ".lock"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows ACL PermissionError path")
    def test_persistent_permission_error_without_lock_hits_deadline(self) -> None:
        with mock.patch.object(towerctl.os, "open",
                               side_effect=PermissionError(13, "denied")):
            started = time.monotonic()
            with self.assertRaises(towerctl.LedgerLockTimeout):
                towerctl._acquire_lock_file(self.lock, 0.2, 60.0)
            elapsed = time.monotonic() - started
        self.assertFalse(self.lock.exists())
        self.assertGreaterEqual(elapsed, 0.1,
                                "the deadline must be a real wait, not a guess")
        self.assertLess(elapsed, 3.0,
                        f"busy-waited for {elapsed:.1f}s instead of timing out")

    def test_normal_contention_is_not_an_immediate_timeout(self) -> None:
        self.lock.write_text("held by someone else\n", encoding="utf-8")
        started = time.monotonic()
        with self.assertRaises(towerctl.LedgerLockTimeout):
            towerctl._acquire_lock_file(self.lock, 0.3, 60.0)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.2,
                                "a fresh lock is contention, not a timeout")
        self.assertLess(elapsed, 2.0)
        self.assertTrue(self.lock.exists(),
                        "someone else's lock must never be removed")


if __name__ == "__main__":
    unittest.main()
