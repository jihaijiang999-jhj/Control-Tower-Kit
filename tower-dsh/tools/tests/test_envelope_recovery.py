"""Regression tests for the PILOT-053 envelope-recovery contract.

The 052 failure: a PR merge was blocked on CI, leaving the envelope
``CORRECTION_REQUIRED``.  Re-running ``envelope-new`` folded the envelope back
to ``DRAFT``; the queue already held its ``QUEUE_ADD`` so ``queue-add`` refused
a retry; the second ``MERGE_START`` therefore replayed from ``DRAFT`` and
``state-verify`` reported ``illegal_transition`` (which also failed the
``PROFILE-TOWER-DSH`` STATE probe).

These tests pin the three halves of the fix:

* replay: a repeated ``ENVELOPE_NEW`` keeps ``WAITING`` / ``CORRECTION_REQUIRED``
  / ``MERGED`` instead of resetting to ``DRAFT``;
* ``envelope-new``: preserves an in-flight status and refuses to reopen a
  merged envelope (``queue-add`` deliberately leaves the file status alone, so
  the normal first merge still starts from ``DRAFT`` + ``WAITING``);
* ``merge``: refuses a ``DRAFT`` that a *re-envelope* reset, before any
  ``MERGE_START`` and before any ledger write, while the first ``DRAFT``
  envelope with a ``WAITING`` queue keeps merging.

Each test builds an isolated tower root with a real throw-away git repository
under the runner sandbox (see ``tools/run_tests.py``) and drives the CLI through
``subprocess``, exactly as a supervisor session would.  The PR-mode failure uses
an offline ``gh`` stub, so no network or real GitHub CLI is involved.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import towerctl  # noqa: E402  (needs TOOLS_DIR on sys.path)

TCLI = TOOLS_DIR / "towerctl.py"
TOWER_NAME = "tower-dsh"
TASK = "TEST-ENV-001"
ENVELOPE = "ENV-TEST-ENV-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BASE = "main"
BRANCH = "feature/envelope-recovery"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

# Offline ``gh`` stub for the failing-PR half of the recovery test: auth is
# green, a PR can be opened, and the CI checks fail.  ``pr merge`` is never
# reached, so it must not be stubbed as green.
GH_STUB = '''"""Offline ``gh`` stub for test_envelope_recovery.py."""
import sys

argv = sys.argv[1:]
if argv[:2] == ["auth", "status"]:
    raise SystemExit(0)
if argv[:2] == ["pr", "create"]:
    print("https://example.invalid/pull/7")
    raise SystemExit(0)
if argv[:2] == ["pr", "checks"]:
    print("tower gate\\tfail\\t1\\thttps://example.invalid/run/1")
    raise SystemExit(1)
raise SystemExit(0)
'''


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class EnvelopeRecoveryTestCase(unittest.TestCase):
    """Fixture: bare origin + kit repo (tower root nested) + envelope source."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-envelope-recovery-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / TOWER_NAME
        self.origin = self.tmp / "origin.git"
        self.stub = self.tmp / "gh_stub.py"
        self.gh_log = self.tmp / "gh-argv.jsonl"
        self.stub.write_text(GH_STUB, encoding="utf-8")
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{TASK}", "incoming"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.write_static_tower_files()
        self.init_repo()
        self.write_envelope_source()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(self.kit), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def commit(self, message: str) -> str:
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write_static_tower_files(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": TOWER_NAME,
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": "ctl-test"},
            "owner": {"name": "mac"},
            "next_action": "test",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "tower_id": TOWER_NAME,
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-test"},
        })
        write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [],
        })
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("envelope recovery proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1",
            "id": TASK,
            "title": "envelope recovery regression",
            "status": "closed",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK}/evidence/proof.txt",
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "bytes": proof.stat().st_size,
            }],
        })
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.git("init").returncode, 0)
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.assertEqual(self.git("add", "README.md").returncode, 0)
        self.commit("base")
        self.assertEqual(self.git("checkout", "-b", BRANCH).returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.assertEqual(self.git("add", "feature.txt").returncode, 0)
        self.implementation_head = self.commit("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.assertEqual(self.git("add", ENVELOPE_PATH).returncode, 0)
        self.envelope_head = self.commit("envelope")
        self.assertEqual(self.git("checkout", BASE).returncode, 0)
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        remote = str(self.origin).replace("\\", "/")
        self.assertEqual(
            self.git("remote", "add", "origin", remote).returncode, 0)

    def write_envelope_source(self) -> None:
        write_json(self.root / "incoming" / f"{ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE,
            "task": TASK,
            "repository": "..",  # the verified kit repo is the tower root's parent
            "branch": BRANCH,
            "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1,
            "tower_tests_baseline": 1,
        })

    # -- CLI / state accessors -------------------------------------------
    def run_cli(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["TOWERCTL_GH"] = f"{sys.executable} {self.stub}"
        env["GH_LOG"] = str(self.gh_log)
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=timeout,
        )

    def envelope_new(self) -> subprocess.CompletedProcess:
        return self.run_cli("envelope-new", "--task", TASK,
                            "--file", str(self.root / "incoming"
                                          / f"{ENVELOPE}.json"))

    def queue_add(self) -> subprocess.CompletedProcess:
        return self.run_cli("queue-add", "--envelope", ENVELOPE)

    def merge(self, *args: str) -> subprocess.CompletedProcess:
        return self.run_cli("merge", "--envelope", ENVELOPE,
                            "--role", "supervisor", "--supervisor", "sup-test",
                            *args)

    def state_verify(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.run_cli("state-verify")
        return cp, json.loads(cp.stdout)

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"

    def envelope(self) -> dict:
        return read_json(self.envelope_path())

    def queue_entry(self) -> dict:
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        return next(e for e in queue["entries"] if e["envelope_id"] == ENVELOPE)

    def ledger_text(self) -> str:
        return (self.root / "ledger" / "supervision.jsonl").read_text(
            encoding="utf-8")

    def ledger_events(self, event_type: str | None = None) -> list[dict]:
        events = [json.loads(line) for line in self.ledger_text().splitlines()
                  if line.strip()]
        if event_type is not None:
            events = [e for e in events if e.get("type") == event_type]
        return events

    def write_envelope_status(self, status: str) -> None:
        envelope = self.envelope()
        envelope["status"] = status
        write_json(self.envelope_path(), envelope)

    # -- 1. normal first merge must not regress ---------------------------
    def test_first_envelope_merges_from_draft_and_waiting_queue(self) -> None:
        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "DRAFT")

        cp = self.queue_add()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        # PILOT-053 deviation: ``queue-add`` does not rewrite the envelope
        # status; the first envelope stays DRAFT until it merges.
        self.assertEqual(self.envelope()["status"], "DRAFT")

        cp = self.merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(self.queue_entry()["status"], "MERGED")

        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

    # -- 2. failure -> re-envelope -> second merge ------------------------
    def test_failed_merge_keeps_correction_after_reenvelope_and_merges(self) -> None:
        self.assertEqual(self.envelope_new().returncode, 0)
        self.assertEqual(self.queue_add().returncode, 0)

        failed = self.merge("--mode", "pr", "--check-timeout", "10",
                            "--check-interval", "1")
        self.assertEqual(failed.returncode, 2,
                         msg=failed.stdout + failed.stderr)
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.queue_entry()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(len(self.ledger_events("MERGE_BLOCKED")), 1)
        self.assertEqual(self.ledger_events("MERGE"), [])

        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

        # Re-envelope after the correction: the status must be preserved.
        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")
        self.assertEqual(len(self.ledger_events("ENVELOPE_NEW")), 2)

        # The corrected envelope retries through the same queue entry.
        cp = self.merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(self.queue_entry()["status"], "MERGED")

        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

    # -- 3. a DRAFT lost by a re-envelope is refused before MERGE_START ---
    def test_reenvelope_draft_is_refused_before_merge_start(self) -> None:
        self.assertEqual(self.envelope_new().returncode, 0)
        self.assertEqual(self.queue_add().returncode, 0)
        failed = self.merge("--mode", "pr", "--check-timeout", "10",
                            "--check-interval", "1")
        self.assertEqual(failed.returncode, 2, msg=failed.stdout + failed.stderr)
        self.assertEqual(self.envelope_new().returncode, 0)
        # Construct the old-code failure: the re-envelope wrote DRAFT again.
        self.write_envelope_status("DRAFT")
        ledger_before = self.ledger_text()
        starts_before = len(self.ledger_events("MERGE_START"))

        cp = self.merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("DRAFT", json.dumps(payload))
        self.assertIn("re-envelope", json.dumps(payload))
        self.assertEqual(len(self.ledger_events("MERGE_START")), starts_before)
        self.assertEqual(self.ledger_text(), ledger_before)
        self.assertEqual(self.envelope()["status"], "DRAFT")

    def test_first_draft_envelope_without_queue_is_refused(self) -> None:
        self.assertEqual(self.envelope_new().returncode, 0)
        cp = self.merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("not queued", cp.stdout)
        self.assertEqual(self.ledger_events("MERGE_START"), [])

    # -- 4. a merged envelope cannot be reopened --------------------------
    def test_merged_envelope_cannot_be_reenveloped(self) -> None:
        self.assertEqual(self.envelope_new().returncode, 0)
        self.assertEqual(self.queue_add().returncode, 0)
        self.assertEqual(self.merge().returncode, 0)
        self.assertEqual(self.envelope()["status"], "MERGED")
        ledger_before = self.ledger_text()
        envelope_before = self.envelope()

        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("cannot be reopened", cp.stdout)
        self.assertEqual(self.ledger_text(), ledger_before)
        self.assertEqual(self.envelope(), envelope_before)
        self.assertEqual(len(self.ledger_events("ENVELOPE_NEW")), 1)

    # -- 5. a WAITING envelope keeps WAITING across a re-envelope ---------
    def test_waiting_envelope_keeps_waiting_across_reenvelope(self) -> None:
        self.assertEqual(self.envelope_new().returncode, 0)
        self.assertEqual(self.queue_add().returncode, 0)
        # Construct the queued status a tower may already hold (052's fold
        # reaches it before the failed merge).
        self.write_envelope_status("WAITING")

        cp = self.envelope_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "WAITING")
        self.assertEqual(len(self.ledger_events("ENVELOPE_NEW")), 2)

        cp = self.merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "MERGED")
        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload["drift"], [])

    # -- 6. replay unit: repeated ENVELOPE_NEW preserves the fold ---------
    def test_replay_preserves_statuses_across_repeated_envelope_new(self) -> None:
        rows = [
            ("ENV-WAIT", "ENVELOPE_NEW"),
            ("ENV-WAIT", "QUEUE_ADD"),
            ("ENV-WAIT", "ENVELOPE_NEW"),
            ("ENV-CORR", "ENVELOPE_NEW"),
            ("ENV-CORR", "QUEUE_ADD"),
            ("ENV-CORR", "MERGE_START"),
            ("ENV-CORR", "MERGE_BLOCKED"),
            ("ENV-CORR", "ENVELOPE_NEW"),
            ("ENV-MERGED", "ENVELOPE_NEW"),
            ("ENV-MERGED", "QUEUE_ADD"),
            ("ENV-MERGED", "MERGE_START"),
            ("ENV-MERGED", "MERGE"),
            ("ENV-MERGED", "ENVELOPE_NEW"),
            ("ENV-NEW", "ENVELOPE_NEW"),
            ("ENV-UNKNOWN", "ENVELOPE_NEW"),
            ("ENV-UNKNOWN", "NOT_A_LIFECYCLE_EVENT"),
        ]
        ledger = self.root / "ledger" / "supervision.jsonl"
        ledger.write_text("".join(
            json.dumps({"seq": index, "type": event_type,
                        "payload": {"envelope": envelope}})
            + "\n"
            for index, (envelope, event_type) in enumerate(rows, 1)),
            encoding="utf-8")

        states = towerctl.replay_envelope_statuses(self.root)
        self.assertEqual(states, {
            "ENV-WAIT": "WAITING",
            "ENV-CORR": "CORRECTION_REQUIRED",
            "ENV-MERGED": "MERGED",
            "ENV-NEW": "DRAFT",
            "ENV-UNKNOWN": "DRAFT",
        })

        transitions: list[dict] = []
        towerctl.replay_envelope_statuses(self.root, transitions)
        illegal = [row for row in transitions if row["kind"] == "illegal_transition"]
        self.assertEqual([row["target"] for row in illegal], ["ENV-MERGED"])
        self.assertEqual(illegal[0]["event"], "ENVELOPE_NEW")

    # -- 7. the real tower history must replay clean ----------------------
    def test_real_tower_history_has_no_envelope_drift(self) -> None:
        cp = subprocess.run(
            [sys.executable, "-B", str(TCLI), "state-verify"],
            cwd=str(TOWER_ROOT), capture_output=True, text=True,
            encoding="utf-8",
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["drift"], [])
        # 052's second MERGE_START used to replay from DRAFT.
        illegal = [row for row in payload["drift"]
                   if row.get("kind") == "illegal_transition"]
        self.assertEqual(illegal, [])


if __name__ == "__main__":
    unittest.main()
