"""PILOT-061: the PR merge is pinned at the real PR head, not the impl head.

056/059/060 opened a PR whose head was one envelope-only commit on top of the
implementation head, while ``merge --mode pr`` passed the implementation head to
``gh pr merge --match-head-commit``; GitHub answered "Head branch modified" and
the flow fell back to a local merge.  The merge now:

* pins ``--match-head-commit`` at the pushed branch (the PR head);
* accepts that head only when it is the implementation head or exactly one
  commit on top of it whose diff is exactly ``merge-envelopes/<ENV>.json``;
* refuses every other shape (extra files, several paths, several commits, a
  non-descendant head, an empty diff with a different head) with a
  ``MergeBlocked("pr-merge", "merge", ...)`` and no ``MERGED``.

The review binding is untouched: ``merge-check`` still requires the reviewed
head to equal the envelope's implementation head (PILOT-058).

``gh`` is an offline stub injected through ``TOWERCTL_GH``; the "remote" is a
throw-away bare repository under the run sandbox, so nothing here touches a
network.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_merge_head -v
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
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
from tower_common import MergeBlocked  # noqa: E402
# Reuse the PILOT-058 offline gh stub (``TOWERCTL_GH`` / ``RG_GH_LOG`` /
# ``RG_EXPECT_HEAD``): one implementation keeps the suites in step and leaves
# no copy for the shape ratchet to flag.
import test_review_gate as review_gate  # noqa: E402

TASK = "PILOT-061"
ENVELOPE = "ENV-PILOT-061"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
SECOND_ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-061-B.json"
WORKTREE = f"pilot/worktrees/{TASK}"
BRANCH = "pilot/PILOT-061"
BASE = "main"
REVIEWER = "rev-061"
SUPERVISOR = "sup-061"
FIXED_TIME = "2026-11-01T00:00:00+08:00"
PR_URL = review_gate.PR_URL
PR_NUMBER = int(PR_URL.rsplit("/", 1)[1])

GIT_IDENTITY = review_gate.GIT_IDENTITY
GH_STUB = review_gate.GH_STUB
run_cli = review_gate.run_cli
run_git = review_gate.run_git
ok = review_gate.ok
write_json = review_gate.write_json
read_json = review_gate.read_json


@contextlib.contextmanager
def gh_environment(**values: str):
    """Patch exactly the stub's environment for a direct (in-process) call."""
    names = [name for name in os.environ if name.startswith("RG_")]
    saved = {name: os.environ[name] for name in names}
    for name in names:
        del os.environ[name]
    os.environ.update({name: value for name, value in values.items()
                       if value is not None})
    try:
        yield
    finally:
        for name in [name for name in os.environ if name.startswith("RG_")]:
            del os.environ[name]
        os.environ.update(saved)


