"""PILOT-076: owner GitHub approval, and the actor removed from accepts.

Three behaviours are pinned here through the real CLI in a subprocess:

* ``shared/AUTHORITY_MODEL.json`` must pin a non-empty owner and primary
  ``github_login`` and the two must differ; ``authority-check`` fails otherwise;
* ``merge --mode pr`` reads ``gh pr view <n> --json author,reviews`` and only
  merges a PR with the owner's ``APPROVED`` review that is neither the primary
  tower login nor the PR author -- a 077+ card never merges without it, while
  PILOT-076 keeps its legacy bootstrap path;
* ``accept`` / ``post-merge`` no longer write the hard-coded ``actor: "owner"``:
  they record ``--by`` (default: the authority model's owner name) and refuse a
  ``--by`` that disagrees with the registered owner.

``gh`` is an offline stub injected through ``TOWERCTL_GH``; the "remote" is a
throw-away bare repository under the run's temp directory, so nothing here
touches a network.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_owner_approval -v
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
TASK = "PILOT-077"
WORKTREE = f"pilot/worktrees/{TASK}"
REVIEWER = "rev-076"
EXECUTOR = "exec-076"
SUPERVISOR = "sup-076"
BASE = "main"
BRANCH = "feature/owner-approval"
FIXED_TIME = "2026-11-02T00:00:00+08:00"
OWNER_LOGIN = "owner-login"
PRIMARY_LOGIN = "primary-login"
AUTHOR_LOGIN = "author-login"
PR_URL = "https://example.invalid/pull/77"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

# Offline ``gh`` stub: the author/approvers it reports come from OA_* variables,
# so each test states the review shape it exercises.  A successful ``pr merge``
# advances the bare origin's ``main`` to the envelope head, which gives the
# follow-up fetch + ff-only merge a real fast-forward to perform.
GH_STUB = '''"""Offline gh stub for test_owner_approval.py."""
import json
import os
import subprocess
import sys

OA_URL = "https://example.invalid/pull/77"


def log(argv):
    path = os.environ.get("OA_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\\n")


def review_payload():
    approvers = [item for item in os.environ.get("OA_APPROVERS", "").split(",")
                 if item]
    return {"number": 77, "url": os.environ.get("OA_PR_URL", OA_URL),
            "author": {"login": os.environ.get("OA_AUTHOR", "")},
            "reviews": [{"author": {"login": login}, "state": "APPROVED"}
                        for login in approvers]}


def merge():
    origin = os.environ.get("OA_ORIGIN")
    sha = os.environ.get("OA_BRANCH_SHA")
    if origin and sha:
        subprocess.run(["git", "--git-dir", origin, "update-ref",
                        "refs/heads/main", sha], check=True, capture_output=True)
    return 0


def main(argv):
    log(argv)
    if argv[:2] == ["pr", "create"]:
        print(os.environ.get("OA_PR_URL", OA_URL))
        return 0
    if argv[:2] == ["pr", "view"]:
        print(json.dumps(review_payload()))
        return 0
    if argv[:2] == ["pr", "merge"]:
        return merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def run_cli(root: Path, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("OA_")}
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


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
    if cp.returncode != 0:
        raise AssertionError(f"exit {cp.returncode}: {cp.stdout}{cp.stderr}")
    return cp


def authority_model(owner: str, primary: str) -> dict:
    """A model body with the two GitHub logins under test."""
    return {
        "schema": "tower/authority-model@1",
        "roles": {
            "owner": {"name": "mac", "github_login": owner},
            "primary_control_tower": {"github_login": primary},
        },
    }


class AuthorityModelCase(unittest.TestCase):
    """``authority-check`` requires both GitHub logins, distinct."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-owner-model-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower"
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-model",
            "role": "primary", "primary": {"id": "ctl-076"},
            "owner": {"name": "mac"}})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_model(self, owner, primary) -> None:
        write_json(self.root / "shared" / "AUTHORITY_MODEL.json",
                   authority_model(owner, primary))

    def check(self) -> subprocess.CompletedProcess:
        return run_cli(self.root, "authority-check")

    def test_valid_logins_pass_and_are_reported(self) -> None:
        self.write_model(OWNER_LOGIN, PRIMARY_LOGIN)
        cp = self.check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        names = [item["name"] for item in payload["checks"]]
        self.assertIn("authority github logins", names)

    def test_missing_owner_login_fails(self) -> None:
        self.write_model("", PRIMARY_LOGIN)
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("roles.owner.github_login", cp.stdout)

    def test_missing_primary_login_fails(self) -> None:
        self.write_model(OWNER_LOGIN, "")
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("roles.primary_control_tower.github_login", cp.stdout)

    def test_equal_logins_fail(self) -> None:
        self.write_model(OWNER_LOGIN, OWNER_LOGIN)
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("equals primary_control_tower", cp.stdout)


