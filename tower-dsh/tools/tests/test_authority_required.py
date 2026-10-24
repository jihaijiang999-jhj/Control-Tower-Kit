"""PILOT-038: the persisted "this tower requires authority" marker.

``shared/AUTHORITY_POLICY.json`` (``tower/authority-policy@1``) plus one
``AUTHORITY_REQUIRED`` event are the marker.  Its whole point is that the 037
authority gate cannot be escaped by deleting ``state/AUTHORITY.json`` and
truncating the trailing ``AUTHORITY_SET`` row: a required tower whose authority
state is gone is ``required_unconfigured`` (exit 2), never legacy.  The two
halves of the marker must also exist together -- policy without event is
``authority policy unbacked``, event without policy is ``authority policy
missing``.

``authority-require`` is the only writer of the marker: it refuses a caller
that is not the registered owner (zero writes), is idempotent when both halves
exist, and repairs a half-written tower.  A ledger that cannot be appended to
must exit 2 with one JSON payload and no traceback, leaving the half-write
visible (fail closed) instead of making a write failure look authoritative.

Every test builds a throw-away kit (a git repository with a tower inside) under
``tempfile`` and drives the real CLI in a subprocess.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
TASK = "T-AUTH-001"
ENVELOPE = "ENV-AUTH-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/authority"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
AUTHORITY_FILE = "state/AUTHORITY.json"
POLICY_FILE = "shared/AUTHORITY_POLICY.json"
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"
POLICY_SCHEMA = "tower/authority-policy@1"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


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


class AuthorityRequiredTestCase(unittest.TestCase):
    """A tower with one primary, one supervision state and a merge branch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-authority-required-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger",
                          "shared", f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1",
            "id": TASK,
            "title": "authority required",
            "status": "accepted",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK}/evidence/proof.txt",
                "sha256": sha256(proof.read_bytes()).hexdigest(),
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

    def require_ok(self, by: str = "mac", decision: str = "D-X") -> dict:
        cp = self.run_cli("authority-require", "--by", by,
                          "--decision", decision)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def set_ok(self, supervisor: str = SUPERVISOR_ID) -> dict:
        cp = self.run_cli("authority-set", "--supervisor", supervisor,
                          "--decision", "D-X", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def ledger_path(self) -> Path:
        return self.root / "ledger" / "primary.jsonl"

    def primary_events(self) -> list[dict]:
        # ``ledger/primary.jsonl`` may deliberately be a directory in the
        # append-failure tests, so never assume it is readable here.
        path = self.ledger_path()
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def events_of(self, event_type: str) -> list[dict]:
        return [event for event in self.primary_events()
                if event.get("type") == event_type]

    def required_events(self) -> list[dict]:
        return self.events_of("AUTHORITY_REQUIRED")

    def authority_events(self) -> list[dict]:
        return self.events_of("AUTHORITY_SET")

    def policy_path(self) -> Path:
        return self.root / POLICY_FILE

    def policy(self) -> dict:
        return read_json(self.policy_path())

    def supervision_ledger(self) -> str:
        path = self.root / "ledger" / "supervision.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def queue_entries(self) -> list[dict]:
        return read_json(self.root / "supervision" / "MERGE_QUEUE.json")["entries"]

    def write_queue(self, entries: list[dict]) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": entries})

    def write_waiting_entry(self) -> None:
        self.write_queue([{"envelope_id": ENVELOPE, "task": TASK,
                           "branch": BRANCH, "base": "main",
                           "status": "WAITING", "added_at": FIXED_TIME}])

    def queue_bytes(self) -> bytes:
        return (self.root / "supervision" / "MERGE_QUEUE.json").read_bytes()

    def drop_last_event(self) -> dict:
        """Remove the trailing ledger row, keeping the prefix chain intact."""
        rows = self.ledger_path().read_text(encoding="utf-8").splitlines()
        self.assertTrue(rows, msg="the ledger must have a row to drop")
        dropped = json.loads(rows[-1])
        body = "\n".join(rows[:-1])
        self.ledger_path().write_text(body + "\n" if body else "",
                                      encoding="utf-8")
        return dropped

    def write_legacy_envelope(self, envelope_id: str = ENVELOPE) -> None:
        """A pre-baseline envelope: file/git checks only, no lifecycle events."""
        write_json(self.root / "supervision" / "envelopes" /
                   f"{envelope_id}.json", {
            "schema": "tower/merge-envelope@1",
            "envelope_id": envelope_id,
            "task": TASK,
            "repository": "..",
            "branch": BRANCH,
            "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head,
            "status": "DRAFT",
        })

    def find_check(self, payload: dict, needle: str) -> dict:
        for check in payload["checks"]:
            if needle in check["name"]:
                return check
        self.fail(f"no check containing {needle!r} in {payload['checks']}")

    def assert_merge_fails_closed(self, needle: str) -> None:
        """``merge`` exits 2 on authority and writes no queue/ledger state."""
        self.write_waiting_entry()
        before = self.queue_bytes()
        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertIn(needle, json.dumps(payload["errors"]))
        self.assertEqual(self.queue_bytes(), before,
                         msg="a refused merge must not touch the queue")
        self.assertEqual(self.queue_entries()[0]["status"], "WAITING")
        ledger = self.supervision_ledger()
        self.assertNotIn("MERGE_START", ledger)
        self.assertNotIn("MERGING", ledger)

    # -- 1. require on a configured tower ---------------------------------
    def test_require_pins_policy_and_exactly_one_event(self) -> None:
        self.set_ok()
        out = self.require_ok(decision="D-X")

        self.assertTrue(out["ok"], out)
        self.assertTrue(out["required"], out)
        self.assertFalse(out["already"], out)
        self.assertTrue(out["repaired"], out)
        self.assertEqual(out["path"], POLICY_FILE)

        policy = self.policy()
        self.assertEqual(policy["schema"], POLICY_SCHEMA)
        self.assertEqual(policy["tower_id"], "tower-dsh")
        self.assertIs(policy["require_authority"], True)
        self.assertEqual(policy["set_by"], "mac")
        self.assertEqual(policy["decision"], "D-X")
        self.assertIsInstance(policy["set_at"], str)

        events = self.required_events()
        self.assertEqual(len(events), 1, msg=events)
        # The event payload is isomorphic to the policy file: same keys, same
        # values, so the requirement can be reconstructed from either half.
        self.assertEqual(events[0]["payload"], policy)

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "required")
        self.assertTrue(check["required"], check)
        pinned = self.find_check(check, "authority requirement pinned")
        self.assertTrue(pinned["ok"], pinned)

        # merge-check reports the requirement as its own ok=true check.
        self.write_legacy_envelope()
        self.write_waiting_entry()
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        requirement = self.find_check(check, "merge authority requirement")
        self.assertTrue(requirement["ok"], requirement)
        self.assertIn(POLICY_FILE, requirement["detail"])

    # -- 2. a non-owner writes nothing ------------------------------------
    def test_require_rejects_non_owner_with_zero_writes(self) -> None:
        ledger_before = self.ledger_path().read_bytes()

        cp = self.run_cli("authority-require", "--by", "mallory",
                          "--decision", "D-X")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = cp.stdout + cp.stderr
        self.assertIn("mallory", blob)
        self.assertIn("owner", blob)
        self.assertFalse(self.policy_path().exists(),
                         msg="a rejected require must not write the policy")
        self.assertEqual(self.required_events(), [])
        self.assertEqual(self.ledger_path().read_bytes(), ledger_before)

    # -- 3. re-running is idempotent --------------------------------------
    def test_repeat_require_is_idempotent(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        policy_before = self.policy_path().read_bytes()
        ledger_before = self.ledger_path().read_bytes()

        out = self.require_ok(decision="D-Y")

        self.assertTrue(out["ok"], out)
        self.assertTrue(out["already"], out)
        self.assertFalse(out["repaired"], out)
        self.assertEqual(len(self.required_events()), 1)
        self.assertEqual(self.policy_path().read_bytes(), policy_before,
                         msg="an idempotent require must not rewrite the policy")
        self.assertEqual(self.ledger_path().read_bytes(), ledger_before,
                         msg="an idempotent require must not append an event")

    # -- 4. deleting both halves cannot downgrade a required tower --------
    def test_required_tower_without_state_is_not_legacy_and_blocks_merge(
            self) -> None:
        # AUTHORITY_REQUIRED first, AUTHORITY_SET last: the dropped row is the
        # only AUTHORITY_SET and the remaining prefix is a legal hash chain.
        self.require_ok(decision="D-X")
        self.set_ok()
        (self.root / AUTHORITY_FILE).unlink()
        dropped = self.drop_last_event()
        self.assertEqual(dropped["type"], "AUTHORITY_SET", msg=dropped)
        self.assertEqual(len(self.required_events()), 1)

        cp = self.run_cli("verify-ledger")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["status"], "required_unconfigured")
        self.assertIn("authority required but not configured",
                      json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertIn("authority_required_unconfigured",
                      [item["kind"] for item in out["drift"]], msg=out)
        # The 037 missing-state drift is not the whole story any more: the
        # requirement itself is the drift.  There is no legacy skip here.
        self.assertNotIn("authority_state",
                         [item["kind"] for item in out["skipped"]])

        # merge-check reports the requirement as a failed check, never legacy.
        self.write_legacy_envelope()
        self.write_waiting_entry()
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        failed = next((check for check in payload["errors"]
                       if "merge authority" in check["name"]), None)
        self.assertIsNotNone(failed, msg=payload)
        self.assertFalse(failed["ok"], failed)
        self.assertIn("required but not configured", failed["detail"])

        self.assert_merge_fails_closed("required but not configured")

    # -- 5. event without policy: policy missing --------------------------
    def test_deleted_policy_with_event_is_policy_missing(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        self.policy_path().unlink()

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertIn("authority policy missing", json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in out["drift"]],
                         ["authority_policy_missing"], msg=out)
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "AUTHORITY_POLICY")
        self.assertEqual(drift["actual"], "missing")

        self.assert_merge_fails_closed("policy missing")

    # -- 6. policy without event: policy unbacked -------------------------
    def test_truncated_required_event_is_policy_unbacked(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        dropped = self.drop_last_event()
        self.assertEqual(dropped["type"], "AUTHORITY_REQUIRED", msg=dropped)
        self.assertIs(self.policy()["require_authority"], True)

        cp = self.run_cli("verify-ledger")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertIn("authority policy unbacked", json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in out["drift"]],
                         ["authority_policy_unbacked"], msg=out)
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "AUTHORITY_POLICY")
        self.assertEqual(drift["actual"], "policy file only")

        self.assert_merge_fails_closed("policy unbacked")

    # -- 6b. require repairs whichever half went missing -------------------
    def test_require_repairs_missing_halves(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")

        # Policy deleted, event still there: the next require rewrites only the
        # policy half and does not append a duplicate event.
        self.policy_path().unlink()
        out = self.require_ok(decision="D-Y")
        self.assertTrue(out["repaired"], out)
        self.assertFalse(out["already"], out)
        self.assertIs(self.policy()["require_authority"], True)
        self.assertEqual(len(self.required_events()), 1)
        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "required")

        # Event truncated but policy intact: the next require appends only the
        # missing event, replaying the policy file verbatim.
        dropped = self.drop_last_event()
        self.assertEqual(dropped["type"], "AUTHORITY_REQUIRED", msg=dropped)
        out = self.require_ok(decision="D-Z")
        self.assertTrue(out["repaired"], out)
        self.assertEqual(len(self.required_events()), 1)
        self.assertEqual(self.required_events()[0]["payload"], self.policy())
        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "required")
        out = self.cli_json("state-verify")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["drift"], [])

    # -- 7a. authority-set append failure is one JSON, exit 2 -------------
    def test_authority_set_append_failure_is_clean_and_repairable(self) -> None:
        ledger = self.ledger_path()
        original = ledger.read_bytes()
        ledger.unlink()
        ledger.mkdir()

        cp = self.run_cli("authority-set", "--supervisor", SUPERVISOR_ID,
                          "--decision", "D-X", "--by", "mac")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)  # exactly one JSON object
        self.assertFalse(payload["ok"], payload)
        self.assertIn("cannot append AUTHORITY_SET", json.dumps(payload["errors"]))
        # The state file was written before the append failed: it must be
        # visible as unbacked, never as a usable configured state.
        self.assertTrue((self.root / AUTHORITY_FILE).exists())
        check = self.cli_json("authority-check")
        self.assertFalse(check["ok"], check)
        backed = self.find_check(check, "backed by ledger")
        self.assertFalse(backed["ok"], backed)
        self.assertIn("no AUTHORITY_SET event", backed["detail"])
        self.assert_merge_fails_closed("no AUTHORITY_SET event")

        # Restoring the ledger and re-running repairs the half-write.
        ledger.rmdir()
        ledger.write_bytes(original)
        self.set_ok()
        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "optional")
        self.assertEqual(len(self.authority_events()), 1)

    # -- 7b. authority-require append failure is fail-closed --------------
    def test_authority_require_append_failure_is_clean_and_repairable(
            self) -> None:
        ledger = self.ledger_path()
        original = ledger.read_bytes()
        ledger.unlink()
        ledger.mkdir()

        cp = self.run_cli("authority-require", "--by", "mac",
                          "--decision", "D-X")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)  # exactly one JSON object
        self.assertFalse(payload["ok"], payload)
        self.assertIn("cannot append AUTHORITY_REQUIRED",
                      json.dumps(payload["errors"]))
        # The policy half was written but has no event: visible, unbacked,
        # never a passing configured state.
        self.assertTrue(self.policy_path().exists())
        self.assertIs(self.policy()["require_authority"], True)
        self.assertEqual(self.required_events(), [])
        check = self.cli_json("authority-check")
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["status"], "required_unconfigured")
        self.assertIn("authority policy unbacked", json.dumps(check))

        # Repair both halves once the ledger is writable: the re-run appends
        # the missing event instead of appending a duplicate.
        ledger.rmdir()
        ledger.write_bytes(original)
        out = self.require_ok(decision="D-Y")
        self.assertTrue(out["repaired"], out)
        self.assertEqual(len(self.required_events()), 1)
        self.set_ok()
        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "required")
        self.assertTrue(self.find_check(check, "authority requirement pinned")["ok"])

    # -- 8. a non-required tower keeps the 037 behaviour -------------------
    def test_non_required_tower_keeps_legacy_and_configured_behaviour(
            self) -> None:
        self.write_legacy_envelope()
        self.write_waiting_entry()

        # No policy and no event: legacy, still passing, legacy detail intact.
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        legacy = self.find_check(payload, "merge authority")
        self.assertTrue(legacy["ok"], legacy)
        self.assertEqual(legacy["detail"], "legacy: no AUTHORITY_SET")
        check = self.cli_json("authority-check")
        self.assertEqual(check["status"], "legacy")
        self.assertEqual(check["requirement"], "optional")
        self.assertTrue(check["ok"], check)

        # Configured but not required: 037's configured pin, no requirement.
        self.set_ok()
        check = self.cli_json("authority-check")
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "optional")
        self.assertTrue(check["ok"], check)
        self.assertTrue(self.find_check(check, "backed by ledger")["ok"])
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        pinned = self.find_check(payload, "merge authority pinned")
        self.assertIn(SUPERVISOR_ID, pinned["detail"])
        self.assertNotIn("requirement",
                         json.dumps([c["name"] for c in payload["checks"]]))


if __name__ == "__main__":
    unittest.main()
