"""PILOT-077: post-merge runs on frozen state; recovery re-folds the ledger.

076 was merged but could not be verified: its suites read live tower state while
an earlier recovery had written ``MERGED`` files whose ledger still folded to
``CORRECTION_REQUIRED`` (a real ``MERGE`` followed by ``POST_MERGE_FAILED`` rows
and no recovered tail).  ``post-merge`` now snapshots the state bytes
(envelopes, merge queue, supervision ledger, task board, the verified task's
record) before each child starts and restores them in a ``finally`` block;
children carry ``TOWER_POST_MERGE=1`` (the root gate stops recursing into the
full tower suite) and ``TOWER_POST_MERGE_ROOT`` (the entry layer refuses writes
to the live root).

``envelope-recover`` closes the second gap: when the envelope already records
its ``MERGE`` but the replay still folds ``CORRECTION_REQUIRED``, it appends one
recovered ``MERGE_START``/``MERGE`` tail with the same commit, so ``state-verify``
agrees with the files; an already-``MERGED`` replay (074) still gets no second
``MERGE``.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_post_merge_isolation -v
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
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import tower_cli  # noqa: E402  (needs TOOLS_DIR on sys.path)
import tower_envelope, tower_ledger_replay  # noqa: E402

TCLI = TOOLS_DIR / "towerctl.py"
TOWER_ROOT, WORKTREE = TOOLS_DIR.parent, TOOLS_DIR.parent.parent
POST_MERGE_ENV, POST_MERGE_ROOT_ENV = (tower_cli.POST_MERGE_ENV, tower_cli.POST_MERGE_ROOT_ENV)
FIXED_TIME = "2026-11-07T00:00:00+08:00"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test", "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

CHILD_MUTATE = """\
import json, os, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tower-dsh"
STATE = ROOT / "supervision"
ENVELOPE = STATE / "envelopes" / "__ENVELOPE__"
QUEUE = STATE / "MERGE_QUEUE.json"
LEDGER = ROOT / "ledger" / "supervision.jsonl"


class ChildMutateTest(unittest.TestCase):
    def test_child_sees_merged_then_writes_state(self):
        status = json.loads(ENVELOPE.read_text(encoding="utf-8"))["status"]
        (STATE / "reviews" / "child-observed.json").write_text(
            json.dumps({"status": status,
                        "post_merge": os.environ.get("TOWER_POST_MERGE"),
                        "root": os.environ.get("TOWER_POST_MERGE_ROOT")}),
            encoding="utf-8")
        self.assertEqual(status, "MERGED")
        self.assertEqual(os.environ.get("TOWER_POST_MERGE"), "1")
        envelope = json.loads(ENVELOPE.read_text(encoding="utf-8"))
        envelope["status"] = "MUTATED"
        ENVELOPE.write_text(json.dumps(envelope), encoding="utf-8")
        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue["entries"][0]["status"] = "MUTATED"
        QUEUE.write_text(json.dumps(queue), encoding="utf-8")
        LEDGER.write_text(LEDGER.read_text(encoding="utf-8") + '{"garbage": 1}\\n')
        (ROOT / "primary" / "TASK_BOARD.json").write_text('{"mutated": true}\\n')
        (ROOT / "tasks" / "__TASK__" / "record.json").write_text('{"mutated": 1}')
        (STATE / "envelopes" / "ENV-TEST-ISO-999.json").write_text("{}")
        self.assertTrue(True)
"""

CHILD_MUTATE_FAIL = CHILD_MUTATE.replace(
    "        self.assertTrue(True)",
    "        self.fail('post-merge child fails after mutating state')",
).replace("class ChildMutateTest", "class ChildMutateFailTest")

TOWER_CHILD = """\
import os, unittest


class TowerSuiteChildTest(unittest.TestCase):
    def test_tower_suite_sees_the_post_merge_env(self):
        self.assertEqual(os.environ.get("TOWER_POST_MERGE"), "1")
"""

# The fake tower runner the root-gate case copies under a throw-away
# ``repo/tower-dsh/tools/``: it records the recursion and fakes a summary.
FAKE_TOWER_RUNNER = """\
import pathlib, sys

