"""PILOT-058: structured REVIEW.json, head/base binding and expected-head merge.

Three behaviours are pinned here, each driven through the real CLI in a
subprocess so the observable exit code and the written bytes are what is
asserted:

* ``checkback`` writes ``tasks/<id>/REVIEW.json`` for PASS *and* FAIL, binding
  the verdict to the reviewed head (default: the task worktree HEAD) and the
  dispatch base (default: ``record.dispatch.base_sha``);
* ``merge-check`` refuses a review whose head/base is not the envelope's, and
  reports a pre-058 card (no structured ``CHECKBACK`` event) as legacy instead
  of retro-fitting a ``REVIEW.json``;
* ``merge --mode pr`` passes ``--match-head-commit`` to ``gh pr merge``.

``gh`` is an offline stub injected through ``TOWERCTL_GH``; the "remote" is a
throw-away bare repository under ``%TEMP%``, so nothing here touches a network.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_review_gate -v
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
TASK = "T-REVIEW-058"
ENVELOPE = "ENV-REVIEW-058"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
WORKTREE = f"pilot/worktrees/{TASK}"
BRANCH = "feature/review"
BASE = "main"
REVIEWER = "rev-058"
FIXED_TIME = "2026-11-01T00:00:00+08:00"
BASE_SHA = "1" * 40
REVIEW_SCHEMA = "tower/review@1"
REVIEW_CHECK = "review bound to head"
PR_URL = "https://example.invalid/pull/58"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

# Offline ``gh`` stub.  ``pr merge`` records its argv (``RG_GH_LOG``) and can
# refuse a merge whose ``--match-head-commit`` value is not the PR head the
# caller pinned (``RG_EXPECT_HEAD``), which is how real gh reports the mismatch.
GH_STUB = '''"""Offline gh stub for test_review_gate.py."""
import json
import os
import subprocess
import sys


def record(argv):
    path = os.environ.get("RG_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\\n")


def pr_merge(argv):
    record(argv)
    if "--match-head-commit" not in argv:
        sys.stderr.write("a merge must name the head commit\\n")
        return 1
    wanted = os.environ.get("RG_EXPECT_HEAD", "")
    actual = argv[argv.index("--match-head-commit") + 1]
    if wanted and actual != wanted:
        sys.stderr.write("head commit mismatch: the PR head is " + wanted + "\\n")
        return 1
    origin = os.environ.get("RG_ORIGIN")
    sha = os.environ.get("RG_BRANCH_SHA")
    if origin and sha:
        subprocess.run(["git", "--git-dir", origin, "update-ref",
                        "refs/heads/main", sha], check=True, capture_output=True)
    return 0


def main(argv):
    if argv[:2] == ["pr", "merge"]:
        return pr_merge(argv)
    if argv[:2] == ["pr", "create"]:
        print("https://example.invalid/pull/58")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def run_cli(root: Path, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("RG_")}
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_IDENTITY}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ok(cp: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    """Fail the current test unless the child exit code is 0."""
    if cp.returncode != 0:
        raise AssertionError(f"exit {cp.returncode}: {cp.stdout}{cp.stderr}")
    return cp


def init_worktree_repo(path: Path) -> str:
    """A real repository standing in for the executor's worktree; returns HEAD."""
    path.mkdir(parents=True, exist_ok=True)
    ok(run_git(path, "init"))
    ok(run_git(path, "symbolic-ref", "HEAD", "refs/heads/main"))
    (path / "reviewed.txt").write_text("reviewed code\n", encoding="utf-8")
    ok(run_git(path, "add", "-A"))
    ok(run_git(path, "-c", "commit.gpgsign=false", "commit", "-m", "implementation"))
    return run_git(path, "rev-parse", "HEAD").stdout.strip()