class RepoKitCase(unittest.TestCase):
    """One throw-away repository: ``base -> implementation -> extras``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-merge-head-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.gh = self.tmp / "gh_stub.py"
        self.gh_log = self.tmp / "gh-argv.jsonl"
        self.gh.write_text(GH_STUB, encoding="utf-8")
        self.init_repo()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ---------------------------------------------------------
    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        ok(run_git(self.kit, "init"))
        ok(run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main"))
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.base_sha = self.commit("base")
        ok(run_git(self.kit, "checkout", "-b", BRANCH))
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit("implementation")

    def commit(self, message: str, *paths: str) -> str:
        """Commit ``paths`` (or everything before the tower root exists).

        Restricting later commits to the files under test keeps the tower root
        (which lives inside the throw-away repository) out of git, so a branch
        switch never deletes tower state.
        """
        add = (["add", "--", *paths] if paths else ["add", "-A"])
        ok(run_git(self.kit, *add))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m", message))
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def add_envelope(self, path: str = ENVELOPE_PATH,
                     message: str = "envelope") -> str:
        target = self.kit / path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, {"envelope_id": ENVELOPE})
        return self.commit(message, path)

    def commit_file(self, path: str, text: str, message: str) -> str:
        target = self.kit / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return self.commit(message, path)

    def head(self, branch: str = BRANCH) -> str:
        return run_git(self.kit, "rev-parse", branch).stdout.strip()

    def env(self, **overrides) -> dict:
        payload = {
            "envelope_id": ENVELOPE, "task": TASK, "repository": "..",
            "branch": BRANCH, "base": BASE, "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
        }
        payload.update(overrides)
        return payload


class PrMergeHeadUnitCase(RepoKitCase):
    """``pr_merge_head`` is the decision point: which head may be pinned."""

    # -- 1. implementation-only PR head ----------------------------------
    def test_implementation_only_head_is_the_implementation(self) -> None:
        self.assertEqual(tower_merge.pr_merge_head(self.kit, self.env()),
                         self.implementation_head)

    # -- 2. implementation + one envelope-only commit --------------------
    def test_envelope_only_commit_is_the_pr_head(self) -> None:
        envelope_head = self.add_envelope()
        self.assertEqual(tower_merge.pr_merge_head(self.kit, self.env()),
                         envelope_head)

    # -- 3. implementation + an extra file -------------------------------
    def test_extra_file_is_blocked(self) -> None:
        self.add_envelope()
        self.commit_file("leak.txt", "implementation change\n", "extra")
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, self.env())
        exc = caught.exception
        self.assertEqual((exc.phase, exc.reason), ("pr-merge", "merge"))
        self.assertIn("leak.txt", exc.detail)
        self.assertIn("only [", exc.detail)

    def test_extra_file_before_envelope_is_blocked(self) -> None:
        self.commit_file("leak.txt", "implementation change\n", "extra")
        self.add_envelope()
        with self.assertRaises(MergeBlocked):
            tower_merge.pr_merge_head(self.kit, self.env())

    # -- 4. two envelope files / several commits -------------------------
    def test_two_envelope_files_are_blocked(self) -> None:
        one = self.add_envelope(message="envelope one")
        self.add_envelope(SECOND_ENVELOPE_PATH, message="envelope two")
        self.assertNotEqual(one, self.head())
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, self.env())
        self.assertIn(SECOND_ENVELOPE_PATH, caught.exception.detail)

    def test_two_commits_on_the_envelope_are_blocked(self) -> None:
        self.add_envelope()
        # A second commit that still only touches the same envelope file keeps
        # the diff at one path; the "one envelope commit" rule must still hold.
        target = self.kit / ENVELOPE_PATH
        write_json(target, {"envelope_id": ENVELOPE, "revision": 2})
        self.commit("envelope revision")
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, self.env())
        self.assertIn("single envelope commit", caught.exception.detail)

    # -- other shapes ----------------------------------------------------
    def test_non_descendant_head_is_blocked(self) -> None:
        # Move the envelope branch back to the base: its head is an ancestor of
        # the implementation head, never a descendant of it.
        ok(run_git(self.kit, "reset", "--hard", self.base_sha))
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, self.env())
        self.assertIn("not a descendant", caught.exception.detail)

    def test_empty_diff_with_a_different_head_is_blocked(self) -> None:
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit",
                   "--allow-empty", "-m", "empty"))
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, self.env())
        self.assertIn("changes []", caught.exception.detail)

    def test_envelope_path_outside_merge_envelopes_is_blocked(self) -> None:
        head = self.commit_file("not-an-envelope.json", "{}\n", "fake envelope")
        env = self.env(envelope_path="not-an-envelope.json")
        with self.assertRaises(MergeBlocked) as caught:
            tower_merge.pr_merge_head(self.kit, env)
        self.assertIn("merge-envelopes", caught.exception.detail)
        self.assertNotEqual(head, self.implementation_head)


class PrRemoteMergeUnitCase(RepoKitCase):
    """``pr_remote_merge`` pins the head it resolved before any CI work."""

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.tmp / "origin.git"
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        ok(run_git(self.kit, "remote", "add", "origin",
                   str(self.origin).replace("\\", "/")))
        # Stay on the envelope branch: ``pr_remote_merge`` pushes it, and the
        # local checkout is irrelevant to the remote half.
        self.args = argparse.Namespace(
            remote="origin", envelope=ENVELOPE, supervisor=SUPERVISOR,
            check_timeout=10, check_interval=0.05)

    def merge(self, env: dict, **rg: str) -> dict:
        values = {
            "TOWERCTL_GH": f"{sys.executable} {self.gh}",
            "RG_GH_LOG": str(self.gh_log),
        }
        values.update(rg)
        with gh_environment(**values):
            return tower_merge.pr_remote_merge(self.kit, env, self.args)

    def merge_argv(self) -> list[str]:
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        return next(call for call in calls if call[:2] == ["pr", "merge"])

    def test_implementation_only_head_pins_implementation(self) -> None:
        identity = self.merge(self.env())
        self.assertEqual(identity["pr_number"], PR_NUMBER)
        argv = self.merge_argv()
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.implementation_head)

    def test_envelope_only_head_pins_the_pr_head(self) -> None:
        envelope_head = self.add_envelope()
        identity = self.merge(self.env(), RG_EXPECT_HEAD=envelope_head)
        self.assertEqual(identity["pr_url"], PR_URL)
        argv = self.merge_argv()
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         envelope_head)

    def test_extra_file_blocks_before_the_pr_is_merged(self) -> None:
        self.add_envelope()
        self.commit_file("leak.txt", "implementation change\n", "extra")
        with self.assertRaises(MergeBlocked) as caught:
            self.merge(self.env())
        self.assertEqual((caught.exception.phase, caught.exception.reason),
                         ("pr-merge", "merge"))
        # The refusal happens before any PR exists: no merge call reached gh.
        self.assertFalse(self.gh_log.exists())


class MergePrModeCliCase(RepoKitCase):
    """End-to-end ``merge --mode pr`` through the real CLI and merge gates."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.kit / "tower-dsh"
        self.origin = self.tmp / "origin.git"
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        ok(run_git(self.kit, "remote", "add", "origin",
                   str(self.origin).replace("\\", "/")))
        ok(run_git(self.kit, "checkout", BASE))
        (self.root / "tasks" / TASK / "evidence").mkdir(parents=True)
        self.proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        self.proof.write_text("merge head evidence\n", encoding="utf-8")
        # PILOT-059+: the accept gate requires a machine-readable list, and the
        # auto item must already be passed before a card can be accepted.
        write_json(self.root / "tasks" / TASK / "ACCEPTANCE.json", {
            "schema": "tower/acceptance@1",
            "items": [{"id": "A-01", "kind": "auto", "status": "passed",
                       "note": "merge head"}],
        })
        self.write_state()

    # -- tower state -----------------------------------------------------
    def write_state(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-061"}, "owner": {"name": "mac"},
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
        write_json(self.record_path(), self.record())

    def record_path(self) -> Path:
        return self.root / "tasks" / TASK / "record.json"

    def record(self, status: str = "delivered") -> dict:
        proof = self.proof.read_bytes()
        return {
            "schema": "tower/task@1", "id": TASK, "title": "merge head",
            "status": status, "authority": "workspace_write",
            "scope": ["pr merge head"],
            "allowed_paths": [f"tower-dsh/tasks/{TASK}/REVIEW.json"],
            "forbidden": ["merge"], "acceptance": ["tests pass"], "depends_on": [],
            "worktree": WORKTREE, "executor": "exec-061",
            "dispatch": {"executor": "exec-061", "worktree": WORKTREE,
                         "base_sha": self.base_sha, "at": FIXED_TIME},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof).hexdigest(),
                          "bytes": len(proof), "at": FIXED_TIME}],
            "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "waiting for independent reviewer",
        }

    def payload(self) -> dict:
        return {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1, "tower_tests_baseline": 1,
        }

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"

    # -- commands --------------------------------------------------------
    def cli(self, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
        return run_cli(self.root, *args, env_extra=env_extra)

    def checkback(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("checkback", "--task", TASK, "--reviewer", REVIEWER,
                        "--verdict", "PASS", *extra)

    def promote(self, *checkback_args: str) -> None:
        """checkback -> accept -> envelope-new -> queue-add (the real flow)."""
        cp = self.checkback(*checkback_args)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-061")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        write_json(self.root / "envelope.json", self.payload())
        cp = self.cli("envelope-new", "--task", TASK,
                      "--file", str(self.root / "envelope.json"))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def queue_add(self) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": BASE, "status": "WAITING",
                         "added_at": FIXED_TIME}]})

    def envelope_commit(self, paths: tuple[str, ...] = (ENVELOPE_PATH,),
                        message: str = "envelope") -> str:
        """Commit the envelope file(s) on the task branch; return its head."""
        ok(run_git(self.kit, "checkout", BRANCH))
        for path in paths:
            write_json(self.kit / path, {"envelope_id": ENVELOPE})
        head = self.commit(message, *paths)
        ok(run_git(self.kit, "checkout", BASE))
        return head

    def merge(self, *, expect_head: str | None = None,
              branch_sha: str | None = None) -> subprocess.CompletedProcess:
        extra = {
            "TOWERCTL_GH": f"{sys.executable} {self.gh}",
            "RG_GH_LOG": str(self.gh_log),
            "RG_ORIGIN": str(self.origin).replace("\\", "/"),
            "RG_BRANCH_SHA": branch_sha or self.head(),
        }
        if expect_head is not None:
            extra["RG_EXPECT_HEAD"] = expect_head
        return self.cli("merge", "--envelope", ENVELOPE, "--role", "supervisor",
                        "--supervisor", SUPERVISOR, "--mode", "pr",
                        env_extra=extra)

    def merge_argv(self) -> list[str]:
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        return next(call for call in calls if call[:2] == ["pr", "merge"])

    def ledger_types(self) -> list[str]:
        return [json.loads(line)["type"] for line in
                (self.root / "ledger" / "supervision.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()]

    # -- 2. implementation + envelope-only head merges at the PR head ----
    def test_envelope_only_head_merges_pinned_at_pr_head(self) -> None:
        envelope_head = self.envelope_commit()
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        self.assertNotEqual(envelope_head, self.implementation_head)
        cp = self.merge(expect_head=envelope_head)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["status"], "MERGED")
        argv = self.merge_argv()
        self.assertIn("--match-head-commit", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         envelope_head)
        self.assertNotIn("Head branch modified", cp.stdout + cp.stderr)
        envelope = read_json(self.envelope_path())
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_commit"], envelope_head)
        self.assertEqual(envelope["implementation_head_sha"],
                         self.implementation_head)

    # -- 3. an extra commit on the PR branch never merges ----------------
    def test_extra_commit_never_merges(self) -> None:
        self.envelope_commit()
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        ok(run_git(self.kit, "checkout", BRANCH))
        self.commit_file("leak.txt", "implementation change\n", "extra")
        extra_head = self.head()
        ok(run_git(self.kit, "checkout", BASE))
        cp = self.merge(branch_sha=extra_head)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("branch head == envelope head", cp.stdout)
        envelope = read_json(self.envelope_path())
        self.assertNotEqual(envelope["status"], "MERGED")
        self.assertNotIn("merge_commit", envelope)
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        entry = next(e for e in queue["entries"] if e["envelope_id"] == ENVELOPE)
        self.assertEqual(entry["status"], "CORRECTION_REQUIRED")
        self.assertNotIn("MERGE", self.ledger_types())
        self.assertNotIn("MERGED", cp.stdout)

    # -- 4. two envelope files in one commit never merges ----------------
    def test_two_envelope_files_never_merge(self) -> None:
        cp = self.checkback("--head", self.implementation_head,
                            "--base", self.base_sha)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-061")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        head = self.envelope_commit((ENVELOPE_PATH, SECOND_ENVELOPE_PATH),
                                    "two envelopes")
        write_json(self.envelope_path(), {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": head, "status": "DRAFT",
        })
        self.queue_add()
        cp = self.merge(branch_sha=head)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope commit only changes envelope path", cp.stdout)
        self.assertNotIn("MERGED", cp.stdout)
        self.assertNotIn("MERGE", self.ledger_types())

    # -- 5. the review binding still pins the implementation head --------
    def test_review_head_that_is_not_the_implementation_blocks(self) -> None:
        envelope_head = self.envelope_commit()
        self.promote("--head", envelope_head, "--base", self.base_sha)
        cp = self.cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        detail = next(item["detail"] for item in errors
                      if item["name"] == "review bound to head")
        self.assertIn("stale review: head", detail)
        self.assertIn(self.implementation_head, detail)
        # The same stale review cannot be smuggled past the PR merge either.
        cp = self.merge(expect_head=envelope_head)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("MERGED", cp.stdout)


if __name__ == "__main__":
    unittest.main()
