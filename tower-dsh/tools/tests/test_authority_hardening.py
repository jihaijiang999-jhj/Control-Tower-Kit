"""PILOT-039: authority hardening (policy isomorphism, cross-lock, merge chain).

Three residual holes from PILOT-038 are closed here:

1. **policy <-> event isomorphism.**  The marker has two halves
   (``shared/AUTHORITY_POLICY.json`` and one ``AUTHORITY_REQUIRED`` event).  038
   only checked presence and polarity, so rewriting ``tower_id``/``set_by``/
   ``decision``/``set_at`` in the policy file (or typing ``require_authority``
   as ``"true"``/``1``/``null``) was silent.  Now every shared field must match
   the *last* event payload exactly, ``require_authority`` must be the boolean
   ``true``, and a present-but-invalid policy fails closed instead of
   downgrading the tower to optional/legacy.
2. **cross-lock.**  ``authority-require``/``authority-set`` serialized only the
   ledger append, so two writers could read the same revision or race the
   ``.tmp`` replace.  The whole read-validate-write-append section now runs
   under ``state/.authority.lock`` (taken before the ledger lock), so concurrent
   ``authority-set`` calls produce unique, strictly increasing revisions with
   one event per success.
3. **pre-merge chain verification.**  ``merge`` used to trust a legacy envelope
   without verifying the ledgers, so a forged row with a legal ``seq``/
   ``prev_hash`` (only the hash wrong) could reach ``MERGED``.  ``merge`` now
   verifies both ledgers before reading the envelope/queue/git, and legacy
   ``merge-check`` carries an independent ``pre-merge ledger chains verified``
   item (new-style envelopes already have ``ledger chain intact``, so they do
   not get a second, synonymous check).

Every test builds a throw-away kit (a git repository with a tower inside) under
``tempfile`` and drives the real CLI in a subprocess, like the 037/038 suites.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
TASK = "T-AUTH-039"
ENVELOPE = "ENV-AUTH-039"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/authority-039"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
AUTHORITY_FILE = "state/AUTHORITY.json"
POLICY_FILE = "shared/AUTHORITY_POLICY.json"
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"
POLICY_SCHEMA = "tower/authority-policy@1"
MISMATCH_PREFIX = "authority policy does not match last AUTHORITY_REQUIRED"

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


class AuthorityHardeningTestCase(unittest.TestCase):
    """A tower with one primary, one supervision state and a merge branch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-authority-hardening-", ignore_cleanup_errors=True)
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
            "title": "authority hardening",
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

    def popen_cli(self, *args: str) -> subprocess.Popen:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.Popen(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=env,
        )

    def cli_json(self, *args: str) -> dict:
        cp = self.run_cli(*args)
        try:
            return json.loads(cp.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
            self.fail(f"{args} emitted non-JSON stdout={cp.stdout!r} "
                      f"stderr={cp.stderr!r}: {exc}")

    def require_ok(self, decision: str = "D-X") -> dict:
        cp = self.run_cli("authority-require", "--by", "mac",
                          "--decision", decision)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def set_ok(self, supervisor: str = SUPERVISOR_ID) -> dict:
        cp = self.run_cli("authority-set", "--supervisor", supervisor,
                          "--decision", "D-X", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return json.loads(cp.stdout)

    def ledger_path(self, name: str = "primary") -> Path:
        return self.root / "ledger" / f"{name}.jsonl"

    def ledger_events(self, name: str = "primary") -> list[dict]:
        path = self.ledger_path(name)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def events_of(self, event_type: str) -> list[dict]:
        return [event for event in self.ledger_events()
                if event.get("type") == event_type]

    def required_events(self) -> list[dict]:
        return self.events_of("AUTHORITY_REQUIRED")

    def authority_events(self) -> list[dict]:
        return self.events_of("AUTHORITY_SET")

    def policy_path(self) -> Path:
        return self.root / POLICY_FILE

    def policy(self) -> dict:
        return read_json(self.policy_path())

    def write_policy(self, **overrides) -> None:
        data = dict(self.policy())
        data.update(overrides)
        write_json(self.policy_path(), data)

    def supervision_ledger(self) -> str:
        path = self.ledger_path("supervision")
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

    def write_envelope(self, *, baselines: bool = False) -> None:
        data = {
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
        }
        if baselines:
            data.update({"tests_baseline": 1, "tower_tests_baseline": 1})
        write_json(self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json",
                   data)

    def append_forged_row(self, name: str = "primary",
                          event_type: str = "FORGED") -> dict:
        """Append a row with legal ``seq``/``prev_hash`` and a wrong hash.

        This is exactly the attack the pre-merge chain check must catch: the
        row looks structurally fine to a parser, so only verifying the hash
        reveals it.  It is not produced by any towerctl writer.
        """
        rows = self.ledger_events(name)
        seq = max((event.get("seq", 0) for event in rows), default=0) + 1
        prev = rows[-1]["hash"] if rows else "GENESIS"
        event = {
            "seq": seq,
            "at": FIXED_TIME,
            "type": event_type,
            "actor": "forger",
            "payload": {"forged": True},
            "prev_hash": prev,
            "hash": "0" * 64,
        }
        with self.ledger_path(name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def find_check(self, payload: dict, needle: str) -> dict:
        for check in payload["checks"]:
            if needle in check["name"]:
                return check
        self.fail(f"no check containing {needle!r} in {payload['checks']}")

    def assert_merge_refused(self, needle: str) -> dict:
        """``merge`` exits 2 at the authority gate and starts nothing.

        Deliberately does not queue an entry: the authority gate runs before
        the envelope/queue are read, so no fixture is needed and the tower's
        queue state stays untouched for the surrounding assertions.
        """
        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertIn(needle, json.dumps(payload["errors"]))
        ledger = self.supervision_ledger()
        self.assertNotIn("MERGE_START", ledger)
        self.assertNotIn("MERGING", ledger)
        return payload

    def assert_single_json(self, cp: subprocess.CompletedProcess) -> dict:
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        try:
            return json.loads(cp.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
            self.fail(f"stdout is not one JSON object: {cp.stdout!r} "
                      f"stderr={cp.stderr!r}: {exc}")

    # -- 1. isomorphism positive -----------------------------------------
    def test_policy_event_isomorphism_passes_after_require(self) -> None:
        self.set_ok()
        out = self.require_ok(decision="D-X")
        self.assertTrue(out["required"], out)

        # The file and the last event are byte-for-byte the same JSON object.
        self.assertEqual(self.required_events()[-1]["payload"], self.policy())

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertEqual(check["requirement"], "required")

        state = self.cli_json("state-verify")
        self.assertTrue(state["ok"], state)
        self.assertEqual(state["drift"], [])

        self.write_envelope()
        self.write_waiting_entry()
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        merged_check = json.loads(cp.stdout)
        pinned = self.find_check(merged_check, "merge authority requirement")
        self.assertTrue(pinned["ok"], pinned)

    # -- 2. each audit field is compared ---------------------------------
    def test_policy_audit_field_tamper_fails_check_verify_and_merge(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        original = self.policy_path().read_bytes()

        tampered = {
            "tower_id": "tower-rogue",
            "set_by": "mallory",
            "decision": "D-OTHER",
            "set_at": FIXED_TIME,
        }
        for field, value in tampered.items():
            with self.subTest(field=field):
                self.policy_path().write_bytes(original)
                self.write_policy(**{field: value})

                cp = self.run_cli("authority-check")
                self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
                check = json.loads(cp.stdout)
                self.assertFalse(check["ok"], check)
                blob = json.dumps(check)
                self.assertIn(MISMATCH_PREFIX, blob)
                self.assertIn(field, blob)
                self.assertIn(value, blob)

                cp = self.run_cli("state-verify")
                self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
                state = json.loads(cp.stdout)
                self.assertEqual([item["kind"] for item in state["drift"]],
                                 ["authority_policy_mismatch"], msg=state)
                drift = state["drift"][0]
                self.assertEqual(drift["target"], "AUTHORITY_POLICY")
                self.assertEqual(drift["actual"][field], value)
                self.assertNotEqual(drift["expected"][field], value)

                self.assert_merge_refused(MISMATCH_PREFIX)

        # Restoring the policy restores every gate: nothing was one-way.
        self.policy_path().write_bytes(original)
        self.assertTrue(self.cli_json("authority-check")["ok"])
        self.assertEqual(self.cli_json("state-verify")["drift"], [])

    # -- 3. require_authority must be boolean true -----------------------
    def test_require_authority_truthy_lookalikes_fail_closed(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        original = self.policy_path().read_bytes()
        # ``AUTHORITY_ABSENT`` is emulated by deleting the key entirely: a
        # missing field must not compare equal to one that is present.
        cases = [("string", "true"), ("int", 1), ("null", None),
                 ("missing", towerctl.AUTHORITY_ABSENT)]
        for label, value in cases:
            with self.subTest(require_authority=label):
                self.policy_path().write_bytes(original)
                data = dict(self.policy())
                if value is towerctl.AUTHORITY_ABSENT:
                    data.pop("require_authority", None)
                else:
                    data["require_authority"] = value
                write_json(self.policy_path(), data)

                cp = self.run_cli("authority-check")
                self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
                check = json.loads(cp.stdout)
                self.assertFalse(check["ok"], check)
                # 038 semantics are preserved: the event exists but the policy
                # is not a requirement, so this is "policy missing".
                self.assertIn("authority policy missing", json.dumps(check))

                cp = self.run_cli("state-verify")
                self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
                state = json.loads(cp.stdout)
                self.assertEqual([item["kind"] for item in state["drift"]],
                                 ["authority_policy_missing"], msg=state)

                self.assert_merge_refused("authority policy missing")
        self.policy_path().write_bytes(original)

    def test_invalid_policy_without_event_is_fail_closed(self) -> None:
        # No AUTHORITY_SET, no AUTHORITY_REQUIRED event: only a policy file that
        # tries to require authority with the wrong type.  It must not be read
        # as "optional" and it must not be reported as legacy.
        write_json(self.policy_path(), {
            "schema": POLICY_SCHEMA,
            "tower_id": "tower-dsh",
            "require_authority": "true",
            "set_by": "mac",
            "decision": "D-X",
            "set_at": FIXED_TIME,
        })

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        blob = json.dumps(check)
        self.assertIn("authority policy invalid", blob)
        self.assertIn("require_authority", blob)
        self.assertNotEqual(check["status"], "legacy", check)

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        state = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in state["drift"]],
                         ["authority_policy_mismatch"], msg=state)
        drift = state["drift"][0]
        self.assertEqual(drift["target"], "AUTHORITY_POLICY")
        self.assertIs(drift["expected"]["require_authority"], True)
        self.assertEqual(drift["actual"]["require_authority"], "true")
        self.assertNotIn("authority_state",
                         [item["kind"] for item in state["skipped"]])

    def test_require_repairs_a_divergent_policy_from_the_event(self) -> None:
        self.set_ok()
        self.require_ok(decision="D-X")
        self.write_policy(set_by="mallory", decision="D-OTHER")
        self.assertEqual([item["kind"] for item in
                          self.cli_json("state-verify")["drift"]],
                         ["authority_policy_mismatch"])

        out = self.require_ok(decision="D-IGNORED")

        self.assertTrue(out["repaired"], out)
        self.assertFalse(out["already"], out)
        self.assertEqual(self.policy(), self.required_events()[-1]["payload"])
        self.assertTrue(self.cli_json("authority-check")["ok"])
        self.assertEqual(self.cli_json("state-verify")["drift"], [])

    # -- 4. concurrent authority-set -------------------------------------
    def test_concurrent_authority_set_serializes_revisions(self) -> None:
        workers = 3
        rounds = 2
        results: list[tuple[int, str, str]] = []
        for _ in range(rounds):
            processes = [self.popen_cli("authority-set",
                                        "--supervisor", SUPERVISOR_ID,
                                        "--decision", "D-X", "--by", "mac")
                         for _ in range(workers)]
            for process in processes:
                stdout, stderr = process.communicate(timeout=180)
                results.append((process.returncode, stdout, stderr))

        successes = 0
        for code, stdout, stderr in results:
            self.assertNotIn("Traceback", stdout + stderr)
            payload = json.loads(stdout)  # exactly one JSON object
            if code == 0:
                successes += 1
                self.assertTrue(payload["ok"], payload)
            else:
                # A loser must be a clean, single-JSON refusal.
                self.assertEqual(code, 2, msg=stdout + stderr)
                self.assertFalse(payload["ok"], payload)
                self.assertIn("errors", payload)
                self.assertTrue(payload["errors"], payload)

        events = self.authority_events()
        self.assertEqual(len(events), successes,
                         msg="one AUTHORITY_SET per successful writer")
        revisions = [event["payload"]["revision"] for event in events]
        self.assertEqual(revisions, list(range(1, successes + 1)),
                         msg="revisions must be unique and strictly increasing")
        self.assertEqual(len(set(revisions)), len(revisions))
        state = read_json(self.root / AUTHORITY_FILE)
        self.assertEqual(state["revision"], revisions[-1])

        cp = self.run_cli("verify-ledger")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        report = json.loads(cp.stdout)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["errors"], [])

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")

        self.assertFalse((self.root / "state" / ".authority.lock").exists(),
                         msg="no authority lock may be left behind")
        self.assertEqual(list(self.root.rglob("*.tmp")), [],
                         msg="no .tmp residue may survive a write")

    # -- 5. merge precondition: forged primary row, legacy envelope ------
    def test_merge_precondition_blocks_forged_primary_row(self) -> None:
        # A legacy envelope has no baselines, so 038's envelope checks never
        # verify the ledgers for it.
        self.write_envelope(baselines=False)
        self.write_waiting_entry()
        forged = self.append_forged_row("primary")
        self.assertEqual(forged["type"], "FORGED")
        envelope_before = (self.root / "supervision" / "envelopes"
                           / f"{ENVELOPE}.json").read_bytes()
        queue_before = self.queue_bytes()

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        blob = json.dumps(payload["errors"])
        self.assertIn("merge precondition: primary ledger chain broken", blob)
        self.assertIn("ledger chain broken", blob)
        # Nothing downstream of the precondition may have run.
        self.assertEqual(self.queue_bytes(), queue_before)
        self.assertEqual(self.queue_entries()[0]["status"], "WAITING")
        self.assertEqual(
            (self.root / "supervision" / "envelopes"
             / f"{ENVELOPE}.json").read_bytes(), envelope_before)
        ledger = self.supervision_ledger()
        self.assertNotIn("MERGE_START", ledger)
        self.assertNotIn("MERGING", ledger)

        cp = self.run_cli("verify-ledger")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)

    def test_legacy_merge_check_reports_broken_primary_chain(self) -> None:
        self.write_envelope(baselines=False)
        self.write_waiting_entry()
        self.append_forged_row("primary")

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        failed = [check["name"] for check in payload["errors"]]
        self.assertIn("pre-merge ledger chains verified", failed)
        detail = self.find_check(
            {"checks": payload["errors"]},
            "pre-merge ledger chains verified")["detail"]
        self.assertIn("primary ledger chain broken", detail)

    # -- 6. new-style envelope: one chain failure, no duplicate ----------
    def test_new_style_merge_check_has_no_duplicate_chain_failure(self) -> None:
        self.write_envelope(baselines=True)
        self.write_waiting_entry()
        self.append_forged_row("supervision")

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        failed = [check["name"] for check in payload["errors"]]
        # The new-style check inside ``envelope_checks`` owns this failure; a
        # second, synonymous pre-merge item would double-report one broken
        # chain, so the legacy-only precondition must stay out of the way.
        self.assertIn("ledger chain intact", failed)
        self.assertNotIn("pre-merge ledger chains verified", failed)
        chain_failures = [name for name in failed
                          if "chain" in name]
        self.assertEqual(len(chain_failures), 1, failed)

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = json.dumps(json.loads(cp.stdout)["errors"])
        self.assertIn("merge precondition: supervision ledger chain broken", blob)

    # -- 7. clean towers are unchanged -----------------------------------
    def test_clean_legacy_tower_still_passes_merge_check(self) -> None:
        self.write_envelope(baselines=False)
        self.write_waiting_entry()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        check = self.find_check(payload, "pre-merge ledger chains verified")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["detail"], "ok")

    def test_clean_configured_tower_still_passes_merge_check(self) -> None:
        self.set_ok()
        self.write_envelope(baselines=False)
        self.write_waiting_entry()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        pinned = self.find_check(payload, "merge authority pinned")
        self.assertIn(SUPERVISOR_ID, pinned["detail"])
        self.assertTrue(
            self.find_check(payload, "pre-merge ledger chains verified")["ok"])

    # -- 8. the authority lock itself ------------------------------------
    def test_authority_lock_timeout_is_one_json_exit_2(self) -> None:
        lock = self.root / "state" / ".authority.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("held by another writer\n", encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = ["towerctl", "--root", str(self.root), "authority-set",
                "--supervisor", SUPERVISOR_ID, "--decision", "D-X",
                "--by", "mac"]
        old_timeout = towerctl.LEDGER_LOCK_TIMEOUT
        try:
            towerctl.LEDGER_LOCK_TIMEOUT = 0.2
            with mock.patch.object(sys, "argv", argv), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    towerctl.main()
        finally:
            towerctl.LEDGER_LOCK_TIMEOUT = old_timeout

        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())
        payload = json.loads(stdout.getvalue())  # exactly one JSON object
        self.assertFalse(payload["ok"], payload)
        self.assertIn("lock", json.dumps(payload["errors"]).lower())
        # Someone else's lock must not be removed, and no partial write may
        # survive (file first, event second never started).
        self.assertTrue(lock.exists())
        self.assertFalse((self.root / AUTHORITY_FILE).exists())
        self.assertEqual(self.authority_events(), [])

    def test_authority_lock_clears_a_stale_lock_and_writes(self) -> None:
        lock = self.root / "state" / ".authority.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("stale\n", encoding="utf-8")
        old = time.time() - 120
        os.utime(lock, (old, old))

        out = self.set_ok()

        self.assertEqual(out["revision"], 1)
        self.assertFalse(lock.exists())
        self.assertTrue(self.cli_json("authority-check")["ok"])


if __name__ == "__main__":
    unittest.main()
