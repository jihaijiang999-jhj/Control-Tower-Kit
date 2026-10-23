"""PILOT-036: trust-boundary closure for the merge gate.

Three residual holes used to let the merge gate believe the chain held:

* a *missing* or *unreadable* ``ledger/<name>.jsonl`` verified as an intact
  empty chain (or crashed with a traceback), so ``verify-ledger`` and the
  envelope's ``ledger chain intact`` check both said "ok";
* the command-level envelope identity compared ``str(... or "")``, so a JSON
  declaration of ``42`` passed for the requested id ``"42"``;
* ``ENVELOPE_NEW`` was matched by envelope id alone; it now has to bind the
  envelope ``task`` and ``envelope_head_sha`` as well.

Every test drives the real CLI in a subprocess over an isolated tower root.
The envelope id is deliberately the integer-looking ``"42"`` so the identity
tests exercise the exact case ``str(42) == "42"`` used to accept.

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
TASK = "T-TRUST-001"
ENVELOPE = "42"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/trust"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
GENESIS = "GENESIS"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def canonical_hash(event: dict) -> str:
    """Independent re-implementation of the documented canonical hash."""
    body = {k: v for k, v in event.items() if k != "hash"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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


class TrustBoundaryTestCase(unittest.TestCase):
    """Missing/unreadable ledgers, exact identity and ENVELOPE_NEW binding."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-trust-boundary-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1",
            "id": TASK,
            "title": "trust boundary",
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
            "primary": {"id": "ctl-primary"},
            "owner": {"name": "mac"},
            "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.init_repo()
        self.envelope_file = self.root / "envelope.json"
        self.write_payload(self.payload())

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
        (self.kit / "feature.txt").write_text("implementation\n",
                                              encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.envelope_head = self.commit_all("envelope")
        self.assertEqual(self.git("checkout", "main").returncode, 0)

    def payload(self, **overrides) -> dict:
        data = {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE,
            "task": TASK,
            "repository": "..",
            "branch": BRANCH,
            "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1,
            "tower_tests_baseline": 1,
        }
        data.update(overrides)
        return data

    def write_payload(self, payload: dict) -> None:
        write_json(self.envelope_file, payload)

    def envelope_path(self, name: str = ENVELOPE) -> Path:
        return self.root / "supervision" / "envelopes" / f"{name}.json"

    def supervision_ledger_path(self) -> Path:
        return self.root / "ledger" / "supervision.jsonl"

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def create_valid_tower(self) -> None:
        """Envelope + queue entry through the real commands (2 ledger events)."""
        cp = self.run_cli("envelope-new", "--task", TASK,
                          "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.run_cli("queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    # -- ledger helpers --------------------------------------------------
    def ledger_events(self) -> list[dict]:
        text = self.supervision_ledger_path().read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def write_ledger_events(self, events: list[dict]) -> None:
        """Rewrite the supervision ledger with a freshly recomputed chain."""
        previous = GENESIS
        lines = []
        for seq, event in enumerate(events, 1):
            event["seq"] = seq
            event["prev_hash"] = previous
            event["hash"] = canonical_hash(event)
            previous = event["hash"]
            lines.append(json.dumps(event, ensure_ascii=False) + "\n")
        self.supervision_ledger_path().write_text(
            "".join(lines), encoding="utf-8", newline="\n")

    def envelope_new_event(self, events: list[dict] | None = None) -> dict:
        """The ``ENVELOPE_NEW`` event, taken from ``events`` when given."""
        if events is None:
            events = self.ledger_events()
        return next(event for event in events
                    if event.get("type") == "ENVELOPE_NEW")

    def queue_entries(self) -> list:
        return read_json(self.root / "supervision" / "MERGE_QUEUE.json")["entries"]

    def assert_single_json(self, cp: subprocess.CompletedProcess) -> dict:
        """``stdout`` must be exactly one JSON object, with no traceback."""
        self.assertNotIn("Traceback", cp.stderr,
                         msg=f"stderr={cp.stderr}")
        text = cp.stdout.strip()
        self.assertTrue(text.startswith("{") and text.endswith("}"),
                        msg=f"stdout is not one JSON object: {cp.stdout!r}")
        return json.loads(text)

    # -- A. missing / unreadable ledgers ---------------------------------
    def test_missing_supervision_ledger_fails_verify_ledger(self) -> None:
        self.create_valid_tower()
        self.supervision_ledger_path().unlink()

        cp = self.run_cli("verify-ledger", "--ledger", "supervision")

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"],
                         ["supervision: ledger missing: ledger/supervision.jsonl"])
        report = payload["files"]["supervision"]
        # A missing file is not an empty chain: exactly one error, no events.
        self.assertEqual(report["errors"],
                         ["ledger missing: ledger/supervision.jsonl"])
        self.assertFalse(report["exists"])
        self.assertEqual(report["events"], 0)
        self.assertEqual(report["legacy_unhashed"], 0)

    def test_missing_supervision_ledger_fails_only_chain_check(self) -> None:
        self.create_valid_tower()
        self.supervision_ledger_path().unlink()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        # Every non-ledger check is green; the missing ledger is the only
        # failure, so the merge gate cannot be talked into "ok".
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["ledger chain intact"])
        detail = payload["errors"][0]["detail"]
        self.assertTrue(detail.startswith("supervision: ledger missing"),
                        msg=detail)

    def test_unreadable_supervision_ledger_fails_verify_ledger(self) -> None:
        self.create_valid_tower()
        path = self.supervision_ledger_path()
        path.unlink()
        path.mkdir()

        cp = self.run_cli("verify-ledger", "--ledger", "supervision")

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        # Parsing succeeds only when the command emitted exactly one JSON.
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertIn("ledger unreadable", " ".join(payload["errors"]))
        report = payload["files"]["supervision"]
        self.assertEqual(len(report["errors"]), 1, msg=report)
        self.assertTrue(
            report["errors"][0].startswith(
                "ledger unreadable: ledger/supervision.jsonl: "),
            msg=report["errors"])
        self.assertEqual(report["events"], 0)

    def test_unreadable_supervision_ledger_fails_chain_check(self) -> None:
        self.create_valid_tower()
        path = self.supervision_ledger_path()
        path.unlink()
        path.mkdir()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["ledger chain intact"])
        detail = payload["errors"][0]["detail"]
        self.assertTrue(detail.startswith("supervision: ledger unreadable"),
                        msg=detail)

    def test_unreadable_primary_ledger_is_reported_by_both_gates(self) -> None:
        self.create_valid_tower()
        path = self.root / "ledger" / "primary.jsonl"
        path.unlink()
        path.mkdir()

        verify = self.run_cli("verify-ledger", "--ledger", "primary")
        self.assertEqual(verify.returncode, 2,
                         msg=f"stdout={verify.stdout}\nstderr={verify.stderr}")
        report = self.assert_single_json(verify)["files"]["primary"]
        self.assertIn("ledger unreadable", " ".join(report["errors"]))
        self.assertEqual(len(report["errors"]), 1, msg=report)

        check = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(check.returncode, 2,
                         msg=f"stdout={check.stdout}\nstderr={check.stderr}")
        payload = self.assert_single_json(check)
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["ledger chain intact"])
        detail = payload["errors"][0]["detail"]
        self.assertTrue(detail.startswith("primary: ledger unreadable"),
                        msg=detail)

    def test_empty_supervision_ledger_is_intact(self) -> None:
        # setUp already touched both ledgers empty.  What was missing is the
        # *file*, not the *events*: an existing empty ledger verifies clean.
        self.assertEqual(self.supervision_ledger_path().read_text(
            encoding="utf-8"), "")

        cp = self.run_cli("verify-ledger")

        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        self.assertEqual(payload["errors"], [])
        report = payload["files"]["supervision"]
        self.assertTrue(report["exists"])
        self.assertEqual(report["events"], 0)
        self.assertEqual(report["legacy_unhashed"], 0)
        self.assertEqual(report["errors"], [])

    # -- B. exact command-level identity ---------------------------------
    def test_integer_envelope_id_rejected_by_merge_check(self) -> None:
        self.create_valid_tower()
        record = read_json(self.envelope_path())
        # A JSON integer whose ``str()`` equals the requested id: the old
        # ``str(...)`` normalisation let it through the command-level gate.
        record["envelope_id"] = 42
        write_json(self.envelope_path(), record)

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        # Command-level identity failures are plain strings, not check dicts.
        self.assertIsInstance(payload["errors"], list)
        self.assertTrue(payload["errors"], msg=payload)
        for error in payload["errors"]:
            self.assertIsInstance(error, str, msg=payload)
        self.assertTrue(payload["errors"][0].startswith(
            "envelope identity matches request:"), msg=payload["errors"][0])
        self.assertIn("42", payload["errors"][0])

        # The same tower with the id put back as the string no longer fails
        # on identity (the rest of the tower is valid, so it fully passes).
        record["envelope_id"] = ENVELOPE
        write_json(self.envelope_path(), record)
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        identity = next(check for check in payload["checks"]
                        if check["name"] == "envelope identity matches request")
        self.assertTrue(identity["ok"], msg=identity)

    def test_integer_envelope_id_rejected_by_merge(self) -> None:
        self.create_valid_tower()
        record = read_json(self.envelope_path())
        record["envelope_id"] = 42
        write_json(self.envelope_path(), record)
        ledger_before = self.supervision_ledger_path().read_bytes()
        queue_before = read_json(self.root / "supervision" / "MERGE_QUEUE.json")

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", "sup-test", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertTrue(all(isinstance(error, str)
                            for error in payload["errors"]), msg=payload)
        self.assertTrue(payload["errors"][0].startswith(
            "envelope identity matches request:"), msg=payload["errors"][0])
        # The command gate fires before any queue/ledger write.
        entries = self.queue_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        self.assertEqual(entries[0]["status"], "WAITING")
        self.assertNotEqual(entries[0]["status"], "MERGING")
        self.assertEqual(
            read_json(self.root / "supervision" / "MERGE_QUEUE.json"),
            queue_before)
        self.assertEqual(self.supervision_ledger_path().read_bytes(),
                         ledger_before)
        self.assertNotIn("MERGE_START",
                         self.supervision_ledger_path().read_text(
                             encoding="utf-8"))

    # -- C. ENVELOPE_NEW binds head and task -----------------------------
    def test_envelope_new_head_mismatch_fails_merge_check(self) -> None:
        self.create_valid_tower()
        events = self.ledger_events()
        created = self.envelope_new_event(events)
        other_head = "a" * 40
        created["payload"]["head"] = other_head
        self.write_ledger_events(events)

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded"])
        detail = payload["errors"][0]["detail"]
        self.assertIn("head", detail)
        self.assertIn(other_head, detail)

        # Restoring the recorded head clears exactly this failure.
        created["payload"]["head"] = self.envelope_head
        self.write_ledger_events(events)
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertTrue(checks["envelope_new recorded"]["ok"], msg=cp.stdout)
        self.assertEqual(checks["envelope_new recorded"]["detail"],
                         "ENVELOPE_NEW event present")

    def test_envelope_new_task_mismatch_fails_merge_check(self) -> None:
        self.create_valid_tower()
        events = self.ledger_events()
        created = self.envelope_new_event(events)
        created["payload"]["task"] = "T-OTHER-001"
        self.write_ledger_events(events)

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded"])
        detail = payload["errors"][0]["detail"]
        self.assertIn("task", detail)
        self.assertIn("T-OTHER-001", detail)

    def test_envelope_new_binding_mismatch_blocks_merge(self) -> None:
        self.create_valid_tower()
        events = self.ledger_events()
        created = self.envelope_new_event(events)
        created["payload"]["head"] = "b" * 40
        self.write_ledger_events(events)

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", "sup-test", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded"])
        # Blocked before MERGING: the entry asks for a correction and no merge
        # was started (no MERGE_START event, envelope still DRAFT).
        entries = self.queue_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        self.assertEqual(entries[0]["status"], "CORRECTION_REQUIRED")
        text = self.supervision_ledger_path().read_text(encoding="utf-8")
        self.assertIn("MERGE_BLOCKED", text)
        self.assertNotIn("MERGE_START", text)
        self.assertEqual(read_json(self.envelope_path())["status"], "DRAFT")

    # -- D. clean tower regression ---------------------------------------
    def test_valid_tower_passes_merge_check(self) -> None:
        self.create_valid_tower()

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = self.assert_single_json(cp)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertTrue(all(check["ok"] for check in payload["checks"]),
                        msg=cp.stdout)
        self.assertEqual(checks["ledger chain intact"]["detail"], "ok")
        self.assertEqual(checks["envelope_new recorded"]["detail"],
                         "ENVELOPE_NEW event present")
        self.assertEqual(checks["queue entry backed by ledger"]["detail"],
                         "QUEUE_ADD event present")


if __name__ == "__main__":
    unittest.main()
