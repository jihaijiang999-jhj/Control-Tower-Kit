"""PILOT-040: a 0-event supervision ledger cannot shield envelope/queue history.

PILOT-036 made an *existing* empty ledger a valid empty chain.  PILOT-039 made a
**missing** ledger fatal at the merge precondition.  The seam left open was
truncation: ``truncate -s0 ledger/supervision.jsonl`` keeps the file, so 039's
presence check passes, and a hand-written legacy envelope plus its queue row
then merged without a single supervision event.  ``state-verify`` already
reported exactly that fixture as ``envelope_unbacked`` / ``queue_unbacked`` --
the auditor saw it, the merge gate did not.

PILOT-040 adds ``ledger_empty_guard``:

* it applies only to non-legacy towers (a tower without authority state keeps
  the old 036/039 behaviour, including successful legacy merges);
* it fires when ``ledger/supervision.jsonl`` exists with zero events **and** at
  least one supervision artifact exists (an envelope file, non-empty
  ``MERGE_QUEUE.json`` entries, or non-empty ``registries/merge-ledger.json``
  entries);
* a fresh tower -- configured/required but with no supervision artifact -- still
  passes, because it has no history to be inconsistent with;
* ``merge`` fails closed before reading the envelope/queue/git and leaves the
  queue, the envelope and the 0-byte ledger untouched (no MERGE_START/MERGING);
* ``merge-check`` reports one failure-only item (``ledger history present``).

The same module pins the PILOT-040 ``authority-require`` echo fix: when the
marker already exists (``already=true``) or one half is repaired
(``repaired=true``), the output echoes the *persisted* decision, not the
requested ``--decision``; a differing request is reported as
``requested_decision`` while policy bytes, the event payload and the event
count do not change.

Every test builds a throw-away kit (a git repository with a tower inside) under
``tempfile`` and drives the real CLI in a subprocess, like the 037/038/039
suites.

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
TASK = "T-EMPTY-040"
ENVELOPE = "ENV-EMPTY-040"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/empty-ledger-040"
FIXED_TIME = "2026-10-23T00:00:00+08:00"
AUTHORITY_FILE = "state/AUTHORITY.json"
POLICY_FILE = "shared/AUTHORITY_POLICY.json"
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"
GUARD_TEXT = "supervision ledger is empty but envelope/queue history exists"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


class EmptyLedgerGuardTestCase(unittest.TestCase):
    """A tower with one primary, one supervision state and a merge branch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-empty-ledger-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("primary", "supervision/envelopes",
                          "supervision/registries", "ledger", "shared", "state",
                          f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1",
            "id": TASK,
            "title": "empty ledger guard",
            "status": "accepted",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK}/evidence/proof.txt",
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "bytes": proof.stat().st_size,
                "at": FIXED_TIME,
            }],
        })
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": PRIMARY_ID},
            "owner": {"name": "mac"},
            "next_action": "test",
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": SUPERVISOR_ID},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.init_repo()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixtures --------------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        return run_git(self.kit, *args)

    def commit_all(self, message: str) -> str:
        add = self.git("add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        commit = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.git("init").returncode, 0)
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / "merge-envelopes").mkdir()
        self.commit_all("base")
        self.assertEqual(self.git("checkout", "-b", BRANCH).returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.envelope_head = self.commit_all("envelope")
        self.assertEqual(self.git("checkout", "main").returncode, 0)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def cli_json(self, *args: str) -> dict:
        cp = self.run_cli(*args)
        try:
            return json.loads(cp.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
            self.fail(f"{args} emitted non-JSON stdout={cp.stdout!r} "
                      f"stderr={cp.stderr!r}: {exc}")

    def configure(self, decision: str = "D-ORIG") -> None:
        cp = self.run_cli("authority-set", "--supervisor", SUPERVISOR_ID,
                          "--decision", decision, "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def require(self, decision: str = "D-ORIG") -> dict:
        cp = self.run_cli("authority-require", "--by", "mac",
                          "--decision", decision)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def write_envelope(self) -> None:
        """The leg*acy* fixture: a hand-written envelope with no lifecycle row.

        ``envelope_new``/``queue_add`` are deliberately bypassed, which is the
        whole point: the files exist, the supervision ledger does not record
        them.
        """
        write_json(self.root / "supervision" / "envelopes" /
                   f"{ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE,
            "task": TASK,
            "repository": "..",
            "branch": BRANCH,
            "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head,
            "status": "DRAFT",
        })

    def write_waiting_entry(self) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": "main",
                         "status": "WAITING", "added_at": FIXED_TIME}],
        })

    def write_truncated_fixture(self) -> None:
        """configured/required tower + envelope + queue + 0-byte ledger."""
        self.write_envelope()
        self.write_waiting_entry()
        self.assertEqual(self.supervision_ledger_path().stat().st_size, 0,
                         msg="fixture must start from a 0-byte supervision ledger")

    def seed_supervision_event(self, event_type: str = "QUEUE_ADD") -> dict:
        return towerctl.append_supervision_ledger(
            self.root, event_type, "primary",
            {"envelope": ENVELOPE, "task": TASK,
             "branch": BRANCH, "head": self.envelope_head})

    def supervision_ledger_path(self) -> Path:
        return self.root / "ledger" / "supervision.jsonl"

    def supervision_ledger_bytes(self) -> bytes:
        return self.supervision_ledger_path().read_bytes()

    def queue_bytes(self) -> bytes:
        return (self.root / "supervision" / "MERGE_QUEUE.json").read_bytes()

    def queue_entry(self) -> dict:
        return read_json(
            self.root / "supervision" / "MERGE_QUEUE.json")["entries"][0]

    def policy_bytes(self) -> bytes:
        return (self.root / POLICY_FILE).read_bytes()

    def primary_ledger_bytes(self) -> bytes:
        return (self.root / "ledger" / "primary.jsonl").read_bytes()

    def primary_events(self) -> list[dict]:
        path = self.root / "ledger" / "primary.jsonl"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def required_events(self) -> list[dict]:
        return [event for event in self.primary_events()
                if event.get("type") == "AUTHORITY_REQUIRED"]

    def find_check(self, checks: list[dict], needle: str) -> dict:
        for check in checks:
            if needle in check["name"]:
                return check
        self.fail(f"no check containing {needle!r} in {checks}")

    def assert_merge_refused_by_guard(self) -> dict:
        """``merge`` exits 2 at the guard, before any state is touched."""
        envelope_before = (self.root / "supervision" / "envelopes"
                           / f"{ENVELOPE}.json").read_bytes()
        queue_before = self.queue_bytes()
        ledger_before = self.supervision_ledger_bytes()

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        blob = json.dumps(payload["errors"])
        self.assertIn(GUARD_TEXT, blob)
        # Nothing downstream of the guard may have run.
        self.assertEqual(self.queue_bytes(), queue_before,
                         msg="a refused merge must not touch the queue")
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        self.assertEqual(self.supervision_ledger_bytes(), ledger_before,
                         msg="a refused merge must not rewrite the 0-byte ledger")
        self.assertEqual(ledger_before, b"",
                         msg="the fixture ledger must stay a 0-byte empty chain")
        self.assertEqual(
            (self.root / "supervision" / "envelopes"
             / f"{ENVELOPE}.json").read_bytes(), envelope_before)
        self.assertNotIn(b"MERGE_START", self.supervision_ledger_bytes())
        self.assertNotIn(b"MERGING", self.supervision_ledger_bytes())
        return payload

    def assert_merge_check_refused_by_guard(self) -> dict:
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        check = self.find_check(payload["errors"], "ledger history present")
        self.assertFalse(check["ok"], check)
        self.assertIn(GUARD_TEXT, check["detail"])
        return payload

    # -- 1. configured tower ---------------------------------------------
    def test_configured_empty_ledger_with_artifacts_blocks_merge(self) -> None:
        self.configure()
        self.write_truncated_fixture()

        self.assert_merge_check_refused_by_guard()
        self.assert_merge_refused_by_guard()

        # The queue row and the 0-byte ledger survive both refusals verbatim.
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        self.assertEqual(self.supervision_ledger_bytes(), b"")
        self.assertFalse(
            (self.root / "supervision" / "registries"
             / "merge-ledger.json").exists(),
            msg="a refused merge must not write a merge-ledger entry")

    # -- 2. required tower -----------------------------------------------
    def test_required_empty_ledger_with_artifacts_blocks_merge(self) -> None:
        self.configure()
        out = self.require()
        self.assertTrue(out["repaired"], out)
        self.assertEqual(self.cli_json("authority-check")["status"],
                         "configured")
        self.write_truncated_fixture()

        check = self.assert_merge_check_refused_by_guard()
        # The requirement check itself still passes: the tower is required and
        # pinned, only its supervision history is missing.
        merged = self.cli_json("authority-check")
        self.assertTrue(merged["ok"], merged)
        self.assertEqual(merged["requirement"], "required")
        self.assert_merge_refused_by_guard()
        self.assertEqual(self.supervision_ledger_bytes(), b"")
        self.assertIn("ledger history present",
                      [item["name"] for item in check["errors"]])

    # -- 3. legacy tower keeps the old behaviour --------------------------
    def test_legacy_tower_with_empty_ledger_still_merges(self) -> None:
        # No authority state: the guard must not touch a legacy tower, so the
        # exact same fixture that fails on a configured tower still merges.
        self.assertEqual(self.cli_json("authority-check")["status"], "legacy")
        self.write_envelope()
        self.write_waiting_entry()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertNotIn("ledger history present",
                         [item["name"] for item in payload["checks"]])

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        merged = json.loads(cp.stdout)
        self.assertTrue(merged["ok"], merged)
        self.assertEqual(merged["status"], "MERGED")
        self.assertEqual(self.queue_entry()["status"], "MERGED")
        # The merge itself wrote supervision history: the ledger is no longer an
        # empty chain afterwards.
        self.assertIn("MERGE_START", self.supervision_ledger_bytes().decode())

    # -- 4. a fresh tower has no history to lose --------------------------
    def test_fresh_configured_tower_without_artifacts_passes_guard(self) -> None:
        self.configure()
        # Direct guard probe: configured tower, 0-byte supervision ledger and
        # no envelope/queue/merge-ledger artifact is a legal empty chain (036).
        self.assertEqual(towerctl.ledger_empty_guard(self.root), [])
        self.assertEqual(self.supervision_ledger_bytes(), b"")

        # ``merge`` reaches the missing envelope instead of failing on the
        # ledger: the guard did not fire.
        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = json.dumps(json.loads(cp.stdout)["errors"])
        self.assertIn("envelope not found", blob)
        self.assertNotIn(GUARD_TEXT, blob)
        self.assertEqual(self.supervision_ledger_bytes(), b"")

        # And once the ledger records the artifact, the guard stays quiet.
        self.write_envelope()
        self.seed_supervision_event("ENVELOPE_NEW")
        self.assertEqual(towerctl.ledger_empty_guard(self.root), [])

    # -- 5. the auditor saw it first --------------------------------------
    def test_state_verify_reports_unbacked_artifacts_on_empty_ledger(self) -> None:
        self.configure()
        self.write_truncated_fixture()

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        kinds = {item["kind"] for item in payload["drift"]}
        self.assertIn("queue_unbacked", kinds)
        self.assertIn("envelope_unbacked", kinds)
        self.assertEqual({item["target"] for item in payload["drift"]
                          if item["kind"] in ("queue_unbacked",
                                              "envelope_unbacked")},
                         {ENVELOPE})
        # Read-only audit: it neither repairs the artifacts nor appends events.
        self.assertEqual(self.supervision_ledger_bytes(), b"")
        self.assertEqual(self.queue_entry()["status"], "WAITING")

    # -- 6. authority-require echoes the persisted decision ----------------
    def test_require_already_echoes_persisted_decision(self) -> None:
        self.configure()
        first = self.require(decision="D-ORIG")
        self.assertTrue(first["repaired"], first)
        policy_before = self.policy_bytes()
        ledger_before = self.primary_ledger_bytes()

        out = self.require(decision="D-NEW")

        self.assertTrue(out["ok"], out)
        self.assertTrue(out["already"], out)
        self.assertFalse(out["repaired"], out)
        # The request did not overwrite the authority: echo the persisted value
        # and report the ignored request alongside it.
        self.assertEqual(out["decision"], "D-ORIG")
        self.assertEqual(out["requested_decision"], "D-NEW")
        self.assertEqual(len(self.required_events()), 1)
        self.assertEqual(self.policy_bytes(), policy_before,
                         msg="an idempotent require must not rewrite the policy")
        self.assertEqual(self.primary_ledger_bytes(), ledger_before,
                         msg="an idempotent require must not append an event")
        self.assertEqual(read_json(self.root / POLICY_FILE)["decision"],
                         "D-ORIG")

    def test_require_repair_echoes_persisted_decision(self) -> None:
        self.configure()
        self.require(decision="D-ORIG")
        events_before = [event["payload"] for event in self.required_events()]

        # Repair the missing file half from the authoritative event.  The
        # requested decision must not replace the one the ledger pinned.
        (self.root / POLICY_FILE).unlink()
        out = self.require(decision="D-NEW")

        self.assertTrue(out["repaired"], out)
        self.assertFalse(out["already"], out)
        self.assertEqual(out["decision"], "D-ORIG")
        self.assertEqual(out["requested_decision"], "D-NEW")
        self.assertEqual(read_json(self.root / POLICY_FILE)["decision"],
                         "D-ORIG")
        self.assertEqual(
            [event["payload"] for event in self.required_events()],
            events_before,
            msg="repairing the policy half must not rewrite the event")

        # Repair the divergent both-halves case the same way: the event is the
        # authority, the request is only echoed.
        policy = read_json(self.root / POLICY_FILE)
        policy["decision"] = "D-OTHER"
        write_json(self.root / POLICY_FILE, policy)
        self.assertEqual(
            [item["kind"] for item in self.cli_json("state-verify")["drift"]],
            ["authority_policy_mismatch"])
        out = self.require(decision="D-SECOND")

        self.assertTrue(out["repaired"], out)
        self.assertEqual(out["decision"], "D-ORIG")
        self.assertEqual(out["requested_decision"], "D-SECOND")
        self.assertEqual(read_json(self.root / POLICY_FILE)["decision"],
                         "D-ORIG")
        self.assertEqual(len(self.required_events()), 1)
        self.assertTrue(self.cli_json("authority-check")["ok"])
        self.assertEqual(self.cli_json("state-verify")["drift"], [])

    # -- 7. the guard is driven by real history, not file size alone ------
    def test_non_empty_supervision_ledger_is_never_guarded(self) -> None:
        self.configure()
        self.write_waiting_entry()
        self.seed_supervision_event("QUEUE_ADD")
        self.assertTrue(self.supervision_ledger_bytes())

        self.assertEqual(towerctl.ledger_empty_guard(self.root), [])

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        # Fails on the missing envelope, never on the ledger-history guard.
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = cp.stdout + cp.stderr
        self.assertIn("envelope not found", blob)
        self.assertNotIn(GUARD_TEXT, blob)


if __name__ == "__main__":
    unittest.main()