class OwnerApprovalKit(unittest.TestCase):
    """A kit repository: base, implementation branch, envelope commit, tower."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-owner-merge-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.origin = self.tmp / "origin.git"
        self.gh = self.tmp / "gh.py"
        self.gh_log = self.tmp / "gh-calls.jsonl"
        self.gh.write_text(GH_STUB, encoding="utf-8")
        self.init_kit()
        self.init_origin()
        self.write_state()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def init_kit(self) -> None:
        self.kit.mkdir(parents=True)
        ok(run_git(self.kit, "init"))
        ok(run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main"))
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.base_sha = self.commit("base")
        ok(run_git(self.kit, "checkout", "-b", BRANCH))
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.impl_head = self.commit("implementation")
        (self.kit / "merge-envelopes").mkdir()
        self.envelope_path = f"merge-envelopes/ENV-{TASK}.json"
        write_json(self.kit / self.envelope_path, {"envelope_id": f"ENV-{TASK}"})
        self.envelope_head = self.commit("envelope")
        ok(run_git(self.kit, "checkout", BASE))

    def init_origin(self) -> None:
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        ok(run_git(self.kit, "remote", "add", "origin",
                   str(self.origin).replace("\\", "/")))

    def commit(self, message: str) -> str:
        ok(run_git(self.kit, "add", "-A"))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit",
                   "-m", message))
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def write_model(self, owner: str = OWNER_LOGIN,
                    primary: str = PRIMARY_LOGIN) -> None:
        write_json(self.root / "shared" / "AUTHORITY_MODEL.json",
                   authority_model(owner, primary))

    def write_state(self) -> None:
        self.write_model()
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-owner",
            "role": "primary", "phase": "TEST",
            "primary": {"id": "ctl-076"}, "owner": {"name": "mac"}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": SUPERVISOR}})
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})

    def proof(self, task: str) -> Path:
        path = self.root / "tasks" / task / "evidence" / "proof.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{task} proof\n", encoding="utf-8")
        return path

    def write_record(self, task: str) -> None:
        proof = self.proof(task)
        write_json(self.root / "tasks" / task / "record.json", {
            "schema": "tower/task@1", "id": task, "title": task,
            "status": "delivered", "authority": "workspace_write",
            "scope": ["owner approval"], "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge"], "acceptance": ["tests pass"],
            "depends_on": [], "worktree": f"pilot/worktrees/{task}",
            "executor": EXECUTOR,
            "dispatch": {"executor": EXECUTOR, "worktree": f"pilot/worktrees/{task}",
                         "base_sha": self.base_sha, "at": FIXED_TIME},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{task}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                          "bytes": proof.stat().st_size, "at": FIXED_TIME}],
            "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "等待独立 reviewer"})

    def payload(self, task: str) -> dict:
        return {"schema": "tower/merge-envelope@1",
                "envelope_id": f"ENV-{task}", "task": task,
                "repository": "..", "branch": BRANCH, "base": BASE,
                "envelope_path": self.envelope_path,
                "implementation_head_sha": self.impl_head,
                "tests_baseline": 1, "tower_tests_baseline": 1}

    def cli(self, *args: str,
            env_extra: dict | None = None) -> subprocess.CompletedProcess:
        return run_cli(self.root, *args, env_extra=env_extra)

    def promote(self, task: str) -> None:
        """record -> checkback -> acceptance -> accept -> envelope -> queue."""
        self.write_record(task)
        envelope_id = f"ENV-{task}"
        ok(self.cli("checkback", "--task", task, "--reviewer", REVIEWER,
                    "--verdict", "PASS", "--head", self.impl_head,
                    "--base", self.base_sha))
        ok(self.cli("acceptance-add", "--task", task, "--id", "A-01",
                    "--kind", "auto", "--status", "passed"))
        ok(self.cli("accept", "--task", task, "--decision", f"D-{task}"))
        write_json(self.root / "envelope.json", self.payload(task))
        ok(self.cli("envelope-new", "--task", task,
                    "--file", str(self.root / "envelope.json")))
        ok(self.cli("queue-add", "--envelope", envelope_id))

    def run_merge(self, task: str, author: str, approvers: str) -> subprocess.CompletedProcess:
        env_extra = {
            "TOWERCTL_GH": f"{sys.executable} {self.gh}",
            "OA_GH_LOG": str(self.gh_log),
            "OA_PR_URL": PR_URL,
            "OA_ORIGIN": str(self.origin).replace("\\", "/"),
            "OA_BRANCH_SHA": self.envelope_head,
            "OA_AUTHOR": author,
            "OA_APPROVERS": approvers,
        }
        return self.cli("merge", "--envelope", f"ENV-{task}", "--role",
                        "supervisor", "--supervisor", SUPERVISOR,
                        "--mode", "pr", env_extra=env_extra)

    def events(self) -> list[dict]:
        path = self.root / "ledger" / "supervision.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def envelope(self, task: str) -> dict:
        return read_json(self.root / "supervision" / "envelopes"
                         / f"ENV-{task}.json")


class MergeOwnerApprovalCase(OwnerApprovalKit):
    """``merge --mode pr`` refuses any PR without the owner's approval."""

    def test_owner_approved_pr_merges(self) -> None:
        self.promote(TASK)
        cp = self.run_merge(TASK, AUTHOR_LOGIN, OWNER_LOGIN)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["status"], "MERGED")
        self.assertEqual(self.envelope(TASK)["status"], "MERGED")
        self.assertIn("MERGE", [event["type"] for event in self.events()])

    def test_pr_view_reads_author_and_reviews(self) -> None:
        self.promote(TASK)
        cp = self.run_merge(TASK, AUTHOR_LOGIN, OWNER_LOGIN)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        views = [call for call in calls if call[:2] == ["pr", "view"]]
        self.assertEqual(len(views), 1, msg=calls)
        self.assertEqual(views[0][-1], "author,reviews")
        self.assertEqual(views[0][2], "77")

    def test_missing_owner_approval_blocks(self) -> None:
        self.promote(TASK)
        cp = self.run_merge(TASK, AUTHOR_LOGIN, "someone-else")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("no APPROVED review", cp.stdout)
        self.assertNotIn("MERGE", [event["type"] for event in self.events()])
        self.assertEqual(self.envelope(TASK)["status"], "CORRECTION_REQUIRED")

    def test_owner_equals_primary_blocks(self) -> None:
        self.promote(TASK)
        self.write_model(OWNER_LOGIN, OWNER_LOGIN)
        cp = self.run_merge(TASK, AUTHOR_LOGIN, OWNER_LOGIN)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("equals the primary login", cp.stdout)
        self.assertNotIn("MERGE", [event["type"] for event in self.events()])

    def test_owner_self_approval_blocks(self) -> None:
        self.promote(TASK)
        cp = self.run_merge(TASK, OWNER_LOGIN, OWNER_LOGIN)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("self-approval", cp.stdout)
        self.assertNotIn("MERGE", [event["type"] for event in self.events()])

    def test_primary_login_approval_blocks(self) -> None:
        self.promote(TASK)
        cp = self.run_merge(TASK, AUTHOR_LOGIN, PRIMARY_LOGIN)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("primary control tower", cp.stdout)
        self.assertNotIn("MERGE", [event["type"] for event in self.events()])

    def test_pilot_076_keeps_the_legacy_bootstrap_path(self) -> None:
        """076 merged before the gate existed, so no owner review is required."""
        self.promote("PILOT-076")
        cp = self.run_merge("PILOT-076", AUTHOR_LOGIN, "")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope("PILOT-076")["status"], "MERGED")
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([call for call in calls if call[:2] == ["pr", "view"]], [])


