"""Tests for the PILOT-041 deliver scope gate and dispatch provenance.

``towerctl deliver`` must prove that the task worktree's committed diff is a
subset of the task card's ``allowed_paths`` *before* it copies any evidence.
The gate is skipped only when the tower root is outside a git repository
(fixtures / legacy towers); every git failure is fail-closed.

The fixtures below build a minimal tower inside a real git repository and give
the task a real ``git worktree`` (``git worktree add``) so ``merge-base main
HEAD`` and ``git diff --name-only`` are exercised for real, not mocked.  The
worktree layout mirrors the tower: the tower root is ``<kit>/tower-dsh`` and the
task worktree is ``<tower>/pilot/worktrees/<ID>``, a separate checkout whose
root is the repository root the diff is taken in.

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
TASK_ID = "TEST-041"
FIXED_TIME = "2026-10-19T00:00:00+08:00"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
PROOF_REL = "work/proof.txt"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def task_record(*, status: str = "dispatched", allowed_paths=None) -> dict:
    return {
        "schema": "tower/task@1",
        "id": TASK_ID,
        "title": "deliver scope gate",
        "status": status,
        "authority": "workspace_write",
        "scope": ["exercise the deliver scope gate"],
        "allowed_paths": allowed_paths if allowed_paths is not None else [
            f"{WORKTREE_REL}/tower-dsh/tools/x.py",
        ],
        "forbidden": ["merge"],
        "acceptance": ["tests pass"],
        "depends_on": [],
        "worktree": WORKTREE_REL,
        "executor": "exec-a",
        "dispatch": {"executor": "exec-a", "worktree": WORKTREE_REL,
                     "at": FIXED_TIME},
        "evidence": [],
        "review": None,
        "decision": None,
        "closeout": None,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        "next": "等待 executor 交付",
    }


class DeliverScopeGateTestCase(unittest.TestCase):
    """Deliver against a tower whose task worktree is a real git worktree."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-deliver-scope-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.tower = self.kit / "tower-dsh"
        self.worktree = self.tower / WORKTREE_REL
        self.write_source_tree()
        self.init_kit()
        self.add_worktree()
        self.write_tower_state()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixtures ---------------------------------------------------------
    def write_source_tree(self) -> None:
        """The committed repository content (also the worktree checkout)."""
        self.kit.mkdir(parents=True, exist_ok=True)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / ".gitignore").write_text(
            "tower-dsh/pilot/worktrees/\n", encoding="utf-8")
        (self.tower / "tools").mkdir(parents=True, exist_ok=True)
        (self.tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (self.tower / "pilot").mkdir(parents=True, exist_ok=True)
        (self.tower / "pilot" / f"{TASK_ID}.spec.json").write_text(
            "{}\n", encoding="utf-8")
        (self.tower / "pilot" / "other.json").write_text("{}\n", encoding="utf-8")

    def init_kit(self) -> None:
        self.assertEqual(run_git(self.kit, "init").returncode, 0)
        self.assertEqual(
            run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        self.assertEqual(run_git(self.kit, "add", "-A").returncode, 0)
        cp = run_git(self.kit, "commit", "-m", "base")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

    def add_worktree(self) -> None:
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        cp = run_git(self.kit, "worktree", "add", str(self.worktree),
                     "-b", f"pilot/{TASK_ID}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

    def write_tower_state(self) -> None:
        write_json(self.tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-test"}, "owner": {"name": "mac"},
        })
        write_json(self.tower / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.tower / "ledger").mkdir(parents=True, exist_ok=True)
        (self.tower / "ledger" / "primary.jsonl").touch()
        self.write_record()

    def write_record(self, **overrides) -> None:
        record = task_record()
        record.update(overrides)
        write_json(self.tower / "tasks" / TASK_ID / "record.json", record)

    def load_record(self) -> dict:
        return read_json(self.tower / "tasks" / TASK_ID / "record.json")

    def ledger_events(self) -> list[dict]:
        path = self.tower / "ledger" / "primary.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_worktree(self, relpath: str, text: str) -> Path:
        path = self.worktree / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit_worktree(self, message: str) -> None:
        self.assertEqual(run_git(self.worktree, "add", "-A").returncode, 0)
        cp = run_git(self.worktree, "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

    def proof(self) -> Path:
        path = self.tower / PROOF_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("proof of work\n", encoding="utf-8")
        return path

    def deliver(self) -> subprocess.CompletedProcess:
        self.proof()
        return run_cli(self.tower, "deliver", "--task", TASK_ID,
                       "--evidence", PROOF_REL)

    def evidence_dir(self) -> Path:
        return self.tower / "tasks" / TASK_ID / "evidence"

    def assert_failed_with(self, cp: subprocess.CompletedProcess, needle: str) -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = "\n".join(payload["errors"])
        self.assertIn(needle, blob)

    # -- 1. an in-scope committed change delivers ------------------------
    def test_allowed_change_committed_is_delivered(self) -> None:
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")

        cp = self.deliver()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(out["scope_check"], "checked")
        self.assertEqual(out["scope_files"], ["tower-dsh/tools/x.py"])
        self.assertEqual(out["status"], "delivered")

        record = self.load_record()
        self.assertEqual(record["status"], "delivered")
        self.assertEqual(len(record["evidence"]), 1)
        self.assertTrue((self.evidence_dir() / "proof.txt").exists())

    # -- 2. an out-of-scope committed change is rejected with zero writes -
    def test_out_of_scope_change_rejected_with_zero_writes(self) -> None:
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.write_worktree("tower-dsh/tools/y.py", "y = 2\n")
        self.commit_worktree("out of scope change")

        cp = self.deliver()
        self.assert_failed_with(cp, "tower-dsh/tools/y.py")
        self.assertNotIn("tower-dsh/tools/x.py (not in allowed_paths)",
                         "\n".join(json.loads(cp.stdout)["errors"]))

        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())
        self.assertNotIn("DELIVER", [event["type"] for event in self.ledger_events()])

    # -- 3. tracked dirt is rejected; untracked scratch/ is allowed ------
    def test_tracked_uncommitted_change_is_rejected(self) -> None:
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")
        # Same file, still tracked, now dirty in the working tree.
        self.write_worktree("tower-dsh/tools/x.py", "x = 3\n")

        cp = self.deliver()
        self.assert_failed_with(cp, "uncommitted tracked change")
        self.assertIn("tower-dsh/tools/x.py",
                      "\n".join(json.loads(cp.stdout)["errors"]))

        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())

    def test_untracked_scratch_does_not_block_delivery(self) -> None:
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")
        scratch = self.write_worktree("scratch/note.txt", "untracked scratch\n")
        self.assertTrue(scratch.exists())

        cp = self.deliver()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(self.load_record()["status"], "delivered")

    # -- 4. rev-parse failure is fail-closed, not skipped ----------------
    def test_worktree_that_is_not_a_git_checkout_fails_closed(self) -> None:
        # Replace the real checkout with a boundary that git cannot resolve:
        # a .git file pointing at a missing git directory.  The tower root is
        # still inside a git repository, so this must be exit 2.
        for child in sorted(self.worktree.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        (self.worktree / ".git").write_text(
            "gitdir: ./missing-gitdir\n", encoding="utf-8")

        cp = self.deliver()
        self.assert_failed_with(cp, "not a git repository")
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])

    # -- 4b. a rename of an out-of-scope file into an allowed path is caught -
    def test_rename_from_out_of_scope_into_allowed_is_rejected(self) -> None:
        # Only the rename target is allowed.  Rename detection must be off, so
        # the diff also lists the deleted (out-of-scope) source path.
        self.write_record(allowed_paths=[
            f"{WORKTREE_REL}/tower-dsh/tools/new.py",
        ])
        cp = run_git(self.worktree, "mv", "tower-dsh/pilot/other.json",
                     "tower-dsh/tools/new.py")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        self.commit_worktree("rename out-of-scope file into an allowed path")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/other.json")
        errors = json.loads(deliver.stdout)["errors"]
        self.assertIn(
            "out of scope change: tower-dsh/pilot/other.json (not in allowed_paths)",
            "\n".join(errors))
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())

    def test_rename_from_allowed_to_out_of_scope_is_rejected(self) -> None:
        # Default allowed_paths is tower-dsh/tools/x.py; moving it away leaves
        # the (allowed) deletion plus an out-of-scope addition.
        cp = run_git(self.worktree, "mv", "tower-dsh/tools/x.py",
                     "tower-dsh/pilot/moved.json")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        self.commit_worktree("rename allowed file out of scope")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/moved.json")
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())

    # -- 4c. a nested checkout is not the repository root -----------------
    def test_nested_checkout_is_not_the_repository_root(self) -> None:
        nested_rel = "pilot/worktrees/NESTED"
        nested = self.tower / nested_rel
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "file.txt").write_text("nested\n", encoding="utf-8")
        self.write_record(worktree=nested_rel)

        cp = self.deliver()
        self.assert_failed_with(cp, "not the repository root")
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())

    # -- 4d. a rewired .git (foreign repository) is not the tower repo ----
    def test_worktree_git_dir_pointing_at_another_repository_fails_closed(
            self) -> None:
        foreign = Path(self._tmp.name) / "foreign"
        foreign.mkdir(parents=True, exist_ok=True)
        self.assertEqual(run_git(foreign, "init").returncode, 0)
        self.assertEqual(
            run_git(foreign, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (foreign / "a.txt").write_text("a\n", encoding="utf-8")
        self.assertEqual(run_git(foreign, "add", "-A").returncode, 0)
        commit = run_git(foreign, "commit", "-m", "foreign base")
        self.assertEqual(commit.returncode, 0, msg=commit.stderr + commit.stdout)

        # Point the worktree's .git file at a repository that is not the
        # tower's repository; rev-parse still succeeds and the diff is empty,
        # so only the repository-identity check can catch it.
        gitfile = self.worktree / ".git"
        gitfile.unlink()
        gitfile.write_text(
            f"gitdir: {(foreign / '.git').as_posix()}\n", encoding="utf-8")

        cp = self.deliver()
        self.assert_failed_with(cp, "not a worktree of the tower repository")
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())

    # -- 5. a git worktree without main is fail-closed -------------------
    def test_missing_main_baseline_fails_closed(self) -> None:
        self._tmp.cleanup()
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-deliver-nomain-", ignore_cleanup_errors=True)
        kit = Path(self._tmp.name) / "kit"
        tower = kit / "tower-dsh"
        (kit / "README.md").parent.mkdir(parents=True, exist_ok=True)
        (kit / "README.md").write_text("base\n", encoding="utf-8")
        (tower / "tools").mkdir(parents=True, exist_ok=True)
        (tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(run_git(kit, "init").returncode, 0)
        self.assertEqual(
            run_git(kit, "symbolic-ref", "HEAD", "refs/heads/trunk").returncode, 0)
        self.assertEqual(run_git(kit, "add", "-A").returncode, 0)
        cp = run_git(kit, "commit", "-m", "base without main")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        worktree = tower / WORKTREE_REL
        worktree.parent.mkdir(parents=True, exist_ok=True)
        cp = run_git(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK_ID}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

        write_json(tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-test"}, "owner": {"name": "mac"},
        })
        write_json(tower / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (tower / "ledger").mkdir(parents=True, exist_ok=True)
        (tower / "ledger" / "primary.jsonl").touch()
        write_json(tower / "tasks" / TASK_ID / "record.json", task_record())
        proof = tower / PROOF_REL
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("proof\n", encoding="utf-8")

        deliver = run_cli(tower, "deliver", "--task", TASK_ID,
                          "--evidence", PROOF_REL)
        self.assert_failed_with(deliver, "merge-base")
        record = read_json(tower / "tasks" / TASK_ID / "record.json")
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse((tower / "tasks" / TASK_ID / "evidence").exists())

    # -- 6. both allowed_paths mapping branches ---------------------------
    def test_mapping_accepts_worktree_and_tower_root_paths(self) -> None:
        allowed = [
            f"{WORKTREE_REL}/tower-dsh/tools/x.py",  # inside the worktree
            f"pilot/{TASK_ID}.spec.json",            # elsewhere in the tower
        ]
        self.write_record(allowed_paths=allowed)
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.write_worktree(f"tower-dsh/pilot/{TASK_ID}.spec.json", '{"v": 2}\n')
        self.commit_worktree("both mapping branches")

        cp = self.deliver()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(set(out["scope_files"]), {
            "tower-dsh/tools/x.py",
            f"tower-dsh/pilot/{TASK_ID}.spec.json",
        })
        self.assertEqual(self.load_record()["status"], "delivered")

    def test_mapping_rejects_tower_root_out_of_scope_path(self) -> None:
        allowed = [
            f"{WORKTREE_REL}/tower-dsh/tools/x.py",
            f"pilot/{TASK_ID}.spec.json",
        ]
        self.write_record(allowed_paths=allowed)
        # ``pilot/other.json`` maps to ``tower-dsh/pilot/other.json`` and is
        # not in allowed_paths, so the delivery must be rejected.
        self.write_worktree("tower-dsh/pilot/other.json", '{"v": 2}\n')
        self.commit_worktree("out of scope tower path")

        cp = self.deliver()
        self.assert_failed_with(cp, "tower-dsh/pilot/other.json")
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())


class NonGitDeliverScopeTestCase(unittest.TestCase):
    """Deliver in a tower that is not inside a git repository is unchanged."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-deliver-nogit-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", f"tasks/{TASK_ID}",
                          f"pilot/worktrees/{TASK_ID}", "work"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-test"}, "owner": {"name": "mac"},
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.root / "ledger" / "primary.jsonl").touch()
        write_json(self.root / "tasks" / TASK_ID / "record.json", task_record())
        (self.root / PROOF_REL).write_text("proof of work\n", encoding="utf-8")
        # Make git discovery fail deterministically: a .git file pointing at a
        # missing git directory is exactly "not inside a git repository".
        (self.root / ".git").write_text("gitdir: ./missing-gitdir\n",
                                        encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_non_git_tower_skips_scope_check_and_delivers(self) -> None:
        cp = run_cli(self.root, "deliver", "--task", TASK_ID,
                     "--evidence", PROOF_REL)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual(out["scope_check"], "skipped (no git repo)")
        self.assertFalse(out["scope_checked"])
        self.assertEqual(out["status"], "delivered")
        record = read_json(self.root / "tasks" / TASK_ID / "record.json")
        self.assertEqual(record["status"], "delivered")
        self.assertEqual(len(record["evidence"]), 1)


class DispatchProvenanceTestCase(unittest.TestCase):
    """``dispatch`` records kind/model/parent in the record and the ledger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-dispatch-prov-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs", f"tasks/{TASK_ID}",
                          WORKTREE_REL):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.spec_path = self.root / "specs" / "task.spec.json"
        write_json(self.spec_path, {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "dispatch provenance",
            "authority": "workspace_write",
            "scope": ["exercise dispatch provenance"],
            "worktree": WORKTREE_REL,
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "forbidden": ["merge"],
            "acceptance": ["tests pass"],
        })
        self.record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "dispatch provenance",
            "status": "ready",
            "authority": "workspace_write",
            "scope": ["exercise dispatch provenance"],
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "forbidden": ["merge"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": WORKTREE_REL,
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
            f"# {TASK_ID} — dispatch provenance\n", encoding="utf-8")
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.root / "ledger" / "primary.jsonl").touch()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / TASK_ID / "record.json", data)
        self.record = data

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def dispatch_events(self) -> list[dict]:
        path = self.root / "ledger" / "primary.jsonl"
        events = [json.loads(line) for line in
                  path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [event for event in events if event["type"] == "DISPATCH"]

    def test_dispatch_records_kind_model_parent(self) -> None:
        cp = run_cli(self.root, "dispatch", "--task", TASK_ID,
                     "--executor", "exec-a", "--kind", "external",
                     "--model", "m1", "--parent", "p1")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        dispatch = record["dispatch"]
        self.assertEqual(dispatch["executor"], "exec-a")
        self.assertEqual(dispatch["worktree"], WORKTREE_REL)
        self.assertTrue(dispatch["at"])
        self.assertEqual(dispatch["kind"], "external")
        self.assertEqual(dispatch["model"], "m1")
        self.assertEqual(dispatch["parent"], "p1")

        events = self.dispatch_events()
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["task"], TASK_ID)
        self.assertEqual(payload["executor"], "exec-a")
        self.assertEqual(payload["worktree"], WORKTREE_REL)
        self.assertEqual(payload["at"], dispatch["at"])
        self.assertEqual(payload["kind"], "external")
        self.assertEqual(payload["model"], "m1")
        self.assertEqual(payload["parent"], "p1")

    def test_dispatch_without_new_flags_stays_backward_compatible(self) -> None:
        cp = run_cli(self.root, "dispatch", "--task", TASK_ID,
                     "--executor", "exec-a")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        dispatch = self.load_record()["dispatch"]
        self.assertEqual(dispatch["executor"], "exec-a")
        self.assertEqual(dispatch["worktree"], WORKTREE_REL)
        self.assertTrue(dispatch["at"])
        self.assertEqual(dispatch["kind"], "subagent")
        self.assertIsNone(dispatch["model"])
        self.assertIsNone(dispatch["parent"])

        payload = self.dispatch_events()[0]["payload"]
        self.assertEqual(payload["kind"], "subagent")
        self.assertIsNone(payload["model"])
        self.assertIsNone(payload["parent"])

    def test_empty_provenance_values_are_rejected(self) -> None:
        for flag in ("--kind", "--model", "--parent"):
            cp = run_cli(self.root, "dispatch", "--task", TASK_ID,
                         "--executor", "exec-a", flag, "")
            self.assertEqual(cp.returncode, 2,
                             msg=f"{flag}: stdout={cp.stdout}\nstderr={cp.stderr}")
            payload = json.loads(cp.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("non-empty", "\n".join(payload["errors"]))
        self.assertEqual(self.load_record()["status"], "ready")
        self.assertEqual(self.dispatch_events(), [])


if __name__ == "__main__":
    unittest.main()