root = pathlib.Path(__file__).resolve().parents[1]
(root / "recursed.txt").write_text("ran", encoding="utf-8")
sys.stderr.write("Ran 9 tests in 0.1s\\n")
raise SystemExit(0)
"""


class _TowerFixture:
    """A throw-away ``kit`` repository with the tower root nested in it."""

    ENVELOPE_ID = "ENV-TEST-ISO-001"
    TASK_ID = "TEST-ISO-001"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="tower-post-merge-iso-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for name in ("supervision/envelopes", "supervision/reviews", "primary",
                     f"tasks/{self.TASK_ID}", "ledger", "tools/tests"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.kit / "tests").mkdir(parents=True, exist_ok=True)
        self.write_static_tower_files()
        self.init_repo()
        self.assertFalse(self.git("status", "--porcelain").stdout.strip())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture plumbing -------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=dict(os.environ, **GIT_IDENTITY))

    def commit_all(self, message: str) -> str:
        for args in (("add", "--all"),
                     ("-c", "commit.gpgsign=false", "commit", "-m", message)):
            cp = self.git(*args)
            self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def write_static_tower_files(self) -> None:
        self.write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "TEST",
            "supervisor": {"id": "sup-test"}})
        self.write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{"id": self.TASK_ID, "status": "accepted"}]})
        self.write_json(self.root / "tasks" / self.TASK_ID / "record.json", {
            "schema": "tower/task@1", "id": self.TASK_ID, "title": "isolation",
            "status": "accepted", "executor": "exec-test",
            "review": {"reviewer": "rev-test", "verdict": "PASS"}})
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")

    def write_repo_suite(self, behavior: str) -> None:
        sources = {"mutate": CHILD_MUTATE, "mutate-fail": CHILD_MUTATE_FAIL}
        path = self.kit / "tests" / "test_smoke.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            sources[behavior].replace("__ENVELOPE__", f"{self.ENVELOPE_ID}.json")
            .replace("__TASK__", self.TASK_ID), encoding="utf-8")

    def write_tower_suite(self) -> None:
        path = self.root / "tools" / "tests" / "test_tower_smoke.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TOWER_CHILD, encoding="utf-8")

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{self.ENVELOPE_ID}.json"

    def write_envelope(self, status: str, implementation: str,
                       merge_commit: str) -> dict:
        envelope = {
            "schema": "tower/merge-envelope@1", "envelope_id": self.ENVELOPE_ID,
            "task": self.TASK_ID, "repository": "..",
            "branch": f"pilot/{self.TASK_ID}", "base": "main",
            "envelope_path": f"merge-envelopes/{self.ENVELOPE_ID}.json",
            "implementation_head_sha": implementation,
            "envelope_head_sha": merge_commit, "status": status,
            "merge_commit": merge_commit, "tests_baseline": 1,
            "tower_tests_baseline": 1}
        self.write_json(self.envelope_path(), envelope)
        return envelope

    def write_queue(self, status: str, merge_commit: str) -> None:
        self.write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1", "updated_at": FIXED_TIME,
            "entries": [{"envelope_id": self.ENVELOPE_ID, "task": self.TASK_ID,
                         "branch": f"pilot/{self.TASK_ID}", "base": "main",
                         "status": status, "added_at": FIXED_TIME,
                         "merge_commit": merge_commit}]})

    def init_repo(self) -> None:
        self.git("init")
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.write_repo_suite("mutate")
        self.write_tower_suite()
        self.write_queue("MERGED", "0" * 40)
        self.write_json(self.kit / "merge-envelopes" / f"{self.ENVELOPE_ID}.json",
                        {"schema": "tower/merge-envelope@1",
                         "envelope_id": self.ENVELOPE_ID, "task": self.TASK_ID})
        self.commit_all("base state")
        self.base_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.write_envelope("MERGED", self.base_sha, self.base_sha)
        self.commit_all("merged envelope")

    # -- assertions -------------------------------------------------------
    def prepare(self, behavior: str) -> None:
        self.write_repo_suite(behavior)
        if self.git("status", "--porcelain").stdout.strip():
            self.commit_all(f"child suite: {behavior}")
        self.assertFalse(self.git("status", "--porcelain").stdout.strip())

    def state_paths(self) -> dict[str, Path]:
        return {"envelope": self.envelope_path(),
                "queue": self.root / "supervision" / "MERGE_QUEUE.json",
                "ledger": self.root / "ledger" / "supervision.jsonl",
                "board": self.root / "primary" / "TASK_BOARD.json",
                "record": self.root / "tasks" / self.TASK_ID / "record.json"}

    def state_bytes(self) -> dict[str, bytes]:
        return {name: path.read_bytes() for name, path in self.state_paths().items()}

    def envelope_status(self) -> str:
        return json.loads(self.envelope_path().read_text(encoding="utf-8"))["status"]

    def queue_status(self) -> str:
        queue = json.loads(self.state_paths()["queue"].read_text(encoding="utf-8"))
        return queue["entries"][0]["status"]

    def ledger_events(self) -> list[dict]:
        return [json.loads(line) for line in
                self.state_paths()["ledger"].read_text(
                    encoding="utf-8").splitlines() if line.strip()]

    def check(self, cp: subprocess.CompletedProcess, name: str) -> dict:
        return next(c for c in json.loads(cp.stdout)["checks"]
                    if c["name"] == name)

    def run_post_merge(self, result: str = "PASS") -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop(POST_MERGE_ENV, None)
        env.pop(POST_MERGE_ROOT_ENV, None)
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "post-merge", "--envelope", self.ENVELOPE_ID, "--result", result],
            capture_output=True, text=True, encoding="utf-8", env=env)

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8",
            env=dict(os.environ, **GIT_IDENTITY))


class SnapshotIsolationCase(_TowerFixture, unittest.TestCase):
    """Snapshot/restore bytes and the success/failure write ordering."""

    def test_snapshot_restore_round_trips_every_byte(self) -> None:
        before = self.state_bytes()
        snapshot = tower_cli.snapshot_state(self.root, {"task": self.TASK_ID})
        self.assertEqual(sorted(snapshot), sorted([
            f"supervision/envelopes/{self.ENVELOPE_ID}.json",
            "supervision/MERGE_QUEUE.json", "ledger/supervision.jsonl",
            "primary/TASK_BOARD.json", f"tasks/{self.TASK_ID}/record.json"]))
        paths = self.state_paths()
        paths["envelope"].write_text('{"status": "MUTATED"}\n', encoding="utf-8")
        paths["record"].unlink()
        paths["board"].write_text("{}\n", encoding="utf-8")
        extra = self.root / "supervision" / "envelopes" / "ENV-TEST-ISO-999.json"
        extra.write_text("{}", encoding="utf-8")
        restored = tower_cli.restore_state(self.root, snapshot)
        self.assertIn(f"supervision/envelopes/{self.ENVELOPE_ID}.json", restored)
        self.assertIn(f"tasks/{self.TASK_ID}/record.json", restored)
        self.assertIn("supervision/envelopes/ENV-TEST-ISO-999.json", restored)
        self.assertFalse(extra.exists())
        self.assertEqual(self.state_bytes(), before)

    def test_child_sees_merged_and_state_is_restored_before_verified(self) -> None:
        self.prepare("mutate")
        before = self.state_bytes()
        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["status"], "POST_MERGE_VERIFIED")
        self.assertTrue(self.check(cp, "working tree clean")["ok"])
        observed = json.loads((self.root / "supervision" / "reviews"
                               / "child-observed.json").read_text(encoding="utf-8"))
        self.assertEqual((observed["status"], observed["post_merge"]),
                         ("MERGED", "1"))
        self.assertEqual(Path(observed["root"]).resolve(), self.root.resolve())
        self.assertEqual((self.envelope_status(), self.queue_status()),
                         ("POST_MERGE_VERIFIED", "POST_MERGE_VERIFIED"))
        paths = self.state_paths()
        self.assertEqual((paths["board"].read_bytes(),
                          paths["record"].read_bytes()),
                         (before["board"], before["record"]))
        self.assertNotIn(b"MUTATED", paths["envelope"].read_bytes())
        self.assertNotIn(b"MUTATED", paths["queue"].read_bytes())
        self.assertTrue(paths["ledger"].read_bytes().startswith(before["ledger"]))
        self.assertEqual(self.ledger_events()[-1]["type"], "POST_MERGE_VERIFIED")
        self.assertFalse([e for e in self.ledger_events()
                          if "garbage" in json.dumps(e)])

    def test_entry_layer_refuses_live_writes_but_allows_reads(self) -> None:
        tagged = dict(os.environ, **{POST_MERGE_ENV: "1",
                                     POST_MERGE_ROOT_ENV: str(self.root)})
        blocked = subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "phase", "--phase", "B"], capture_output=True, text=True,
            encoding="utf-8", env=tagged)
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("post-merge isolation", blocked.stdout)
        read = subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "hash", str(self.kit / "README.md")], capture_output=True,
            text=True, encoding="utf-8", env=tagged)
        self.assertEqual(read.returncode, 0, read.stdout + read.stderr)
        other = subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "hash", str(self.kit / "README.md")], capture_output=True,
            text=True, encoding="utf-8",
            env=dict(os.environ, **{POST_MERGE_ENV: "1",
                                    POST_MERGE_ROOT_ENV: str(self.kit)}))
        self.assertEqual(other.returncode, 0, other.stdout + other.stderr)

    def test_failure_run_restores_state_before_writing_correction(self) -> None:
        self.prepare("mutate-fail")
        before = self.state_bytes()
        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["status"], "CORRECTION_REQUIRED")
        self.assertEqual((self.envelope_status(), self.queue_status()),
                         ("CORRECTION_REQUIRED", "CORRECTION_REQUIRED"))
        paths = self.state_paths()
        self.assertEqual(paths["board"].read_bytes(), before["board"])
        self.assertEqual(paths["record"].read_bytes(), before["record"])
        self.assertNotIn(b"MUTATED", paths["envelope"].read_bytes())
        self.assertNotIn(b"MUTATED", paths["queue"].read_bytes())
        events = self.ledger_events()
        self.assertEqual(events[-1]["type"], "POST_MERGE_FAILED")
        self.assertFalse([e for e in events if e["type"] == "POST_MERGE_VERIFIED"])
        self.assertFalse([e for e in events if "garbage" in json.dumps(e)])


class RootGateRecursionCase(unittest.TestCase):
    """TOWER_POST_MERGE=1 stops the root gate from running the tower suite."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="tower-root-gate-", ignore_cleanup_errors=True)
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tower-dsh" / "tools").mkdir(parents=True)
        shutil.copyfile(WORKTREE / "tests" / "test_tower_gates.py",
                        self.repo / "tests" / "test_tower_gates.py")
        (self.repo / "tower-dsh" / "tools" / "run_tests.py").write_text(
            FAKE_TOWER_RUNNER, encoding="utf-8")
        self.marker = self.repo / "tower-dsh" / "recursed.txt"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_root_gate(self, *, post_merge: bool) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop(POST_MERGE_ENV, None)
        env.pop(POST_MERGE_ROOT_ENV, None)
        if post_merge:
            env[POST_MERGE_ENV] = "1"
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests",
             "-p", "test_tower_gates.py", "-v"],
            cwd=str(self.repo), capture_output=True, text=True,
            encoding="utf-8", env=env)

    def test_recursion_only_happens_outside_the_post_merge_env(self) -> None:
        blocked = self.run_root_gate(post_merge=True)
        self.assertEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
        self.assertIn("Ran 2 tests", blocked.stderr)
        self.assertNotIn("TOWER_TEST_TMP=", blocked.stdout + blocked.stderr)
        self.assertFalse(self.marker.exists())
        ordinary = self.run_root_gate(post_merge=False)
        self.assertEqual(ordinary.returncode, 0, ordinary.stdout + ordinary.stderr)
        self.assertIn("Ran 2 tests", ordinary.stderr)
        self.assertTrue(self.marker.exists())


