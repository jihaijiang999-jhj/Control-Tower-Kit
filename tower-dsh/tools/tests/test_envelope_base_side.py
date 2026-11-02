"""PILOT-063: base-side envelopes — the PR head is always the implementation.

061 relaxed ``pr_remote_merge`` so a PR head could be the implementation plus
one envelope-only commit, but ``envelope_checks`` still demanded that the
implementation branch head equal the envelope head.  Any branch commit (even an
empty one) therefore broke the head equality, and the PR path stayed unusable.

A *base-side* envelope moves the envelope commit to the base branch:

* ``envelope-new --base-side`` records the implementation branch head as
  ``implementation_head_sha`` and the base head as ``head``/``envelope_head_sha``,
  writes ``ENVELOPE_NEW``/``QUEUE_ADD`` and never requires an envelope commit on
  the implementation branch;
* ``envelope_checks`` requires ``branch head == implementation_head_sha`` and the
  envelope file in base, and no longer compares the branch head to the envelope
  head;
* ``merge --mode pr`` pins ``--match-head-commit`` at the implementation head.

Branch-side envelopes written before 063 keep the old checks unchanged.  ``gh``
is an offline stub injected through ``TOWERCTL_GH``; the "remote" is a
throw-away bare repository, so nothing here touches a network.

PILOT-065 keeps the same shape checks but binds them to the envelope's own
``envelope_head_sha`` instead of the base tip: after the envelope is created,
base keeps moving with ledger/queue/task state commits, and those must not be
re-read as "the envelope commit".

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_envelope_base_side -v
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(TOOLS_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import tower_merge  # noqa: E402  (TOOLS_DIR must be on sys.path first)
from tower_ledger import append_ledger, append_supervision_ledger  # noqa: E402
import test_merge_head as head_kit  # noqa: E402  (offline gh environment)
import test_review_gate as kit  # noqa: E402  (offline gh stub + CLI/git helpers)

TASK = "PILOT-063"
ENVELOPE = "ENV-PILOT-063"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
WORKTREE = f"pilot/worktrees/{TASK}"
BRANCH = "pilot/PILOT-063"
BASE = "main"
REVIEWER = "rev-063"
SUPERVISOR = "sup-063"
FIXED_TIME = "2026-11-01T00:00:00+08:00"
PR_URL = kit.PR_URL

run_cli = kit.run_cli
run_git = kit.run_git
write_json = kit.write_json
read_json = kit.read_json
ok = kit.ok


class BaseSideKit(unittest.TestCase):
    """One throw-away repository and tower root shared by the 063 cases.

    ``base_side`` decides where the envelope commit lives: on the base branch
    (main) or, for the legacy comparison, on the implementation branch.
    ``create_envelope`` is off for the shape-refusal cases, which build their
    own base history before invoking ``envelope-new``.
    """

    base_side = True
    create_envelope = True

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-base-side-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.gh = self.tmp / "gh_stub.py"
        self.gh_log = self.tmp / "gh-argv.jsonl"
        self.gh.write_text(kit.GH_STUB, encoding="utf-8")
        self.envelope_head = ""
        self.init_repo()
        self.init_tower()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- repository fixture ----------------------------------------------
    def commit(self, message: str, *paths: str) -> str:
        ok(run_git(self.kit, "add", "--", *paths))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m", message))
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def envelope_repo_path(self) -> str:
        """Repo-relative envelope path: base-side lives under the tower root.

        ``git diff`` names files from the repository root, so a base-side
        envelope materialises as ``tower-dsh/merge-envelopes/<ENV>.json``
        (PILOT-064).  A branch-side envelope keeps the pre-063 root path.
        """
        return f"tower-dsh/{ENVELOPE_PATH}" if self.base_side else ENVELOPE_PATH

    def write_envelope_file(self) -> None:
        write_json(self.kit / self.envelope_repo_path(), {"envelope_id": ENVELOPE})

    def envelope_commit(self, *extra: str) -> str:
        """Commit the envelope file (plus optional extras) where we stand."""
        self.write_envelope_file()
        for path in extra:
            (self.kit / path).write_text("extra\n", encoding="utf-8")
        return self.commit("envelope", self.envelope_repo_path(), *extra)

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        ok(run_git(self.kit, "init"))
        ok(run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main"))
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.base_sha = self.commit("base", "README.md")
        ok(run_git(self.kit, "checkout", "-b", BRANCH))
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit("implementation", "feature.txt")
        ok(run_git(self.kit, "checkout", BASE))
        if not self.create_envelope:
            return
        if self.base_side:
            self.envelope_head = self.envelope_commit()
            return
        ok(run_git(self.kit, "checkout", BRANCH))
        self.envelope_head = self.envelope_commit()
        ok(run_git(self.kit, "checkout", BASE))

    # -- tower fixture ----------------------------------------------------
    def init_tower(self) -> None:
        evidence = self.root / "tasks" / TASK / "evidence"
        evidence.mkdir(parents=True)
        proof = evidence / "proof.txt"
        proof.write_text("base-side envelope evidence\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "ACCEPTANCE.json", {
            "schema": "tower/acceptance@1",
            "items": [{"id": "A-01", "kind": "auto", "status": "passed",
                       "note": "base-side envelope"}]})
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-063"}, "owner": {"name": "mac"},
            "phase": "TEST"})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": SUPERVISOR}})
        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        write_json(self.root / "tasks" / TASK / "record.json", self.record())

    def record(self) -> dict:
        proof = (self.root / "tasks" / TASK / "evidence" / "proof.txt").read_bytes()
        return {
            "schema": "tower/task@1", "id": TASK, "title": "base-side envelope",
            "status": "delivered", "authority": "workspace_write",
            "scope": ["base-side envelope"],
            "allowed_paths": [f"tower-dsh/tasks/{TASK}/REVIEW.json"],
            "forbidden": ["merge"], "acceptance": ["tests pass"], "depends_on": [],
            "worktree": WORKTREE, "executor": "exec-063",
            "dispatch": {"executor": "exec-063", "worktree": WORKTREE,
                         "base_sha": self.base_sha, "at": FIXED_TIME},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof).hexdigest(),
                          "bytes": len(proof), "at": FIXED_TIME}],
            "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "waiting for independent reviewer",
        }

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"

    def payload(self) -> dict:
        return {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1, "tower_tests_baseline": 1,
        }

    def supervision_events(self) -> list[dict]:
        text = (self.root / "ledger" / "supervision.jsonl").read_text(
            encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    # -- commands ---------------------------------------------------------
    def cli(self, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
        return run_cli(self.root, *args, env_extra=env_extra)

    def accept_task(self, head: str | None = None) -> None:
        cp = self.cli("checkback", "--task", TASK, "--reviewer", REVIEWER,
                      "--verdict", "PASS", "--head",
                      head or self.implementation_head, "--base", self.base_sha)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-063")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def envelope_new(self, *,
                     base_side: bool | None = None) -> subprocess.CompletedProcess:
        write_json(self.root / "envelope.json", self.payload())
        side = self.base_side if base_side is None else base_side
        args = ["envelope-new", "--task", TASK,
                "--file", str(self.root / "envelope.json")]
        if side:
            args.append("--base-side")
        return self.cli(*args)

    def promote(self, *, head: str | None = None,
                base_side: bool | None = None) -> None:
        self.accept_task(head)
        cp = self.envelope_new(base_side=base_side)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def merge_check(self) -> subprocess.CompletedProcess:
        return self.cli("merge-check", "--envelope", ENVELOPE)


class BaseSideGateCase(BaseSideKit):
    """The base-side happy path and the three refusals of ``envelope_checks``."""

    def test_base_side_envelope_checks_clean(self) -> None:
        self.assertNotEqual(self.envelope_head, self.implementation_head)
        self.promote()
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        checks = json.loads(cp.stdout)["checks"]
        self.assertTrue(all(c["ok"] for c in checks),
                        [c for c in checks if not c["ok"]])
        names = [c["name"] for c in checks]
        self.assertIn("branch head == implementation head", names)
        self.assertIn("envelope file in base", names)
        self.assertNotIn("branch head == envelope head", names)
        # The envelope record and its lifecycle events describe base-side.
        envelope = read_json(self.envelope_path())
        self.assertTrue(envelope["base_side"])
        self.assertEqual(envelope["head"], self.envelope_head)
        self.assertEqual(envelope["envelope_head_sha"], self.envelope_head)
        self.assertEqual(envelope["implementation_head_sha"],
                         self.implementation_head)
        events = self.supervision_events()
        created = next(e for e in events if e["type"] == "ENVELOPE_NEW")
        self.assertEqual(created["payload"]["head"], self.envelope_head)
        self.assertTrue(created["payload"]["base_side"])
        self.assertIn("QUEUE_ADD", [e["type"] for e in events])
        # The envelope commit is in main, under the tower prefix; the
        # implementation branch has no envelope file at all.
        present = run_git(self.kit, "cat-file", "-e",
                          f"{BASE}:{self.envelope_repo_path()}")
        self.assertEqual(present.returncode, 0, msg=present.stderr)
        self.assertNotEqual(
            run_git(self.kit, "cat-file", "-e",
                    f"{BRANCH}:{self.envelope_repo_path()}").returncode,
            0)

    def test_envelope_commit_lives_under_the_tower_prefix(self) -> None:
        """PILOT-064: the envelope commit is tower-root relative in the repo."""
        self.promote()
        tower_path = self.envelope_repo_path()
        self.assertTrue(tower_path.startswith("tower-dsh/"))
        self.assertEqual(run_git(self.kit, "cat-file", "-e",
                                 f"{BASE}:{tower_path}").returncode, 0)
        # ... and a repo-root copy is not what the check accepts.
        self.assertNotEqual(run_git(self.kit, "cat-file", "-e",
                                    f"{BASE}:{ENVELOPE_PATH}").returncode, 0)
        self.assertNotEqual(run_git(self.kit, "cat-file", "-e",
                                    f"{BRANCH}:{tower_path}").returncode, 0)

    def test_repo_root_envelope_commit_is_refused(self) -> None:
        """PILOT-064: without the tower prefix the envelope is in the wrong place."""
        self.accept_task()
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.commit("root-level envelope", ENVELOPE_PATH)
        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope commit only changes envelope path", cp.stdout)
        self.assertIn("tower-dsh/merge-envelopes", cp.stdout)
        self.assertFalse(self.envelope_path().exists())
        self.assertEqual(len(self.supervision_events()), 0)

    def test_branch_head_that_is_not_the_implementation_blocks(self) -> None:
        self.promote()
        ok(run_git(self.kit, "checkout", BRANCH))
        (self.kit / "feature.txt").write_text("moved\n", encoding="utf-8")
        moved = self.commit("extra implementation", "feature.txt")
        ok(run_git(self.kit, "checkout", BASE))
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        detail = next(item["detail"] for item in errors
                      if item["name"] == "branch head == implementation head")
        self.assertIn(moved, detail)
        self.assertIn(self.implementation_head, detail)

    def test_review_bound_to_the_envelope_head_blocks(self) -> None:
        self.promote(head=self.envelope_head)
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        detail = next(item["detail"] for item in errors
                      if item["name"] == "review bound to head")
        self.assertIn("stale review: head", detail)
        self.assertIn(self.implementation_head, detail)

    def test_envelope_missing_from_base_blocks(self) -> None:
        self.promote()
        ok(run_git(self.kit, "rm", "--quiet", self.envelope_repo_path()))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit",
                   "-m", "drop envelope"))
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        failed = next(item for item in errors
                      if item["name"] == "envelope file in base")
        self.assertFalse(failed["ok"])
        self.assertNotIn("MERGED", cp.stdout)


class BaseSideShapeCase(BaseSideKit):
    """``envelope-new --base-side`` refuses a base commit that is not envelope-only."""

    create_envelope = False

    def test_extra_file_in_the_base_commit_is_rejected(self) -> None:
        self.accept_task()
        self.envelope_commit("leak.txt")
        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope commit only changes envelope path", cp.stdout)
        self.assertFalse(self.envelope_path().exists())
        self.assertEqual(len(self.supervision_events()), 0)

    def test_non_envelope_commit_on_base_is_rejected(self) -> None:
        self.accept_task()
        (self.kit / "leak.txt").write_text("leak\n", encoding="utf-8")
        self.commit("not an envelope", "leak.txt")
        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope commit only changes envelope path", cp.stdout)
        self.assertFalse(self.envelope_path().exists())
        self.assertEqual(len(self.supervision_events()), 0)


class LegacyBranchSideCase(BaseSideKit):
    """A branch-side envelope (pre-063 layout) keeps the old checks and passes."""

    base_side = False

    def test_branch_side_envelope_still_checks_clean(self) -> None:
        self.assertEqual(run_git(self.kit, "rev-parse", BRANCH).stdout.strip(),
                         self.envelope_head)
        self.promote(base_side=False)
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        checks = json.loads(cp.stdout)["checks"]
        names = [c["name"] for c in checks]
        self.assertIn("branch head == envelope head", names)
        self.assertIn("envelope parent == implementation head", names)
        self.assertNotIn("branch head == implementation head", names)
        self.assertNotIn("base_side", read_json(self.envelope_path()))


class BaseSidePrHeadCase(BaseSideKit):
    """``merge --mode pr`` pins ``--match-head-commit`` at the implementation."""

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.tmp / "origin.git"
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        ok(run_git(self.kit, "remote", "add", "origin",
                   str(self.origin).replace("\\", "/")))
        self.args = argparse.Namespace(
            remote="origin", envelope=ENVELOPE, supervisor=SUPERVISOR,
            check_timeout=10, check_interval=0.05)

    def merge_argv(self) -> list[str]:
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        return next(call for call in calls if call[:2] == ["pr", "merge"])

    def test_pr_merge_pins_the_implementation_head(self) -> None:
        env = self.payload()
        env.update({"base_side": True, "envelope_head_sha": self.envelope_head})
        with head_kit.gh_environment(
                TOWERCTL_GH=f"{sys.executable} {self.gh}",
                RG_GH_LOG=str(self.gh_log)):
            identity = tower_merge.pr_remote_merge(self.kit, env, self.args)
        self.assertEqual(identity["pr_url"], PR_URL)
        argv = self.merge_argv()
        self.assertIn("--merge", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.implementation_head)
        self.assertNotEqual(argv[argv.index("--match-head-commit") + 1],
                            self.envelope_head)


class BaseSideLateStateCase(BaseSideKit):
    """PILOT-065: state commits after the envelope keep ``merge-check`` green.

    The envelope commit is the one the envelope records
    (``envelope_head_sha``).  The base tip legitimately moves on after it with
    ledger/queue/task state commits — the PR CI needs those in base — and they
    must not be re-read as "the envelope commit".
    """

    def test_state_commits_after_the_envelope_keep_merge_check_zero(self) -> None:
        self.promote()
        # Three ordinary post-envelope base commits: ledger, merge queue and
        # task state.  Each one advances the base tip past the envelope.
        append_ledger(self.root, "PHASE", "primary",
                      {"from": "TEST", "to": "TEST",
                       "note": "post-envelope ledger state"})
        queue_path = self.root / "supervision" / "MERGE_QUEUE.json"
        queue = read_json(queue_path)
        queue["state_note"] = "post-envelope queue state"
        write_json(queue_path, queue)
        record_path = self.root / "tasks" / TASK / "record.json"
        record = read_json(record_path)
        record["state_note"] = "post-envelope task state"
        write_json(record_path, record)
        for rel_path, message in (
                ("tower-dsh/ledger/primary.jsonl", "state: ledger"),
                ("tower-dsh/supervision/MERGE_QUEUE.json", "state: queue"),
                ("tower-dsh/tasks/PILOT-063/record.json", "state: task")):
            self.commit(message, rel_path)
        base_tip = run_git(self.kit, "rev-parse", BASE).stdout.strip()
        self.assertNotEqual(base_tip, self.envelope_head)
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        checks = json.loads(cp.stdout)["checks"]
        self.assertTrue(all(c["ok"] for c in checks),
                        [c for c in checks if not c["ok"]])
        in_base = next(c for c in checks if c["name"] == "envelope file in base")
        # The detail names the envelope commit, never the moved base tip.
        self.assertIn(self.envelope_head, in_base["detail"])
        self.assertNotIn(base_tip, in_base["detail"])


class BaseSideEnvelopeHeadCase(BaseSideKit):
    """PILOT-065: the base-side shape is bound to ``envelope_head_sha``.

    ``envelope-new`` refuses both shapes below; these cases bypass it and write
    the record by hand so ``merge-check`` itself is what is under test.
    """

    create_envelope = False

    def install_envelope(self, envelope_head: str) -> None:
        """Hand-write the envelope record and its two lifecycle events."""
        record = self.payload()
        record.update({"envelope_head_sha": envelope_head,
                       "head": envelope_head, "status": "DRAFT",
                       "base_side": True})
        write_json(self.envelope_path(), record)
        append_supervision_ledger(
            self.root, "ENVELOPE_NEW", "primary",
            {"envelope": ENVELOPE, "task": TASK, "head": envelope_head,
             "base_side": True})
        append_supervision_ledger(
            self.root, "QUEUE_ADD", "primary",
            {"envelope": ENVELOPE, "task": TASK})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": BASE,
                         "status": "WAITING", "added_at": FIXED_TIME}]})

    def failed_check(self, cp: subprocess.CompletedProcess,
                     name: str) -> dict:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        failed = next((item for item in errors if item["name"] == name), None)
        self.assertIsNotNone(failed, errors)
        self.assertFalse(failed["ok"])
        return failed

    def test_envelope_head_outside_base_is_rejected(self) -> None:
        """The declared envelope commit must be an ancestor of base (main)."""
        self.accept_task()
        # An envelope-only commit that never lands on base: same shape, wrong
        # branch.  It branches off the implementation head so the parent check
        # still holds; only ``envelope file in base`` may fail.
        ok(run_git(self.kit, "checkout", "-b", "envelope-side"))
        self.write_envelope_file()
        sha = self.commit("envelope off base", self.envelope_repo_path())
        ok(run_git(self.kit, "checkout", BASE))
        self.install_envelope(sha)
        cp = self.merge_check()
        failed = self.failed_check(cp, "envelope file in base")
        self.assertIn("in main", failed["detail"])
        self.assertNotIn("MERGED", cp.stdout)

    def test_envelope_head_carrying_an_extra_file_is_rejected(self) -> None:
        """The envelope commit may only change the envelope path."""
        self.accept_task()
        self.write_envelope_file()
        (self.kit / "leak.txt").write_text("leak\n", encoding="utf-8")
        sha = self.commit("envelope with leak", self.envelope_repo_path(),
                          "leak.txt")
        self.install_envelope(sha)
        cp = self.merge_check()
        failed = self.failed_check(
            cp, "envelope commit only changes envelope path")
        self.assertIn("leak.txt", failed["detail"])
        self.assertIn(self.envelope_repo_path(), failed["detail"])


if __name__ == "__main__":
    unittest.main()
