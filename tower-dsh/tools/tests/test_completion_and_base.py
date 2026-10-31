"""Tests for PILOT-042: authorized completions and the dispatch base_sha anchor.

``completion-add`` records an owner-signed completion twice -- one
``COMPLETION_ADDED`` event in ``ledger/primary.jsonl`` and one isomorphic
``record.completions`` entry -- and ``deliver`` folds those completions into
its scope allow-list.  ``dispatch`` additionally anchors the branch to the
``main`` commit it was cut from, and ``deliver`` diffs from that ``base_sha``
instead of the (rewritable) local ``main`` ref.  ``state-verify`` audits both
completion halves for drift.

The fixtures below build a minimal tower inside a real git repository and give
the task a real ``git worktree`` (``git worktree add``), mirroring the layout
used by ``test_deliver_scope.py``: the tower root is ``<kit>/tower-dsh`` and the
task worktree is ``<tower>/pilot/worktrees/<ID>``.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py
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
TASK_ID = "TEST-042"
FIXED_TIME = "2026-10-20T00:00:00+08:00"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
PROOF_REL = "work/proof.txt"
OWNER = "mac"
REASON = "搂6.11 authorized completion: helper needed by the task"
DECISION = "D-042"
COMPLETION_PATH = f"{WORKTREE_REL}/tower-dsh/tools/completion.py"
SPEC_REL = "specs/task.spec.json"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)


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


def completion_entry(path: str, **overrides) -> dict:
    entry = {"task": TASK_ID, "path": path, "by": OWNER, "reason": REASON,
             "decision": DECISION, "at": FIXED_TIME}
    entry.update(overrides)
    return entry


class CompletionAddTestCase(unittest.TestCase):
    """``completion-add`` validation, idempotency and half-write repair."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-completion-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower-dsh"
        for directory in ("primary", "ledger", f"tasks/{TASK_ID}", WORKTREE_REL):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
            "owner": {"name": OWNER},
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.root / "ledger" / "primary.jsonl").touch()
        self.write_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- builders ---------------------------------------------------------
    def task_record(self, **overrides) -> dict:
        record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "authorized completion list",
            "status": "dispatched",
            "authority": "workspace_write",
            "scope": ["record an owner-signed completion"],
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
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
            "next": "",
        }
        record.update(overrides)
        return record

    def write_record(self, **overrides) -> None:
        write_json(self.root / "tasks" / TASK_ID / "record.json",
                   self.task_record(**overrides))

    def save_record(self, record: dict) -> None:
        write_json(self.root / "tasks" / TASK_ID / "record.json", record)

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def ledger_events(self) -> list[dict]:
        path = self.root / "ledger" / "primary.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def completion_events(self) -> list[dict]:
        return [event for event in self.ledger_events()
                if event["type"] == "COMPLETION_ADDED"]

    def snapshot(self) -> dict[str, str]:
        return {
            path.relative_to(self.root).as_posix(): sha256_file(path)
            for path in self.root.rglob("*") if path.is_file()
        }

    def completion_add(self, *, path: str = COMPLETION_PATH, by: str = OWNER,
                       reason: str = REASON, decision: str = DECISION,
                       task: str = TASK_ID) -> subprocess.CompletedProcess:
        return run_cli(self.root, "completion-add", "--task", task,
                       "--path", path, "--by", by, "--reason", reason,
                       "--decision", decision)

    def assert_rejected(self, cp: subprocess.CompletedProcess, needle: str = "") -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        if needle:
            self.assertIn(needle, "\n".join(payload["errors"]))

    def assert_zero_writes(self, before: dict[str, str]) -> None:
        self.assertEqual(self.snapshot(), before)

    # -- 1. a normal completion writes isomorphic halves -------------------
    def test_completion_add_records_entry_and_event(self) -> None:
        cp = self.completion_add()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["ok"])
        self.assertFalse(out["already"])
        self.assertFalse(out["repaired"])
        self.assertEqual(out["path"], COMPLETION_PATH)
        self.assertEqual(out["events"], 1)
        self.assertEqual(out["completions"], 1)

        entries = self.load_record()["completions"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["task"], TASK_ID)
        self.assertEqual(entry["path"], COMPLETION_PATH)
        self.assertEqual(entry["by"], OWNER)
        self.assertEqual(entry["reason"], REASON)
        self.assertEqual(entry["decision"], DECISION)
        self.assertTrue(entry["at"])

        events = self.completion_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["seq"], 1)
        self.assertEqual(events[0]["actor"], "primary")
        # The two halves are isomorphic: the ledger payload *is* the entry.
        self.assertEqual(events[0]["payload"], entry)
        self.assertTrue(events[0]["hash"])

    def test_completion_add_accepts_a_file_that_does_not_exist_yet(self) -> None:
        path = f"{WORKTREE_REL}/tower-dsh/tools/not_written_yet.py"
        self.assertFalse((self.root / path).exists())
        cp = self.completion_add(path=path)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["completions"][0]["path"], path)

    # -- 2. idempotent: both halves present ---------------------------------
    def test_second_completion_add_is_idempotent(self) -> None:
        first = self.completion_add()
        self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
        before = self.snapshot()

        second = self.completion_add(reason="a different reason is still the same path")
        self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
        out = json.loads(second.stdout)
        self.assertTrue(out["already"])
        self.assertFalse(out["repaired"])
        self.assertEqual(out["events"], 1)
        self.assertEqual(out["completions"], 1)
        self.assertEqual(len(self.completion_events()), 1)
        self.assertEqual(len(self.load_record()["completions"]), 1)
        self.assert_zero_writes(before)

    # -- 3. every validation failure is zero-write -------------------------
    def test_non_owner_is_rejected_with_zero_writes(self) -> None:
        before = self.snapshot()
        cp = self.completion_add(by="mallory")
        self.assert_rejected(cp, "only the registered owner")
        self.assertNotIn("completions", self.load_record())
        self.assertEqual(self.completion_events(), [])
        self.assert_zero_writes(before)

    def test_missing_owner_is_rejected_with_zero_writes(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
        })
        before = self.snapshot()
        cp = self.completion_add()
        self.assert_rejected(cp, "no owner.name")
        self.assertNotIn("completions", self.load_record())
        self.assert_zero_writes(before)

    def test_empty_reason_is_rejected_with_zero_writes(self) -> None:
        for value in ("", "   "):
            with self.subTest(reason=value):
                self.write_record()
                before = self.snapshot()
                cp = self.completion_add(reason=value)
                self.assert_rejected(cp, "--reason")
                self.assertNotIn("completions", self.load_record())
                self.assertEqual(self.completion_events(), [])
                self.assert_zero_writes(before)

    def test_empty_decision_is_rejected_with_zero_writes(self) -> None:
        for value in ("", "   "):
            with self.subTest(decision=value):
                self.write_record()
                before = self.snapshot()
                cp = self.completion_add(decision=value)
                self.assert_rejected(cp, "--decision")
                self.assertNotIn("completions", self.load_record())
                self.assertEqual(self.completion_events(), [])
                self.assert_zero_writes(before)

    def test_dotdot_path_is_rejected_with_zero_writes(self) -> None:
        for value in (f"{WORKTREE_REL}/../escape.py", "..",
                      "a/../../b.py"):
            with self.subTest(path=value):
                self.write_record()
                before = self.snapshot()
                cp = self.completion_add(path=value)
                self.assert_rejected(cp, "'..'")
                self.assertNotIn("completions", self.load_record())
                self.assertEqual(self.completion_events(), [])
                self.assert_zero_writes(before)

    def test_absolute_path_is_rejected_with_zero_writes(self) -> None:
        values = (str(self.root / "tools" / "x.py"), "/etc/passwd")
        for value in values:
            with self.subTest(path=value):
                self.write_record()
                before = self.snapshot()
                cp = self.completion_add(path=value)
                self.assert_rejected(cp, "absolute")
                self.assertNotIn("completions", self.load_record())
                self.assertEqual(self.completion_events(), [])
                self.assert_zero_writes(before)

    def test_empty_path_is_rejected_with_zero_writes(self) -> None:
        before = self.snapshot()
        cp = self.completion_add(path="")
        self.assert_rejected(cp, "non-empty")
        self.assert_zero_writes(before)

    def test_invalid_task_status_is_rejected_with_zero_writes(self) -> None:
        for status in ("closed", "accepted", "reviewed"):
            with self.subTest(status=status):
                self.write_record(status=status)
                before = self.snapshot()
                cp = self.completion_add()
                self.assert_rejected(cp, "cannot record a completion")
                self.assertNotIn("completions", self.load_record())
                self.assertEqual(self.completion_events(), [])
                self.assert_zero_writes(before)

    def test_unknown_task_is_rejected_with_zero_writes(self) -> None:
        before = self.snapshot()
        cp = self.completion_add(task="TEST-999")
        self.assert_rejected(cp, "task record missing")
        self.assert_zero_writes(before)

    # -- 4. half-write repair, both directions -----------------------------
    def test_event_without_record_is_repaired(self) -> None:
        self.assertEqual(self.completion_add().returncode, 0)
        event_payload = self.completion_events()[0]["payload"]

        record = self.load_record()
        record.pop("completions")
        self.save_record(record)
        self.assertNotIn("completions", self.load_record())

        cp = self.completion_add()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertFalse(out["already"])
        self.assertTrue(out["repaired"])
        self.assertEqual(out["events"], 1)      # no duplicate event
        self.assertEqual(out["completions"], 1)
        self.assertEqual(len(self.completion_events()), 1)
        entries = self.load_record()["completions"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], event_payload)

    def test_record_without_event_is_repaired(self) -> None:
        self.assertEqual(self.completion_add().returncode, 0)
        entry = self.load_record()["completions"][0]

        ledger = self.root / "ledger" / "primary.jsonl"
        kept = [
            line for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["type"] != "COMPLETION_ADDED"
        ]
        ledger.write_text("\n".join(kept) + ("\n" if kept else ""),
                          encoding="utf-8")
        self.assertEqual(self.completion_events(), [])

        cp = self.completion_add()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertFalse(out["already"])
        self.assertTrue(out["repaired"])
        self.assertEqual(out["events"], 1)
        self.assertEqual(out["completions"], 1)
        events = self.completion_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"], entry)
        self.assertEqual(self.load_record()["completions"], [entry])


