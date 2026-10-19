"""Regression tests for towerctl gate hardening (PILOT-002).

Each test builds an isolated tower root with ``tempfile``, writes the JSON
state directly, and drives the real CLI through ``subprocess`` so that exit
codes are asserted exactly as a caller would observe them.

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
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
TASK_ID = "TEST-001"
ENVELOPE_ID = "ENV-TEST-001"
FIXED_TIME = "2026-10-19T00:00:00+08:00"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


class TowerGateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-gates-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for d in ("primary", "ledger", "specs",
                  f"tasks/{TASK_ID}/evidence",
                  f"pilot/worktrees/{TASK_ID}"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.spec_path = self.root / "specs" / "task.spec.json"
        self.spec_data = {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "gate regression",
            "authority": "workspace_write",
            "scope": ["exercise towerctl gates"],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
        }
        self.write_spec()
        self.record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "gate regression",
            "status": "ready",
            "authority": "workspace_write",
            "scope": ["exercise towerctl gates"],
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "spec_path": "specs/task.spec.json",
            "spec_sha256": sha256(self.spec_path),
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
        self.task_md = self.root / "tasks" / TASK_ID / "TASK.md"
        self.task_md.write_text(f"# {TASK_ID} — gate regression\n", encoding="utf-8")
        (self.root / "primary" / "TASK_BOARD.json").write_text(
            json.dumps({"schema": "tower/task-board@1", "tasks": []},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixtures ---------------------------------------------------------
    def write_spec(self) -> None:
        self.spec_path.write_text(
            json.dumps(self.spec_data, ensure_ascii=False, indent=2), encoding="utf-8")

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

    def valid_evidence(self) -> list[dict]:
        dest = self.root / "tasks" / TASK_ID / "evidence" / "proof.txt"
        dest.write_text("proof of work\n", encoding="utf-8")
        return [{
            "id": "E-001",
            "path": f"tasks/{TASK_ID}/evidence/proof.txt",
            "sha256": sha256(dest),
            "bytes": dest.stat().st_size,
            "at": FIXED_TIME,
        }]

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8",
        )

    def assert_fails(self, cp: subprocess.CompletedProcess, *keywords: str) -> None:
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = (cp.stdout + cp.stderr).lower()
        for keyword in keywords:
            self.assertIn(keyword.lower(), blob,
                          msg=f"missing {keyword!r} in stdout={cp.stdout}\nstderr={cp.stderr}")

    def prepare_merge(self, *, base: str = "main", branch: str = "feature",
                      entry_status: str = "WAITING") -> Path:
        repo = self.root / "pilot" / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        self.assertEqual(git(repo, "init").returncode, 0)
        self.assertEqual(git(repo, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        git(repo, "add", "README.md")
        self.assertEqual(
            git(repo, "-c", "commit.gpgsign=false", "commit", "-m", "base").returncode, 0)
        if branch != "main":
            self.assertEqual(git(repo, "checkout", "-b", branch).returncode, 0)
        (self.root / "primary" / "CURRENT_STATE.json").write_text(
            json.dumps({"schema": "tower/current-state@1", "role": "primary",
                        "primary": {"id": "ctl-test"}, "owner": {"name": "mac"}}),
            encoding="utf-8")
        supervision = self.root / "supervision"
        (supervision / "envelopes").mkdir(parents=True, exist_ok=True)
        (supervision / "CURRENT_STATE.json").write_text(
            json.dumps({"schema": "tower/supervision-state@1", "role": "supervision",
                        "phase": "TEST", "supervisor": {"id": "sup-test"}}),
            encoding="utf-8")
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        envelope = {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
            "repository": "pilot/repo",
            "branch": branch,
            "base": base,
            "envelope_path": f"envelopes/{ENVELOPE_ID}.json",
            "implementation_head_sha": head,
            "status": "DRAFT",
        }
        (supervision / "envelopes" / f"{ENVELOPE_ID}.json").write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        queue = {"schema": "tower/merge-queue@1", "entries": [{
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
            "branch": branch,
            "base": base,
            "status": entry_status,
            "added_at": FIXED_TIME,
        }]}
        (supervision / "MERGE_QUEUE.json").write_text(
            json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        return repo

    def queue_status(self) -> str:
        path = self.root / "supervision" / "MERGE_QUEUE.json"
        queue = json.loads(path.read_text(encoding="utf-8"))
        return queue["entries"][0]["status"]

    # -- 1. dispatch ------------------------------------------------------
    def test_dispatch_rejects_missing_spec_gate(self) -> None:
        self.write_record(spec_gate=None)
        cp = self.run_cli("dispatch", "--task", TASK_ID, "--executor", "exec-a")
        self.assert_fails(cp, "spec")
        self.assertEqual(self.load_record()["status"], "ready")

    def test_dispatch_rejects_legacy_card_without_spec_path(self) -> None:
        self.write_record(spec_path=None, spec_sha256=None, spec_gate=None)
        cp = self.run_cli("dispatch", "--task", TASK_ID, "--executor", "exec-a")
        self.assert_fails(cp, "spec")
        self.assertEqual(self.load_record()["status"], "ready")

    def test_dispatch_rejects_spec_changed_after_task_new(self) -> None:
        self.spec_data["acceptance"] = ["changed after task-new"]
        self.write_spec()
        cp = self.run_cli("dispatch", "--task", TASK_ID, "--executor", "exec-a")
        self.assert_fails(cp, "spec", "changed")
        self.assertEqual(self.load_record()["status"], "ready")

    def test_dispatch_rejects_missing_task_md(self) -> None:
        self.task_md.unlink()
        cp = self.run_cli("dispatch", "--task", TASK_ID, "--executor", "exec-a")
        self.assert_fails(cp, "task.md")
        self.assertEqual(self.load_record()["status"], "ready")

    def test_dispatch_succeeds_when_spec_gate_is_fresh(self) -> None:
        cp = self.run_cli("dispatch", "--task", TASK_ID, "--executor", "exec-a")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["executor"], "exec-a")

    # -- 2. check --phase spec -------------------------------------------
    def test_check_spec_rejects_legacy_card_without_spec_path(self) -> None:
        self.write_record(spec_path=None, spec_sha256=None, spec_gate=None)
        cp = self.run_cli("check", "--task", TASK_ID, "--phase", "spec")
        self.assert_fails(cp, "spec")
        self.assertIsNone(self.load_record()["spec_gate"])

    def test_check_spec_passes_and_records_gate_for_valid_spec(self) -> None:
        self.write_record(spec_gate=None)
        ledger = self.root / "ledger" / "primary.jsonl"
        ledger.write_text(json.dumps({
            "seq": 1, "at": FIXED_TIME, "type": "SPEC_APPROVED",
            "actor": "rev-a", "payload": {"task": TASK_ID, "by": "rev-a"},
        }) + "\n", encoding="utf-8")
        cp = self.run_cli("check", "--task", TASK_ID, "--phase", "spec")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["spec_gate"], "PASS")

    # -- 6. check --phase ready vs live spec hash ------------------------
    def test_check_ready_rejects_spec_changed_after_gate_pass(self) -> None:
        self.spec_data["acceptance"] = ["rewritten in place"]
        self.write_spec()
        cp = self.run_cli("check", "--task", TASK_ID, "--phase", "ready")
        self.assert_fails(cp, "spec", "changed")

    def test_check_ready_rejects_legacy_card_without_spec_path(self) -> None:
        self.write_record(spec_path=None, spec_sha256=None, spec_gate=None)
        cp = self.run_cli("check", "--task", TASK_ID, "--phase", "ready")
        self.assert_fails(cp, "spec")

    # -- 4. check --phase review -----------------------------------------
    def test_check_review_rejects_empty_reviewer(self) -> None:
        self.write_record(status="reviewed", executor="exec-a",
                          review={"reviewer": "   ", "verdict": "PASS"},
                          evidence=self.valid_evidence())
        cp = self.run_cli("check", "--task", TASK_ID, "--phase", "review")
        self.assert_fails(cp, "reviewer")

    # -- 3. checkback ----------------------------------------------------
    def test_checkback_rejects_whitespace_only_reviewer(self) -> None:
        self.write_record(status="delivered", executor="exec-a")
        cp = self.run_cli("checkback", "--task", TASK_ID,
                          "--reviewer", "   ", "--verdict", "PASS")
        self.assert_fails(cp, "reviewer")
        record = self.load_record()
        self.assertIsNone(record["review"])
        self.assertEqual(record["status"], "delivered")

    def test_checkback_rejects_reviewer_equal_to_executor(self) -> None:
        self.write_record(status="delivered", executor="exec-a")
        cp = self.run_cli("checkback", "--task", TASK_ID,
                          "--reviewer", "exec-a", "--verdict", "PASS")
        self.assert_fails(cp, "reviewer")
        self.assertIsNone(self.load_record()["review"])

    def test_checkback_normalizes_reviewer(self) -> None:
        self.write_record(status="delivered", executor="exec-a")
        cp = self.run_cli("checkback", "--task", TASK_ID,
                          "--reviewer", "  rev-a  ", "--verdict", "PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        record = self.load_record()
        self.assertEqual(record["review"]["reviewer"], "rev-a")
        self.assertEqual(record["status"], "reviewed")

    # -- 5. accept / close inline evidence -------------------------------
    def test_accept_rejects_missing_evidence(self) -> None:
        self.write_record(status="reviewed", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          evidence=[])
        cp = self.run_cli("accept", "--task", TASK_ID, "--decision", "D-1")
        self.assert_fails(cp, "evidence")
        record = self.load_record()
        self.assertEqual(record["status"], "reviewed")
        self.assertIsNone(record["decision"])

    def test_accept_rejects_evidence_hash_mismatch(self) -> None:
        evidence = self.valid_evidence()
        evidence[0]["sha256"] = "0" * 64
        self.write_record(status="reviewed", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          evidence=evidence)
        cp = self.run_cli("accept", "--task", TASK_ID, "--decision", "D-1")
        self.assert_fails(cp, "evidence")
        record = self.load_record()
        self.assertEqual(record["status"], "reviewed")
        self.assertIsNone(record["decision"])

    def test_close_rejects_missing_task_md(self) -> None:
        self.write_record(status="accepted", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          decision={"id": "D-1"}, evidence=self.valid_evidence())
        self.task_md.unlink()
        cp = self.run_cli("close", "--task", TASK_ID)
        self.assert_fails(cp, "task.md")
        self.assertEqual(self.load_record()["status"], "accepted")
        self.assertFalse((self.root / "tasks" / TASK_ID / "CLOSEOUT.md").exists())

    def test_close_rejects_evidence_hash_mismatch(self) -> None:
        evidence = self.valid_evidence()
        evidence[0]["sha256"] = "f" * 64
        self.write_record(status="accepted", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          decision={"id": "D-1"}, evidence=evidence)
        cp = self.run_cli("close", "--task", TASK_ID)
        self.assert_fails(cp, "evidence")
        self.assertEqual(self.load_record()["status"], "accepted")

    def test_accept_then_close_happy_path(self) -> None:
        self.write_record(status="reviewed", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          evidence=self.valid_evidence())
        cp = self.run_cli("accept", "--task", TASK_ID, "--decision", "D-1")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["status"], "accepted")
        cp = self.run_cli("close", "--task", TASK_ID)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["status"], "closed")
        self.assertTrue((self.root / "tasks" / TASK_ID / "CLOSEOUT.md").exists())

    # -- 7. merge branch assertion and queue precondition ----------------
    def test_merge_rejects_current_branch_not_envelope_base(self) -> None:
        self.prepare_merge(base="main", branch="feature")
        cp = self.run_cli("merge", "--envelope", ENVELOPE_ID,
                          "--role", "supervisor", "--supervisor", "sup-x")
        self.assert_fails(cp, "base")
        self.assertNotEqual(self.queue_status(), "MERGED")
        self.assertEqual(self.queue_status(), "CORRECTION_REQUIRED")
        envelope = json.loads(
            (self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json")
            .read_text(encoding="utf-8"))
        self.assertNotEqual(envelope["status"], "MERGED")

    def test_merge_rejects_queue_entry_not_waiting(self) -> None:
        self.prepare_merge(base="main", branch="main", entry_status="MERGING")
        cp = self.run_cli("merge", "--envelope", ENVELOPE_ID,
                          "--role", "supervisor", "--supervisor", "sup-x")
        self.assert_fails(cp, "waiting")
        self.assertEqual(self.queue_status(), "MERGING")


if __name__ == "__main__":
    unittest.main()