class CheckbackReviewJsonCase(unittest.TestCase):
    """``checkback`` writes the structured review; defaults come from disk."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-review-json-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower"
        self.worktree = self.root / WORKTREE
        self.head = init_worktree_repo(self.worktree)
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-058"}, "owner": {"name": "mac"}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": "review json",
            "status": "delivered", "authority": "workspace_write",
            "scope": ["review"], "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge"], "acceptance": ["tests pass"], "depends_on": [],
            "worktree": WORKTREE, "executor": "exec-a",
            "dispatch": {"executor": "exec-a", "worktree": WORKTREE,
                         "base_sha": BASE_SHA, "at": FIXED_TIME},
            "evidence": [], "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "等待独立 reviewer",
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def checkback(self, *extra: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, "checkback", "--task", TASK,
                       "--reviewer", REVIEWER, "--verdict", "PASS", *extra)

    def review(self) -> dict:
        return read_json(self.root / "tasks" / TASK / "REVIEW.json")

    def record(self) -> dict:
        return read_json(self.root / "tasks" / TASK / "record.json")

    # -- 1. defaults: worktree HEAD + dispatch base ----------------------
    def test_pass_writes_json_with_worktree_head_and_dispatch_base(self) -> None:
        cp = self.checkback("--scope", "tools/towerctl.py",
                            "--finding", "head is bound", "--note", "ok")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        review = self.review()
        self.assertEqual(review["schema"], REVIEW_SCHEMA)
        self.assertEqual(review["task"], TASK)
        self.assertEqual(review["reviewer"], REVIEWER)
        self.assertEqual(review["verdict"], "PASS")
        self.assertEqual(review["head"], self.head)
        self.assertEqual(review["base"], BASE_SHA)
        self.assertEqual(review["scope"], ["tools/towerctl.py"])
        self.assertEqual(review["findings"], ["head is bound"])
        self.assertEqual(review["note"], "ok")
        self.assertTrue(review["at"])
        record = self.record()
        self.assertEqual(record["status"], "reviewed")
        self.assertEqual(record["review"]["reviewer"], REVIEWER)
        self.assertEqual(record["review"]["head"], self.head)
        self.assertEqual(record["review"]["base"], BASE_SHA)

    # -- 2. explicit flags win over the defaults -------------------------
    def test_explicit_head_and_base_override_defaults(self) -> None:
        other = "2" * 40
        cp = self.checkback("--head", other, "--base", other)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        review = self.review()
        self.assertEqual(review["head"], other)
        self.assertEqual(review["base"], other)
        self.assertEqual(review["scope"], [])
        self.assertEqual(review["findings"], [])

    # -- 3. FAIL is written too ------------------------------------------
    def test_fail_writes_verdict_fail_and_rework(self) -> None:
        cp = run_cli(self.root, "checkback", "--task", TASK,
                     "--reviewer", REVIEWER, "--verdict", "FAIL",
                     "--note", "head does not match")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        review = self.review()
        self.assertEqual(review["verdict"], "FAIL")
        self.assertEqual(review["head"], self.head)
        self.assertEqual(review["base"], BASE_SHA)
        self.assertEqual(review["note"], "head does not match")
        self.assertEqual(self.record()["status"], "rework")


class ReviewGateKitCase(unittest.TestCase):
    """Shared kit: repo with base/branch/implementation/envelope + tower root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-review-gate-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.origin = self.tmp / "origin.git"
        self.gh = self.tmp / "gh_stub.py"
        self.gh_log = self.tmp / "gh-merge-argv.jsonl"
        self.gh.write_text(GH_STUB, encoding="utf-8")
        (self.root / "tasks" / TASK / "evidence").mkdir(parents=True)
        self.proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        self.proof.write_text("review gate evidence\n", encoding="utf-8")
        self.init_repo()
        self.init_origin()
        self.write_state()

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
        (self.kit / "merge-envelopes").mkdir()
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.envelope_head = self.commit("envelope")
        ok(run_git(self.kit, "checkout", BASE))

    def init_origin(self) -> None:
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        remote = str(self.origin).replace("\\", "/")
        ok(run_git(self.kit, "remote", "add", "origin", remote))

    def commit(self, message: str) -> str:
        ok(run_git(self.kit, "add", "-A"))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m", message))
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def write_state(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-058"}, "owner": {"name": "mac"},
            "phase": "TEST"})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": "sup-058"}})
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
            "schema": "tower/task@1", "id": TASK, "title": "structured review",
            "status": status, "authority": "workspace_write",
            "scope": ["review gate"],
            "allowed_paths": [f"tower-dsh/tasks/{TASK}/REVIEW.json"],
            "forbidden": ["merge"], "acceptance": ["tests pass"], "depends_on": [],
            "worktree": WORKTREE, "executor": "exec-a",
            "dispatch": {"executor": "exec-a", "worktree": WORKTREE,
                         "base_sha": self.base_sha, "at": FIXED_TIME},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof).hexdigest(),
                          "bytes": len(proof), "at": FIXED_TIME}],
            "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "等待独立 reviewer",
        }

    def payload(self) -> dict:
        return {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1, "tower_tests_baseline": 1,
        }

    # -- commands --------------------------------------------------------
    def cli(self, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
        return run_cli(self.root, *args, env_extra=env_extra)

    def checkback(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("checkback", "--task", TASK, "--reviewer", REVIEWER,
                        "--verdict", "PASS", *extra)

    def merge_check(self) -> subprocess.CompletedProcess:
        return self.cli("merge-check", "--envelope", ENVELOPE)

    def review_path(self) -> Path:
        return self.root / "tasks" / TASK / "REVIEW.json"

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"

    def promote(self, *checkback_args: str) -> None:
        """checkback -> accept -> envelope-new -> queue-add (the 058 flow)."""
        cp = self.checkback(*checkback_args)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-058")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        write_json(self.root / "envelope.json", self.payload())
        cp = self.cli("envelope-new", "--task", TASK,
                      "--file", str(self.root / "envelope.json"))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)


class MergeCheckReviewGateCase(ReviewGateKitCase):
    """``merge-check`` requires a PASS review bound to the envelope's head."""

    def errors(self, cp: subprocess.CompletedProcess) -> list[dict]:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)["errors"]

    def test_matching_head_and_base_passes(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        check = next(c for c in payload["checks"] if c["name"] == REVIEW_CHECK)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["detail"], "ok")

    def test_missing_review_json_fails_stale(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        self.review_path().unlink()
        failed = self.errors(self.merge_check())
        names = [item["name"] for item in failed]
        self.assertIn(REVIEW_CHECK, names, msg=failed)
        detail = next(item["detail"] for item in failed
                      if item["name"] == REVIEW_CHECK)
        self.assertIn("stale review", detail)
        self.assertIn("missing", detail)

    def test_fail_verdict_fails_merge_check(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        review = read_json(self.review_path())
        review["verdict"] = "FAIL"
        write_json(self.review_path(), review)
        failed = self.errors(self.merge_check())
        detail = next(item["detail"] for item in failed
                      if item["name"] == REVIEW_CHECK)
        self.assertIn("verdict", detail)
        self.assertIn("FAIL", detail)

    def test_head_mismatch_is_stale(self) -> None:
        self.promote("--head", self.envelope_head, "--base", self.base_sha)
        failed = self.errors(self.merge_check())
        detail = next(item["detail"] for item in failed
                      if item["name"] == REVIEW_CHECK)
        self.assertIn("stale review: head", detail)
        self.assertIn(self.implementation_head, detail)

    def test_base_mismatch_is_stale(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.envelope_head)
        failed = self.errors(self.merge_check())
        detail = next(item["detail"] for item in failed
                      if item["name"] == REVIEW_CHECK)
        self.assertIn("stale review: base", detail)
        self.assertIn(self.base_sha, detail)

    def test_new_head_needs_recheckback_before_merge_check_passes(self) -> None:
        # The review covers an older head, so the merge is refused as stale.
        self.promote("--head", self.base_sha, "--base", self.base_sha)
        self.errors(self.merge_check())
        # Re-review the accepted card at the envelope head, then re-accept it.
        cp = self.checkback("--head", self.implementation_head,
                            "--base", self.base_sha)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(read_json(self.review_path())["head"],
                         self.implementation_head)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-058R")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def test_legacy_envelope_json_remains_the_only_binding(self) -> None:
        # Rewriting REVIEW.json cannot smuggle a different head past the gate:
        # the envelope head is read from the envelope, never from the review.
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        review = read_json(self.review_path())
        review["head"] = self.base_sha
        write_json(self.review_path(), review)
        failed = self.errors(self.merge_check())
        self.assertEqual([item["name"] for item in failed], [REVIEW_CHECK])


class LegacyReviewCompatCase(ReviewGateKitCase):
    """A pre-058 card (no structured CHECKBACK event) is reported as legacy."""

    def test_legacy_review_without_checkback_is_not_retrofitted(self) -> None:
        record = self.record(status="closed")
        record["review"] = {"reviewer": REVIEWER, "verdict": "PASS"}
        write_json(self.record_path(), record)
        legacy = self.payload()
        legacy.pop("tests_baseline")
        legacy.pop("tower_tests_baseline")
        legacy.update({"status": "DRAFT",
                       "envelope_head_sha": self.envelope_head})
        write_json(self.envelope_path(), legacy)
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": BASE, "status": "WAITING",
                         "added_at": FIXED_TIME}]})
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        check = next(c for c in payload["checks"] if c["name"] == REVIEW_CHECK)
        self.assertTrue(check["ok"], check)
        self.assertIn("legacy", check["detail"])
        self.assertFalse(self.review_path().exists())

    def test_review_json_without_structured_checkback_is_rejected(self) -> None:
        """A REVIEW.json without a head-bearing CHECKBACK is not legacy."""
        record = self.record(status="closed")
        record["review"] = {"reviewer": REVIEWER, "verdict": "PASS"}
        write_json(self.record_path(), record)
        write_json(self.review_path(), {"schema": "tower/review@1",
                                        "verdict": "PASS"})
        legacy = self.payload()
        legacy.pop("tests_baseline")
        legacy.pop("tower_tests_baseline")
        legacy.update({"status": "DRAFT",
                       "envelope_head_sha": self.envelope_head})
        write_json(self.envelope_path(), legacy)
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": BASE, "status": "WAITING",
                         "added_at": FIXED_TIME}]})
        cp = self.merge_check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("structured CHECKBACK", cp.stdout + cp.stderr)