class AcceptActorCase(unittest.TestCase):
    """``accept`` records the owner actor and refuses a mismatching ``--by``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-owner-accept-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower"
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-accept",
            "role": "primary", "primary": {"id": "ctl-076"},
            "owner": {"name": "mac"}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.root / "ledger").mkdir(parents=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.parent.mkdir(parents=True)
        proof.write_text("accept proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": "accept actor",
            "status": "reviewed", "authority": "workspace_write",
            "scope": ["accept actor"], "allowed_paths": ["tools/towerctl.py"],
            "forbidden": ["merge"], "acceptance": ["tests pass"],
            "depends_on": [], "worktree": WORKTREE, "executor": EXECUTOR,
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                          "bytes": proof.stat().st_size, "at": FIXED_TIME}],
            "review": {"reviewer": REVIEWER, "verdict": "PASS",
                       "head": "a" * 40, "base": "b" * 40},
            "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME, "next": ""})
        write_json(self.root / "tasks" / TASK / "ACCEPTANCE.json", {
            "schema": "tower/acceptance@1", "task": TASK,
            "items": [{"id": "A-01", "kind": "auto", "status": "passed",
                       "note": ""}]})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def record(self) -> dict:
        return read_json(self.root / "tasks" / TASK / "record.json")

    def test_default_actor_is_the_owner_not_the_old_literal(self) -> None:
        cp = run_cli(self.root, "accept", "--task", TASK,
                     "--decision", "D-076")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        decision = self.record()["decision"]
        self.assertEqual(decision["actor"], "mac")
        self.assertNotEqual(decision["actor"], "owner")

    def test_by_mismatch_is_refused_with_zero_writes(self) -> None:
        before = (self.root / "tasks" / TASK / "record.json").read_bytes()
        cp = run_cli(self.root, "accept", "--task", TASK,
                     "--decision", "D-076", "--by", "mallory")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("registered owner", cp.stdout)
        self.assertEqual((self.root / "tasks" / TASK / "record.json").read_bytes(),
                         before)

    def test_explicit_owner_by_is_recorded(self) -> None:
        cp = run_cli(self.root, "accept", "--task", TASK,
                     "--decision", "D-076", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record()["decision"]["actor"], "mac")

    def test_post_merge_refuses_a_non_owner_by(self) -> None:
        cp = run_cli(self.root, "post-merge", "--envelope", "ENV-NONE",
                     "--by", "mallory")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("registered owner", cp.stdout)

    # -- git author consistency (PILOT-076 rework) ------------------------
    def make_git_repo(self, name: str) -> None:
        """Make the tower root a repo whose author identity is ``name``."""
        ok(run_git(self.root, "init"))
        ok(run_git(self.root, "config", "user.name", name))

    def test_git_author_mismatch_is_refused_with_zero_writes(self) -> None:
        self.make_git_repo("mallory")
        before = (self.root / "tasks" / TASK / "record.json").read_bytes()
        cp = run_cli(self.root, "accept", "--task", TASK, "--decision", "D-076")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("git author", cp.stdout)
        self.assertEqual(
            (self.root / "tasks" / TASK / "record.json").read_bytes(), before)

    def test_git_author_matching_the_owner_is_accepted(self) -> None:
        self.make_git_repo("mac (jihaijiang999-jhj)")
        cp = run_cli(self.root, "accept", "--task", TASK, "--decision", "D-076")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record()["decision"]["actor"], "mac")

    def test_post_merge_refuses_a_mismatching_git_author(self) -> None:
        self.make_git_repo("mallory")
        cp = run_cli(self.root, "post-merge", "--envelope", "ENV-NONE")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("git author", cp.stdout)


if __name__ == "__main__":
    unittest.main()