class GitWorktreeFixture(unittest.TestCase):
    """A tower inside a real git repository with a real ``git worktree``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-042-git-", ignore_cleanup_errors=True)
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
    def spec_payload(self) -> dict:
        return {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "authorized completion list + base_sha anchor",
            "authority": "workspace_write",
            "scope": ["exercise the PILOT-042 deliver gates"],
            "worktree": WORKTREE_REL,
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "forbidden": ["merge"],
            "acceptance": ["tests pass"],
        }

    def write_source_tree(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / ".gitignore").write_text(
            "tower-dsh/pilot/worktrees/\ntower-dsh/.test-tmp/\n",
            encoding="utf-8")
        (self.tower / "tools").mkdir(parents=True, exist_ok=True)
        (self.tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (self.tower / "pilot").mkdir(parents=True, exist_ok=True)
        (self.tower / "pilot" / f"{TASK_ID}.spec.json").write_text(
            "{}\n", encoding="utf-8")
        (self.tower / "pilot" / "other.json").write_text("{}\n", encoding="utf-8")
        (self.tower / "pilot" / "notes.txt").write_text("notes\n", encoding="utf-8")
        (self.tower / "specs").mkdir(parents=True, exist_ok=True)
        write_json(self.tower / SPEC_REL, self.spec_payload())

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

    def task_record(self, **overrides) -> dict:
        record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "authorized completion list + base_sha anchor",
            "status": "dispatched",
            "authority": "workspace_write",
            "scope": ["exercise the PILOT-042 deliver gates"],
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
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
            "next": "",
        }
        record.update(overrides)
        return record

    def write_tower_state(self) -> None:
        write_json(self.tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
            "owner": {"name": OWNER},
        })
        write_json(self.tower / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.tower / "ledger").mkdir(parents=True, exist_ok=True)
        (self.tower / "ledger" / "primary.jsonl").touch()
        (self.tower / "tasks" / TASK_ID).mkdir(parents=True, exist_ok=True)
        (self.tower / "tasks" / TASK_ID / "TASK.md").write_text(
            f"# {TASK_ID} 鈥?authorized completion list\n", encoding="utf-8")
        self.write_record()

    def write_record(self, **overrides) -> None:
        write_json(self.tower / "tasks" / TASK_ID / "record.json",
                   self.task_record(**overrides))

    def save_record(self, record: dict) -> None:
        write_json(self.tower / "tasks" / TASK_ID / "record.json", record)

    def load_record(self) -> dict:
        return read_json(self.tower / "tasks" / TASK_ID / "record.json")

    def ledger_events(self) -> list[dict]:
        path = self.tower / "ledger" / "primary.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def completion_events(self) -> list[dict]:
        return [event for event in self.ledger_events()
                if event["type"] == "COMPLETION_ADDED"]

    def dispatch_base_sha(self) -> str:
        cp = run_git(self.kit, "rev-parse", "main")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        return cp.stdout.strip()

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

    def completion_add(self, *, path: str = COMPLETION_PATH,
                       by: str = OWNER, reason: str = REASON,
                       decision: str = DECISION) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "completion-add", "--task", TASK_ID,
                       "--path", path, "--by", by, "--reason", reason,
                       "--decision", decision)

    def evidence_dir(self) -> Path:
        return self.tower / "tasks" / TASK_ID / "evidence"

    def assert_failed_with(self, cp: subprocess.CompletedProcess, needle: str) -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(needle, "\n".join(payload["errors"]))

    def assert_delivery_wrote_nothing(self) -> None:
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())
        self.assertNotIn("DELIVER", [event["type"] for event in self.ledger_events()])


class DeliverWithCompletionsTestCase(GitWorktreeFixture):
    """The deliver scope allow-list is ``allowed_paths`` plus completions."""

    def test_completion_path_is_accepted_and_reported(self) -> None:
        cp = self.completion_add(
            path=f"{WORKTREE_REL}/tower-dsh/tools/helper.py")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("completion-authorized helper")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(out["scope_files"], ["tower-dsh/tools/helper.py"])
        self.assertEqual(out["scope_completions"], ["tower-dsh/tools/helper.py"])
        self.assertEqual(out["status"], "delivered")
        self.assertEqual(self.load_record()["status"], "delivered")
        self.assertTrue((self.evidence_dir() / "proof.txt").exists())

    def test_completion_outside_the_worktree_maps_with_the_tower_prefix(self) -> None:
        # ``pilot/notes.txt`` is elsewhere in the tower, so the worktree-relative
        # spelling is ``tower-dsh/pilot/notes.txt`` (same mapping as 041).
        cp = self.completion_add(path="pilot/notes.txt")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        self.write_worktree("tower-dsh/pilot/notes.txt", "notes v2\n")
        self.commit_worktree("completion-authorized tower path")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertEqual(out["scope_completions"],
                         ["tower-dsh/pilot/notes.txt"])
        self.assertEqual(out["scope_files"], ["tower-dsh/pilot/notes.txt"])

    def test_change_neither_allowed_nor_completion_is_rejected(self) -> None:
        self.assertEqual(
            self.completion_add(path=f"{WORKTREE_REL}/tower-dsh/tools/helper.py")
            .returncode, 0)
        self.write_worktree("tower-dsh/pilot/other.json", '{"v": 2}\n')
        self.commit_worktree("out of scope change")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/other.json")
        errors = "\n".join(json.loads(deliver.stdout)["errors"])
        self.assertIn("out of scope change: tower-dsh/pilot/other.json", errors)
        self.assert_delivery_wrote_nothing()

    def test_allowed_and_completion_changes_both_deliver(self) -> None:
        self.assertEqual(
            self.completion_add(path=f"{WORKTREE_REL}/tower-dsh/tools/helper.py")
            .returncode, 0)
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("allowed plus completion")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertEqual(set(out["scope_files"]),
                         {"tower-dsh/tools/x.py", "tower-dsh/tools/helper.py"})
        # Only the completion path is reported as a completion win.
        self.assertEqual(out["scope_completions"], ["tower-dsh/tools/helper.py"])

    def test_hand_written_record_completion_is_rejected(self) -> None:
        """PILOT-043: a record-only completion no longer delivers (exit 2)."""
        record = self.load_record()
        record["completions"] = [completion_entry(
            f"{WORKTREE_REL}/tower-dsh/tools/helper.py")]
        self.save_record(record)
        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("hand-written record completion")

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "completion not backed by COMPLETION_ADDED")
        self.assert_delivery_wrote_nothing()

    def test_legacy_record_without_completions_has_empty_scope_completions(self) -> None:
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        self.assertEqual(json.loads(deliver.stdout)["scope_completions"], [])


class BaseShaTestCase(GitWorktreeFixture):
    """``dispatch`` anchors ``base_sha`` and ``deliver`` diffs from it."""

    def task_record(self, **overrides) -> dict:
        record = super().task_record()
        record.update({
            "status": "ready",
            "spec_path": SPEC_REL,
            "spec_sha256": sha256_file(self.tower / SPEC_REL),
            "spec_gate": "PASS",
            "executor": None,
            "dispatch": None,
        })
        record.update(overrides)
        return record

    def dispatch(self) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "dispatch", "--task", TASK_ID,
                       "--executor", "exec-a")

    def dispatch_events(self) -> list[dict]:
        return [event for event in self.ledger_events()
                if event["type"] == "DISPATCH"]

    def require_dispatch(self) -> dict:
        cp = self.dispatch()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.load_record()

    # -- 1. dispatch records the anchor ------------------------------------
    def test_dispatch_records_base_sha_in_record_and_ledger(self) -> None:
        base = self.dispatch_base_sha()
        record = self.require_dispatch()

        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["dispatch"]["base_sha"], base)

        events = self.dispatch_events()
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["task"], TASK_ID)
        self.assertEqual(payload["base_sha"], base)
        self.assertEqual(payload["base_sha"], record["dispatch"]["base_sha"])

    def test_dispatch_without_main_records_null_base_sha(self) -> None:
        cp = run_git(self.kit, "branch", "-m", "main", "trunk")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

        record = self.require_dispatch()
        self.assertIsNone(record["dispatch"]["base_sha"])
        self.assertIsNone(self.dispatch_events()[0]["payload"]["base_sha"])

    # -- 2. a rewritten main ref cannot hide an out-of-scope change --------
    def test_rewritten_main_ref_cannot_hide_out_of_scope_change(self) -> None:
        record = self.require_dispatch()
        base = record["dispatch"]["base_sha"]
        self.assertTrue(base)

        self.write_worktree("tower-dsh/pilot/other.json", '{"v": 2}\n')
        self.commit_worktree("out of scope change")
        head = run_git(self.worktree, "rev-parse", "HEAD").stdout.strip()

        # Old behaviour: the deliver baseline *was* this local ref, so this
        # rewrite made ``merge-base main HEAD == HEAD`` and the diff empty.
        moved = run_git(self.worktree, "update-ref", "refs/heads/main", "HEAD")
        self.assertEqual(moved.returncode, 0, msg=moved.stderr + moved.stdout)
        self.assertEqual(
            run_git(self.worktree, "rev-parse", "main").stdout.strip(), head)

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/other.json")
        self.assert_delivery_wrote_nothing()

    # -- 3. base_sha must be an ancestor of HEAD ---------------------------
    def test_base_sha_not_ancestor_is_rejected(self) -> None:
        self.require_dispatch()
        run_git(self.kit, "commit", "--allow-empty", "-m", "divergent main")
        divergent = run_git(self.kit, "rev-parse", "main").stdout.strip()

        record = self.load_record()
        record["dispatch"]["base_sha"] = divergent
        self.save_record(record)
        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "not an ancestor")
        self.assertIn(divergent, "\n".join(json.loads(deliver.stdout)["errors"]))
        self.assert_delivery_wrote_nothing()

    # -- 4. legacy records fall back to merge-base main HEAD ---------------
    def test_legacy_record_without_base_sha_uses_merge_base(self) -> None:
        self.write_record(
            status="dispatched",
            dispatch={"executor": "exec-a", "worktree": WORKTREE_REL,
                      "at": FIXED_TIME})
        self.assertNotIn("base_sha", self.load_record()["dispatch"])

        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(out["scope_completions"], [])
        self.assertEqual(self.load_record()["status"], "delivered")

    def test_legacy_record_out_of_scope_change_is_still_rejected(self) -> None:
        self.write_record(
            status="dispatched",
            dispatch={"executor": "exec-a", "worktree": WORKTREE_REL,
                      "at": FIXED_TIME})
        self.write_worktree("tower-dsh/pilot/other.json", '{"v": 2}\n')
        self.commit_worktree("out of scope change")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/other.json")
        self.assert_delivery_wrote_nothing()

    # -- 5. the anchored diff still disables rename detection --------------
    def test_base_sha_diff_keeps_renames_disabled(self) -> None:
        self.require_dispatch()
        self.assertEqual(
            self.completion_add(path=f"{WORKTREE_REL}/tower-dsh/tools/helper.py")
            .returncode, 0)
        moved = run_git(self.worktree, "mv", "tower-dsh/pilot/other.json",
                        "tower-dsh/tools/helper.py")
        self.assertEqual(moved.returncode, 0, msg=moved.stderr + moved.stdout)
        self.commit_worktree("rename out-of-scope file into a completion path")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "tower-dsh/pilot/other.json")
        errors = "\n".join(json.loads(deliver.stdout)["errors"])
        self.assertNotIn("tower-dsh/tools/helper.py (not in allowed_paths)", errors)
        self.assert_delivery_wrote_nothing()

    # -- 6. the anchored path still checks worktree identity ---------------
    def test_base_sha_path_keeps_worktree_identity_gate(self) -> None:
        self.require_dispatch()
        foreign = Path(self._tmp.name) / "foreign"
        foreign.mkdir(parents=True, exist_ok=True)
        self.assertEqual(run_git(foreign, "init").returncode, 0)
        self.assertEqual(
            run_git(foreign, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (foreign / "a.txt").write_text("a\n", encoding="utf-8")
        self.assertEqual(run_git(foreign, "add", "-A").returncode, 0)
        commit = run_git(foreign, "commit", "-m", "foreign base")
        self.assertEqual(commit.returncode, 0, msg=commit.stderr + commit.stdout)

        gitfile = self.worktree / ".git"
        gitfile.unlink()
        gitfile.write_text(
            f"gitdir: {(foreign / '.git').as_posix()}\n", encoding="utf-8")

        deliver = self.deliver()
        self.assert_failed_with(deliver, "not a worktree of the tower repository")
        self.assert_delivery_wrote_nothing()


class StateVerifyCompletionDriftTestCase(unittest.TestCase):
    """``state-verify`` audits both halves of every recorded completion."""

    TASK = "T-900"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-042-verify-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower-dsh"
        for directory in ("ledger", "primary", "tasks",
                          "supervision", "supervision/envelopes"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
            "owner": {"name": OWNER},
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                    "tasks": [{"id": self.TASK, "title": self.TASK,
                               "status": "delivered"}]})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
            towerctl.append_ledger(self.root, event_type, "primary",
                                   {"task": self.TASK})
        self.put_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- builders ---------------------------------------------------------
    def put_record(self, completions=None) -> None:
        record = {"schema": "tower/task@1", "id": self.TASK,
                  "title": self.TASK, "status": "delivered"}
        if completions is not None:
            record["completions"] = completions
        write_json(self.root / "tasks" / self.TASK / "record.json", record)

    def read_record(self) -> dict:
        return read_json(self.root / "tasks" / self.TASK / "record.json")

    def entry(self, path, **overrides) -> dict:
        overrides.setdefault("task", self.TASK)
        return completion_entry(path, **overrides)

    def completion_add(self, path: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, "completion-add", "--task", self.TASK,
                       "--path", path, "--by", OWNER, "--reason", REASON,
                       "--decision", DECISION)

    def state_verify(self) -> tuple[dict, int]:
        proc = run_cli(self.root, "state-verify")
        return json.loads(proc.stdout), proc.returncode

    def drift_kinds(self, out: dict) -> list[str]:
        return sorted(item["kind"] for item in out["drift"])

    # -- 1. a recorded, backed completion is clean -------------------------
    def test_valid_completion_pair_has_no_drift(self) -> None:
        path = f"{WORKTREE_REL}/tower-dsh/tools/x.py"
        cp = self.completion_add(path)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertNotIn("completion_unbacked", self.drift_kinds(out))
        self.assertNotIn("completion_missing", self.drift_kinds(out))
        self.assertNotIn("completion_invalid", self.drift_kinds(out))

    # -- 2. record without event -> completion_unbacked --------------------
    def test_record_completion_without_event_is_unbacked(self) -> None:
        path = f"{WORKTREE_REL}/tower-dsh/tools/x.py"
        self.put_record([self.entry(path)])

        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_unbacked"])
        row = out["drift"][0]
        self.assertEqual(row["target"], self.TASK)
        self.assertEqual(row["expected"], path)

    # -- 3. event without record -> completion_missing ---------------------
    def test_event_without_record_completion_is_missing(self) -> None:
        path = f"{WORKTREE_REL}/tower-dsh/tools/x.py"
        towerctl.append_ledger(self.root, "COMPLETION_ADDED", "primary",
                               self.entry(path))
        self.put_record()

        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_missing"])
        row = out["drift"][0]
        self.assertEqual(row["target"], self.TASK)
        self.assertEqual(row["path"], path)

    # -- 4. malformed fields -> completion_invalid -------------------------
    def test_invalid_completion_fields_are_flagged(self) -> None:
        bad_entries = {
            "empty by": self.entry("pilot/x.py", by=""),
            "empty reason": self.entry("pilot/x.py", reason="  "),
            "empty decision": self.entry("pilot/x.py", decision=""),
            "non-string path": self.entry(None),
            "escaping path": self.entry("../outside.py"),
            "absolute path": self.entry("/etc/passwd"),
        }
        for label, entry in bad_entries.items():
            with self.subTest(case=label):
                self.put_record([entry])
                out, code = self.state_verify()
                self.assertEqual(code, 2, out)
                self.assertEqual(self.drift_kinds(out), ["completion_invalid"])
                self.assertEqual(out["drift"][0]["target"], self.TASK)

        # A non-object entry is invalid too, not a traceback.
        self.put_record(["not-an-entry"])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_invalid"])

    # -- 5. a task without completions gains no row and no skip ------------
    def test_task_without_completions_adds_no_drift_or_skip(self) -> None:
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual([item["kind"] for item in out["skipped"]],
                         ["authority_state"])
        self.assertEqual(out["skipped_count"], 1)
        self.assertFalse([kind for kind in self.drift_kinds(out)
                          if kind.startswith("completion")])


if __name__ == "__main__":
    unittest.main()