class ExpectedHeadMergeCase(ReviewGateKitCase):
    """``merge --mode pr`` pins ``gh pr merge`` to the envelope head."""

    def run_merge(self, *args: str,
                  expect_head: str | None = None) -> subprocess.CompletedProcess:
        extra = {"TOWERCTL_GH": f"{sys.executable} {self.gh}",
                 "RG_GH_LOG": str(self.gh_log),
                 "RG_ORIGIN": str(self.origin).replace("\\", "/"),
                 "RG_BRANCH_SHA": self.envelope_head}
        if expect_head is not None:
            extra["RG_EXPECT_HEAD"] = expect_head
        return self.cli("merge", "--envelope", ENVELOPE, "--role", "supervisor",
                        "--supervisor", "sup-058", "--mode", "pr", *args,
                        env_extra=extra)

    def merge_argv(self) -> list[str]:
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return next(call for call in calls if call[:2] == ["pr", "merge"])

    def test_pr_merge_passes_match_head_commit(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        cp = self.run_merge(expect_head=self.implementation_head)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["status"], "MERGED")
        argv = self.merge_argv()
        self.assertIn("--match-head-commit", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.implementation_head)
        self.assertIn("--merge", argv)
        envelope = read_json(self.envelope_path())
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["implementation_head_sha"],
                         self.implementation_head)

    def test_pr_merge_head_mismatch_does_not_merge(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)
        # The PR head moved: gh rejects the pinned --match-head-commit value.
        cp = self.run_merge(expect_head=self.envelope_head)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertFalse(json.loads(cp.stdout)["ok"])
        envelope = read_json(self.envelope_path())
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertNotEqual(envelope["status"], "MERGED")
        self.assertNotIn("merge_commit", envelope)
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        entry = next(e for e in queue["entries"] if e["envelope_id"] == ENVELOPE)
        self.assertEqual(entry["status"], "CORRECTION_REQUIRED")
        events = [json.loads(line) for line in
                  (self.root / "ledger" / "supervision.jsonl").read_text(
                      encoding="utf-8").splitlines() if line.strip()]
        self.assertNotIn("MERGE", [event["type"] for event in events])
        self.assertIn("MERGE_BLOCKED", [event["type"] for event in events])
        argv = self.merge_argv()
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.implementation_head)


if __name__ == "__main__":
    unittest.main()
