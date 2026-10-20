"""PR-mode merge regression tests (PILOT-015).

``towerctl merge --mode pr`` pushes the envelope branch, opens a GitHub pull
request, watches its checks, merges the PR and then fast-forwards the local
base branch.  These tests keep that flow fully offline:

* the "remote" is a throw-away ``git init --bare`` repository under ``%TEMP%``,
  so ``git push`` / ``git fetch`` never touch the network;
* ``gh`` is a small Python stub written into the temporary directory and
  injected through ``TOWERCTL_GH``, so no real GitHub CLI, token or repository
  is involved.

The stub's behaviour is driven by environment variables: ``GH_LOG`` records
every argv, ``GH_CREATE_EXIT`` / ``GH_CHECKS_EXIT`` / ``GH_MERGE_EXIT`` force a
failure and ``GH_SLEEP`` lets the checks step hang so ``--check-timeout`` can
be exercised.  On a successful ``pr merge`` the stub also advances the bare
origin's ``main`` to the envelope head, which gives the follow-up
``fetch`` + ``merge --ff-only`` a real fast-forward to perform.

Each test drives the real CLI through ``subprocess``, exactly as a supervisor
session would, and asserts the observable exit code plus the resulting
envelope, queue and ledger state.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
TASK_ID = "TEST-PR-001"
ENVELOPE_ID = "ENV-TEST-PR-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE_ID}.json"
BASE = "main"
BRANCH = "feature/pr-merge"
FIXED_TIME = "2026-10-19T00:00:00+08:00"
PR_NUMBER = 42
PR_URL = "https://example.invalid/pr/42"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

# The offline ``gh`` stub.  It only implements the three subcommands PR-mode
# merge uses, and every side effect is either the stdout contract of ``gh`` or
# something the test asserts through ``GH_LOG`` / the tower state.
GH_STUB = '''"""Offline ``gh`` stub for test_merge_pr_mode.py."""
import json
import os
import subprocess
import sys
import time


def log_argv(argv):
    path = os.environ.get("GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\\n")


def exit_code(name):
    try:
        return int(os.environ.get(name, "0") or 0)
    except ValueError:
        return 0


def main(argv):
    log_argv(argv)
    if argv[:2] == ["pr", "create"]:
        print(json.dumps({"number": 42,
                          "url": "https://example.invalid/pr/42"}))
        return exit_code("GH_CREATE_EXIT")
    if argv[:2] == ["pr", "checks"]:
        # Sleeping lets the timeout case prove --check-timeout is applied.
        time.sleep(float(os.environ.get("GH_SLEEP", "0") or 0))
        code = exit_code("GH_CHECKS_EXIT")
        if code:
            sys.stderr.write("conclusion: failure\\n")
        return code
    if argv[:2] == ["pr", "merge"]:
        code = exit_code("GH_MERGE_EXIT")
        origin = os.environ.get("GH_ORIGIN")
        sha = os.environ.get("GH_BRANCH_SHA")
        if code == 0 and origin and sha:
            # Advance the bare origin's base branch so the follow-up fetch and
            # ff-only merge have something real to fast-forward to.
            subprocess.run(["git", "--git-dir", origin, "update-ref",
                            "refs/heads/main", sha], check=True,
                           capture_output=True)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class PrMergeTestCase(unittest.TestCase):
    """Fixture: bare origin + working repo + tower root, all under one tmp dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-merge-pr-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "tower"
        self.repo = self.root / "pilot" / "repo"
        self.origin = self.tmp / "origin.git"
        self.stub = self.tmp / "gh_stub.py"
        self.log = self.tmp / "gh-argv.jsonl"
        self.stub.write_text(GH_STUB, encoding="utf-8")
        for directory in ("primary", "supervision/envelopes", "ledger", "tasks"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.write_tower_state()
        self.init_repo()
        self.write_envelope()
        self.write_queue()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers -------------------------------------------------
    def run_git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def commit_all(self, message: str) -> str:
        add = self.run_git("add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        cp = self.run_git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.run_git("rev-parse", "HEAD").stdout.strip()

    def write_tower_state(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "role": "primary",
            "primary": {"id": "ctl-test"},
            "owner": {"name": "mac"},
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-test"},
        })
        (self.root / "ledger" / "supervision.jsonl").write_text("",
                                                                encoding="utf-8")
        # ``envelope_checks`` also gates on the task record, its PASS review
        # and the evidence hash, so the fixture has to be a real verified task.
        evidence_dir = self.root / "tasks" / TASK_ID / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        proof = evidence_dir / "proof.txt"
        proof.write_text("proof of PR-mode merge\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK_ID / "record.json", {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "pr-mode merge",
            "status": "closed",
            "executor": "exec-test",
            "review": {"reviewer": "rev-test", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK_ID}/evidence/proof.txt",
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "bytes": proof.stat().st_size,
                "at": FIXED_TIME,
            }],
        })

    def init_repo(self) -> None:
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        self.repo.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.run_git("init").returncode, 0)
        self.assertEqual(
            self.run_git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        tests_dir = self.repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_smoke.py").write_text(
            "import unittest\n\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        self.base_head = self.commit_all("base")
        self.assertEqual(self.run_git("checkout", "-b", BRANCH).returncode, 0)
        (self.repo / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.repo / ENVELOPE_PATH, {"envelope_id": ENVELOPE_ID})
        self.envelope_head = self.commit_all("envelope")
        self.assertEqual(self.run_git("checkout", BASE).returncode, 0)
        # Forward slashes keep the local-path remote portable on Windows.
        remote = str(self.origin).replace("\\", "/")
        self.assertEqual(
            self.run_git("remote", "add", "origin", remote).returncode, 0)

    def write_envelope(self, status: str = "DRAFT") -> None:
        write_json(self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json", {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE_ID,
            "task": TASK_ID,
            "repository": "pilot/repo",
            "branch": BRANCH,
            "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head,
            "status": status,
        })

    def write_queue(self, status: str = "WAITING") -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": ENVELOPE_ID,
                "task": TASK_ID,
                "branch": BRANCH,
                "base": BASE,
                "status": status,
                "added_at": FIXED_TIME,
            }],
            "updated_at": FIXED_TIME,
        })

    # -- CLI / state accessors -------------------------------------------
    def run_merge(self, *args: str, env_extra: dict | None = None,
                  timeout: float | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        for name in [name for name in env if name.startswith("GH_")]:
            env.pop(name)
        env.update(GIT_IDENTITY)
        env.update({
            "TOWERCTL_GH": f"{sys.executable} {self.stub}",
            "GH_LOG": str(self.log),
            "GH_ORIGIN": str(self.origin).replace("\\", "/"),
            "GH_BRANCH_SHA": self.envelope_head,
        })
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root),
             "merge", "--envelope", ENVELOPE_ID, "--role", "supervisor",
             "--supervisor", "sup-x", *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=timeout,
        )

    def envelope(self) -> dict:
        path = self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def queue_entry(self) -> dict:
        path = self.root / "supervision" / "MERGE_QUEUE.json"
        queue = json.loads(path.read_text(encoding="utf-8"))
        return next(e for e in queue["entries"] if e["envelope_id"] == ENVELOPE_ID)

    def ledger_events(self, event_type: str | None = None) -> list[dict]:
        path = self.root / "ledger" / "supervision.jsonl"
        if not path.exists():
            return []
        events = [json.loads(line) for line in
                  path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if event_type is not None:
            events = [e for e in events if e.get("type") == event_type]
        return events

    def merge_ledger(self) -> list[dict]:
        path = self.root / "supervision" / "registries" / "merge-ledger.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("entries", [])

    def gh_calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in
                self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def head(self) -> str:
        return self.run_git("rev-parse", "HEAD").stdout.strip()

    # -- 1. happy path -----------------------------------------------------
    def test_pr_mode_merges_and_records_pr_metadata(self) -> None:
        cp = self.run_merge("--mode", "pr", timeout=120)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "MERGED")

        envelope = self.envelope()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_mode"], "pr")
        self.assertEqual(envelope["pr_number"], PR_NUMBER)
        self.assertEqual(envelope["pr_url"], PR_URL)
        self.assertEqual(envelope["check_conclusion"], "success")
        self.assertEqual(envelope["supervisor"], "sup-x")
        self.assertIn("merged_at", envelope)
        # The merge commit is the fast-forwarded envelope head.
        self.assertEqual(envelope["merge_commit"], self.envelope_head)
        self.assertEqual(self.head(), self.envelope_head)

        entry = self.queue_entry()
        self.assertEqual(entry["status"], "MERGED")
        self.assertEqual(entry["merge_commit"], self.envelope_head)

        calls = self.gh_calls()
        self.assertEqual([call[:2] for call in calls],
                         [["pr", "create"], ["pr", "checks"], ["pr", "merge"]])
        create = calls[0]
        self.assertIn("--base", create)
        self.assertEqual(create[create.index("--base") + 1], BASE)
        self.assertIn("--head", create)
        self.assertEqual(create[create.index("--head") + 1], BRANCH)
        self.assertIn(f"merge: {TASK_ID} ({ENVELOPE_ID})", create)
        self.assertEqual(create[create.index("--json") + 1], "number,url")
        checks = calls[1]
        self.assertIn(str(PR_NUMBER), checks)
        self.assertIn("--watch", checks)
        self.assertIn("--fail-fast", checks)
        self.assertIn("--merge", calls[2])

        records = self.merge_ledger()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["merge_mode"], "pr")
        self.assertEqual(record["pr_number"], PR_NUMBER)
        self.assertEqual(record["pr_url"], PR_URL)
        self.assertEqual(record["merge_commit"], self.envelope_head)

        merges = self.ledger_events("MERGE")
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["payload"]["merge_mode"], "pr")
        self.assertEqual(merges[0]["payload"]["pr_number"], PR_NUMBER)
        self.assertEqual(merges[0]["payload"]["pr_url"], PR_URL)
        # A fast-forward leaves exactly one parent; a local --no-ff merge would
        # leave two, so this pins the PR path to step 5.
        parents = self.run_git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
        self.assertEqual(len(parents), 2, parents)

    # -- 2. failing checks block the merge without merging -----------------
    def test_failing_checks_block_with_correction_required(self) -> None:
        cp = self.run_merge("--mode", "pr", env_extra={"GH_CHECKS_EXIT": "1"},
                            timeout=120)
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("checks", payload["errors"][0])

        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertNotIn("merge_commit", envelope)
        self.assertNotEqual(envelope["status"], "MERGED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")

        blocked = self.ledger_events("MERGE_BLOCKED")
        self.assertEqual(len(blocked), 1, blocked)
        self.assertEqual(blocked[0]["payload"]["phase"], "checks")
        self.assertEqual(blocked[0]["payload"]["reason"], "checks")
        self.assertIn("failure", blocked[0]["payload"]["detail"].lower())
        self.assertFalse(self.ledger_events("MERGE"))
        self.assertFalse(self.merge_ledger())
        self.assertEqual([call[:2] for call in self.gh_calls()],
                         [["pr", "create"], ["pr", "checks"]])

    # -- 3. a hung checks gate hits --check-timeout ------------------------
    def test_check_timeout_blocks_with_timeout_reason(self) -> None:
        started = time.monotonic()
        cp = self.run_merge("--mode", "pr", "--check-timeout", "1",
                            env_extra={"GH_SLEEP": "5"}, timeout=120)
        elapsed = time.monotonic() - started
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertLess(elapsed, 30, "the 1s check timeout was not enforced")

        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")

        blocked = self.ledger_events("MERGE_BLOCKED")
        self.assertEqual(len(blocked), 1, blocked)
        self.assertEqual(blocked[0]["payload"]["phase"], "checks")
        self.assertEqual(blocked[0]["payload"]["reason"], "timeout")
        self.assertIn("checks", blocked[0]["payload"]["detail"].lower())
        # The gate must not have merged anything after the timeout.
        self.assertEqual([call[:2] for call in self.gh_calls()],
                         [["pr", "create"], ["pr", "checks"]])

    # -- 4. a failed push aborts before any PR exists ----------------------
    def test_push_failure_blocks_without_touching_gh(self) -> None:
        self.assertEqual(self.run_git("remote", "remove", "origin").returncode, 0)
        cp = self.run_merge("--mode", "pr", timeout=120)
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")

        envelope = self.envelope()
        self.assertEqual(envelope["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        blocked = self.ledger_events("MERGE_BLOCKED")
        self.assertEqual(len(blocked), 1, blocked)
        self.assertEqual(blocked[0]["payload"]["phase"], "push")
        self.assertEqual(self.gh_calls(), [])

    # -- 5. a missing gh executable is a clean gate failure ----------------
    def test_missing_gh_executable_fails_with_hint(self) -> None:
        missing = self.tmp / "no-such-gh-binary"
        cp = self.run_merge("--mode", "pr",
                            env_extra={"TOWERCTL_GH": str(missing)}, timeout=120)
        self.assertEqual(cp.returncode, 2, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = (cp.stdout + cp.stderr).lower()
        self.assertIn("gh", blob)
        self.assertIn("gh not found", blob)
        self.assertIn("towerctl_gh", blob)

        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.gh_calls(), [])
        self.assertFalse(self.ledger_events("MERGE"))

    # -- 6. local mode still takes the original code path ------------------
    def test_local_mode_keeps_local_merge(self) -> None:
        cp = self.run_merge("--mode", "local", timeout=120)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")

        envelope = self.envelope()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_mode"], "local")
        self.assertNotIn("pr_number", envelope)
        self.assertNotIn("pr_url", envelope)
        self.assertEqual(self.queue_entry()["status"], "MERGED")
        # No gh invocation, and a real merge commit with two parents.
        self.assertEqual(self.gh_calls(), [])
        parents = self.run_git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
        self.assertEqual(len(parents), 3, parents)

    # -- 7. --mode defaults to local ---------------------------------------
    def test_mode_defaults_to_local(self) -> None:
        cp = self.run_merge(timeout=120)
        self.assertEqual(cp.returncode, 0, msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        envelope = self.envelope()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_mode"], "local")
        self.assertEqual(self.queue_entry()["status"], "MERGED")
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main()
