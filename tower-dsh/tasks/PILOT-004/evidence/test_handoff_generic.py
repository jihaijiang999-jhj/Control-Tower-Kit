"""Handoff generation/check generalization tests (PILOT-004).

The regression under test: ``handoff-new`` and ``current_snapshot`` used to
hard-code ``PILOT-001`` / ``ENV-PILOT-001`` and the "Phase 2 双塔已验证"
paragraph, so a package could only ever describe the first pilot.

Each test builds an isolated tower root under ``tempfile`` plus a throw-away
git repository and git worktrees, drives the real CLI through ``subprocess``,
and inspects the generated ``HANDOFF.md`` / ``package.json``.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
FIXED_TIME = "2026-10-19T00:00:00+08:00"
PACKAGE = "HANDOFF-TEST-001"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text: str, name: str) -> str:
    """Return the ``## §<name>`` section (``0`` must not match ``0a``)."""
    pattern = re.compile(rf"^## §{re.escape(name)}(?:\s|$)", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"section §{name} missing from handoff text")
    rest = text[match.end():]
    following = re.search(r"^## §", rest, re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


class HandoffGenericTestCase(unittest.TestCase):
    """Fixture: a complete mini tower with two tasks and two queue entries."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-handoff-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower"
        for d in ("primary", "supervision", "shared", "ledger", "tasks", "pilot"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")
        self.write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "phase": "HANDOFF_ACTIVE",
            "primary": {"id": "ctl-test"},
            "owner": {"name": "mac"},
            "next_action": "等待 owner 指令",
        })
        self.write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "tower_id": "tower-dsh",
            "role": "supervision",
            "phase": "PHASE_TEST",
            "supervisor": {"id": "sup-test"},
        })
        self.repo = self.root / "pilot" / "repo"
        self.repo.mkdir(parents=True)
        cp = self.git("init")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        self.assertEqual(self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", "base")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        self.board_tasks: list[dict] = []
        self.queue_entries: list[dict] = []
        self.add_task("PILOT-001", "closed", "2026-10-19T12:00:00+08:00",
                      next_text="merged via ENV-PILOT-001", evidence=True)
        self.add_task("PILOT-004", "ready", "2026-10-19T16:00:00+08:00",
                      next_text="等待 dispatch")
        self.add_envelope("ENV-PILOT-001", "PILOT-001", "POST_MERGE_VERIFIED",
                          "2026-10-19T12:00:00+08:00", merge_commit="a" * 40)
        self.add_envelope("ENV-PILOT-004", "PILOT-004", "WAITING",
                          "2026-10-19T16:00:00+08:00")
        # The profile points at the older pilot; a handoff for another task must
        # not inherit it.
        self.write_profile()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_board(self) -> None:
        self.write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tower_id": "tower-dsh",
            "tasks": self.board_tasks,
            "updated_at": FIXED_TIME,
        })

    def write_queue(self) -> None:
        self.write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": self.queue_entries,
            "updated_at": FIXED_TIME,
        })

    def write_profile(self, *, task: str = "PILOT-001", repo: str = "pilot/repo",
                      worktree: str = "pilot/worktrees/PILOT-001") -> None:
        self.write_json(self.root / "shared" / "PROJECT_PROFILE.json", {
            "schema": "tower/project-profile@1",
            "tower_id": "tower-dsh",
            "tower_root": str(self.root),
            "pilot": {"task": task, "repo": repo, "worktree": worktree},
        })

    def add_task(self, task_id: str, status: str, updated_at: str,
                 next_text: str = "", evidence: bool = False) -> None:
        tdir = self.root / "tasks" / task_id
        (tdir / "evidence").mkdir(parents=True, exist_ok=True)
        (tdir / "TASK.md").write_text(f"# {task_id} — test task\n", encoding="utf-8")
        evidence_entries: list[dict] = []
        if evidence:
            proof = tdir / "evidence" / "proof.txt"
            proof.write_text(f"proof for {task_id}\n", encoding="utf-8")
            evidence_entries = [{
                "id": "E-001",
                "path": f"tasks/{task_id}/evidence/proof.txt",
                "sha256": sha256(proof),
                "bytes": proof.stat().st_size,
                "at": updated_at,
            }]
        worktree = self.root / "pilot" / "worktrees" / task_id
        cp = self.git("worktree", "add", "--detach", str(worktree), "HEAD")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        record = {
            "schema": "tower/task@1",
            "id": task_id,
            "title": f"{task_id} title",
            "status": status,
            "authority": "workspace_write",
            "scope": ["test"],
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": f"pilot/worktrees/{task_id}",
            "executor": None,
            "dispatch": None,
            "review": None,
            "decision": None,
            "closeout": None,
            "evidence": evidence_entries,
            "created_at": updated_at,
            "updated_at": updated_at,
            "next": next_text,
        }
        self.write_json(tdir / "record.json", record)
        self.board_tasks = [t for t in self.board_tasks if t["id"] != task_id] + [{
            "id": task_id,
            "title": record["title"],
            "status": status,
            "authority": "workspace_write",
            "executor": None,
            "reviewer": None,
            "next": next_text,
            "updated_at": updated_at,
        }]
        self.write_board()

    def set_task_status(self, task_id: str, status: str) -> None:
        for task in self.board_tasks:
            if task["id"] == task_id:
                task["status"] = status
        self.write_board()
        path = self.root / "tasks" / task_id / "record.json"
        record = self.read_json(path)
        record["status"] = status
        self.write_json(path, record)

    def add_envelope(self, envelope_id: str, task: str, status: str,
                     added_at: str, merge_commit: str = "") -> None:
        entry = {
            "envelope_id": envelope_id,
            "task": task,
            "branch": f"pilot/{task}",
            "base": "main",
            "status": status,
            "added_at": added_at,
        }
        if merge_commit:
            entry["merge_commit"] = merge_commit
        self.queue_entries = [e for e in self.queue_entries
                              if e["envelope_id"] != envelope_id] + [entry]
        self.write_queue()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        # The CLI prints UTF-8 JSON; force the child's piped stdio to UTF-8 so
        # Windows' locale encoding cannot corrupt section markers like ``§0``.
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def handoff_new(self, *extra: str, package: str = PACKAGE) -> None:
        cp = self.run_cli("handoff-new", "--package", package, *extra)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")

    def handoff_text(self, package: str = PACKAGE) -> str:
        return (self.root / "handoffs" / package / "HANDOFF.md").read_text(
            encoding="utf-8")

    def handoff_pkg(self, package: str = PACKAGE) -> dict:
        return self.read_json(self.root / "handoffs" / package / "package.json")

    # -- 1. explicit task drives §0/§3/§4/§7 -----------------------------
    def test_explicit_task_drives_sections_0_3_4_7(self) -> None:
        self.handoff_new("--task", "PILOT-004")
        text = self.handoff_text()
        for name in ("0", "3", "4", "7"):
            part = section(text, name)
            self.assertIn("PILOT-004", part, msg=part)
            self.assertNotIn("PILOT-001", part, msg=part)
        self.assertNotIn("PILOT-001", text)
        self.assertEqual(self.handoff_pkg()["task"], "PILOT-004")

    # -- 2. §4 lists every non-closed task -------------------------------
    def test_section4_lists_all_open_tasks(self) -> None:
        self.add_task("PILOT-005", "dispatched", "2026-10-19T17:00:00+08:00",
                      next_text="等待 executor 交付")
        self.handoff_new("--task", "PILOT-004")
        part = section(self.handoff_text(), "4")
        self.assertIn("PILOT-004", part)
        self.assertIn("PILOT-005", part)
        self.assertIn("`dispatched`", part)
        self.assertNotIn("PILOT-001", part)

    # -- 3. §4 says there is nothing in flight ---------------------------
    def test_section4_reports_no_open_tasks(self) -> None:
        self.set_task_status("PILOT-004", "closed")
        self.handoff_new("--task", "PILOT-001")
        part = section(self.handoff_text(), "4")
        self.assertIn("无在途任务", part)
        self.assertNotIn("PILOT-004", part)

    # -- 4. explicit envelope among many --------------------------------
    def test_explicit_envelope_is_selected(self) -> None:
        self.handoff_new("--task", "PILOT-001", "--envelope", "ENV-PILOT-001")
        part = section(self.handoff_text(), "0")
        self.assertIn("ENV-PILOT-001", part)
        self.assertIn("POST_MERGE_VERIFIED", part)
        self.assertNotIn("ENV-PILOT-004", part)
        self.assertEqual(self.handoff_pkg()["envelope"], "ENV-PILOT-001")

    # -- 5. default task: the single non-closed task ---------------------
    def test_default_task_uses_single_open_task(self) -> None:
        self.handoff_new()
        self.assertEqual(self.handoff_pkg()["task"], "PILOT-004")
        self.assertIn("PILOT-004", section(self.handoff_text(), "1"))

    # -- 6. default task: newest when several are open -------------------
    def test_default_task_uses_newest_open_task(self) -> None:
        self.add_task("PILOT-005", "dispatched", "2026-10-19T18:00:00+08:00",
                      next_text="等待 executor 交付")
        self.handoff_new()
        self.assertEqual(self.handoff_pkg()["task"], "PILOT-005")

    # -- 7. default envelope: newest added_at ----------------------------
    def test_default_envelope_uses_newest_added(self) -> None:
        self.handoff_new()
        self.assertEqual(self.handoff_pkg()["envelope"], "ENV-PILOT-004")
        self.assertIn("ENV-PILOT-004", section(self.handoff_text(), "0"))

    # -- 8. §1 is generated, not the hard-coded Phase 2 text --------------
    def test_section1_reflects_live_state_without_phase2_text(self) -> None:
        self.handoff_new("--task", "PILOT-004", "--envelope", "ENV-PILOT-004")
        part = section(self.handoff_text(), "1")
        self.assertNotIn("Phase 2", part)
        self.assertNotIn("双塔已验证", part)
        for needle in ("HANDOFF_ACTIVE", "PILOT-004", "`ready`",
                       "ENV-PILOT-004", "`WAITING`"):
            self.assertIn(needle, part, msg=part)

    # -- 9. a freshly generated package passes handoff-check --------------
    def test_generated_package_passes_handoff_check(self) -> None:
        self.handoff_new("--task", "PILOT-001", "--envelope", "ENV-PILOT-001")
        cp = self.run_cli("handoff-check", "--package", PACKAGE)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["checks"]), 21, payload["checks"])
        failed = [c for c in payload["checks"] if not c["ok"]]
        self.assertEqual(failed, [])

    # -- 10. handoff-check uses the package's own task/envelope ----------
    def test_handoff_check_uses_package_task_and_envelope(self) -> None:
        self.handoff_new("--task", "PILOT-001", "--envelope", "ENV-PILOT-001")
        # A newer open task and a newer waiting envelope now win the default
        # selection; the package must still be checked against its own pair.
        self.add_task("PILOT-005", "dispatched", "2026-10-19T18:00:00+08:00",
                      next_text="等待 executor 交付")
        self.add_envelope("ENV-PILOT-005", "PILOT-005", "WAITING",
                          "2026-10-19T18:00:00+08:00")
        cp = self.run_cli("handoff-check", "--package", PACKAGE)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(len(payload["checks"]), 21)

    # -- 11. legacy package without task/envelope fields -----------------
    def test_legacy_package_matches_task_by_evidence_hashes(self) -> None:
        self.handoff_new("--task", "PILOT-001", "--envelope", "ENV-PILOT-001")
        package_path = self.root / "handoffs" / PACKAGE / "package.json"
        pkg = self.read_json(package_path)
        self.assertIn("task", pkg)
        # Simulate HANDOFF-PILOT-001: no top-level task/envelope fields.
        pkg.pop("task")
        pkg.pop("envelope")
        self.write_json(package_path, pkg)
        # A newer open task would win default selection; evidence matching must
        # keep the legacy package on PILOT-001.
        self.add_task("PILOT-005", "dispatched", "2026-10-19T18:00:00+08:00",
                      next_text="等待 executor 交付")
        self.add_envelope("ENV-PILOT-005", "PILOT-005", "WAITING",
                          "2026-10-19T18:00:00+08:00")
        cp = self.run_cli("handoff-check", "--package", PACKAGE)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        task_check = next(c for c in payload["checks"] if c["name"] == "task still closed")
        self.assertTrue(task_check["ok"], task_check)

    # -- 12. profile works for the selected task, not for another one ----
    def test_profile_worktree_is_not_reused_for_another_task(self) -> None:
        self.write_profile(task="PILOT-001", repo="pilot/repo",
                           worktree="pilot/worktrees/PILOT-001")
        self.handoff_new("--task", "PILOT-001")
        part = section(self.handoff_text(), "3")
        self.assertIn(str(self.root / "pilot" / "repo"), part)
        self.assertIn(str(self.root / "pilot" / "worktrees" / "PILOT-001"), part)
        version = (f"{sys.version_info.major}.{sys.version_info.minor}."
                   f"{sys.version_info.micro}")
        self.assertIn(version, part)  # real Python version, not hard-coded "3.12"

    # -- 13. missing git repo/worktree does not raise --------------------
    def test_missing_git_paths_yield_empty_hashes(self) -> None:
        shutil.rmtree(self.root / "pilot" / "worktrees", ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)
        self.handoff_new("--task", "PILOT-004")
        text = self.handoff_text()
        self.assertIn("| main SHA | `` |", text)
        self.assertIn("| worktree head | `` |", text)

    # -- 14. explicit unknown envelope is rejected ----------------------
    def test_explicit_unknown_envelope_fails(self) -> None:
        cp = self.run_cli("handoff-new", "--package", PACKAGE,
                          "--envelope", "ENV-DOES-NOT-EXIST")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope not found", cp.stdout)


if __name__ == "__main__":
    unittest.main()