class _RecoverFixture(_TowerFixture):
    """ENV-PILOT-076 shape: a landed MERGE with a failing post-merge tail."""

    ENVELOPE_ID = "ENV-PILOT-076"
    TASK_ID = "PILOT-076"

    def write_static_tower_files(self) -> None:
        self.write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "TEST", "owner": {"name": "mac"},
            "primary": {"id": "ctl-test"}})
        self.write_json(self.root / "primary" / "TASK_BOARD.json",
                        {"schema": "tower/task-board@1", "tasks": []})
        self.write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "TEST",
            "supervisor": {"id": "sup-test"}})
        for name in ("supervision", "primary"):
            (self.root / "ledger" / f"{name}.jsonl").write_text(
                "", encoding="utf-8")

    def init_repo(self) -> None:
        self.origin = Path(self._tmp.name) / "origin.git"
        self.git("init")
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.write_repo_suite("mutate")
        self.write_tower_suite()
        self.write_json(self.root / "merge-envelopes" / f"{self.ENVELOPE_ID}.json",
                        {"schema": "tower/merge-envelope@1",
                         "envelope_id": self.ENVELOPE_ID, "task": self.TASK_ID})
        self.commit_all("base")
        self.git("checkout", "-b", f"pilot/{self.TASK_ID}")
        (self.kit / "implementation.txt").write_text("076\n", encoding="utf-8")
        self.implementation = self.commit_all("implementation")
        self.git("checkout", "main")
        merge = self.git("merge", "--no-ff", "-m", "merge 076",
                         f"pilot/{self.TASK_ID}")
        self.assertEqual(merge.returncode, 0, msg=merge.stdout + merge.stderr)
        self.merge_commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.merge_commit)
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        self.git("remote", "add", "origin", str(self.origin).replace("\\", "/"))
        self.assertEqual(self.git("push", "origin", "main").returncode, 0)
        self.write_recovery_state()
        self.commit_all("076 state")
        cp = self.cli("authority-set", "--supervisor", "sup-test",
                      "--decision", "D-077", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.commit_all("authority")

    def write_recovery_state(self) -> None:
        """Files at ``CORRECTION_REQUIRED``; ledger MERGE then a failure row."""
        self.write_envelope("CORRECTION_REQUIRED", self.implementation,
                            self.merge_commit)
        self.write_queue("CORRECTION_REQUIRED", self.merge_commit)
        self.write_ledger(("ENVELOPE_NEW", {"task": self.TASK_ID}),
                          ("QUEUE_ADD", {"task": self.TASK_ID}),
                          ("MERGE_START", {}),
                          ("MERGE", {"merge_commit": self.merge_commit}),
                          ("POST_MERGE_FAILED", {"result": "PASS"}))

    def write_ledger(self, *rows) -> None:
        lines = [json.dumps({"seq": index, "at": FIXED_TIME, "type": kind,
                             "actor": "supervision",
                             "payload": {"envelope": self.ENVELOPE_ID, **extra}})
                 for index, (kind, extra) in enumerate(rows, 1)]
        self.state_paths()["ledger"].write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    def recover(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("envelope-recover", "--envelope", self.ENVELOPE_ID,
                        "--merge-commit", self.merge_commit,
                        "--reason", "076 recovered tail", *extra)

    def events(self, kind: str | None = None) -> list[dict]:
        return [e for e in self.ledger_events()
                if kind is None or e["type"] == kind]

    def replay(self) -> str | None:
        return tower_ledger_replay.replay_envelope_statuses(self.root).get(
            self.ENVELOPE_ID)

    def verify(self) -> dict:
        cp = self.cli("state-verify")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def state_snapshot(self) -> tuple[bytes, bytes, bytes]:
        paths = [self.state_paths()[name] for name in ("envelope", "queue",
                                                       "ledger")]
        return tuple(path.read_bytes() for path in paths)

    def reset_without_merge(self) -> None:
        """Turn the fixture into an ordinary correction (no MERGE event)."""
        self.write_ledger(("ENVELOPE_NEW", {"task": self.TASK_ID}),
                          ("QUEUE_ADD", {"task": self.TASK_ID}),
                          ("MERGE_START", {}),
                          ("MERGE_BLOCKED", {"phase": "checks"}))
        envelope = json.loads(self.envelope_path().read_text(encoding="utf-8"))
        envelope.pop("merge_commit", None)
        envelope["status"] = "CORRECTION_REQUIRED"
        self.write_json(self.envelope_path(), envelope)
        queue = json.loads(self.state_paths()["queue"].read_text(encoding="utf-8"))
        queue["entries"][0].pop("merge_commit", None)
        queue["entries"][0]["status"] = "CORRECTION_REQUIRED"
        self.write_json(self.state_paths()["queue"], queue)


class RecoverReopenedCase(_RecoverFixture, unittest.TestCase):
    """Recovery must make the ledger replay agree with the files."""

    def test_recorded_merge_with_a_failure_tail_reopens_to_merged(self) -> None:
        self.assertEqual(self.replay(), "CORRECTION_REQUIRED")
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIs(json.loads(cp.stdout)["reopened"], True)
        self.assertEqual(self.replay(), "MERGED")
        self.assertEqual((self.envelope_status(), self.queue_status()),
                         ("MERGED", "MERGED"))
        self.assertEqual(json.loads(self.envelope_path().read_text(
            encoding="utf-8"))["merge_commit"], self.merge_commit)
        merges = self.events("MERGE")
        self.assertEqual(len(merges), 2)
        self.assertEqual({e["payload"]["merge_commit"] for e in merges},
                         {self.merge_commit})
        tail = self.events()[-2:]
        self.assertEqual([e["type"] for e in tail], ["MERGE_START", "MERGE"])
        self.assertEqual([e["payload"]["recovered"] for e in tail], [True, True])
        self.assertEqual(self.events("POST_MERGE_VERIFIED"), [])
        self.assertEqual(self.verify()["drift"], [])

    def test_second_recovery_does_not_append_again(self) -> None:
        self.assertEqual(self.recover().returncode, 0)
        before = self.state_snapshot()
        cp = self.recover()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("already records a MERGE", cp.stdout)
        self.assertEqual(self.state_snapshot(), before)

    def test_merge_events_with_different_commits_are_refused(self) -> None:
        tower_envelope.append_supervision_ledger(
            self.root, "MERGE", "supervision",
            {"envelope": self.ENVELOPE_ID, "merge_commit": "f" * 40})
        before = self.state_snapshot()
        cp = self.recover()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("merge_commit values are empty or disagree", cp.stdout)
        self.assertEqual(self.state_snapshot(), before)


    def test_ordinary_correction_without_merge_appends_the_original_tail(self):
        self.reset_without_merge()
        self.assertEqual(self.events("MERGE"), [])
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIs(json.loads(cp.stdout)["reopened"], False)
        self.assertEqual(self.replay(), "MERGED")
        merges = self.events("MERGE")
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["payload"]["merge_commit"], self.merge_commit)
        self.assertIs(merges[0]["payload"]["recovered"], True)
        self.assertEqual(self.events("MERGE_START")[-1]["type"], "MERGE_START")
        self.assertEqual(self.events()[-1]["type"], "MERGE")
        self.assertEqual(self.events("POST_MERGE_VERIFIED"), [])
        self.assertEqual(self.verify()["drift"], [])


class Recovered076Case(_RecoverFixture, unittest.TestCase):
    """ENV-PILOT-076 after recovery: merged, failed, then re-folded MERGED."""

    def write_recovery_state(self) -> None:
        envelope = self.write_envelope("MERGED", self.implementation,
                                       self.merge_commit)
        envelope["base_side"] = True
        self.write_json(self.envelope_path(), envelope)
        self.write_queue("MERGED", self.merge_commit)
        self.write_ledger(("ENVELOPE_NEW", {"task": self.TASK_ID}),
                          ("QUEUE_ADD", {"task": self.TASK_ID}),
                          ("MERGE_START", {}),
                          ("MERGE", {"merge_commit": self.merge_commit}),
                          ("POST_MERGE_FAILED", {}),
                          ("MERGE_START", {"recovered": True}),
                          ("MERGE", {"merge_commit": self.merge_commit,
                                     "recovered": True}))

    def test_076_recovered_merged_state_verifies_on_stable_snapshot(self) -> None:
        cp = self.run_post_merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual((self.envelope_status(), self.queue_status()),
                         ("POST_MERGE_VERIFIED", "POST_MERGE_VERIFIED"))
        observed = json.loads((self.root / "supervision" / "reviews"
                               / "child-observed.json").read_text(encoding="utf-8"))
        self.assertEqual(observed["status"], "MERGED")
        self.assertEqual(self.ledger_events()[-1]["type"], "POST_MERGE_VERIFIED")


if __name__ == "__main__":
    unittest.main()
