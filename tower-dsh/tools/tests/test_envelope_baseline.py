"""PILOT-029: a new envelope must declare both count baselines.

``tests_baseline`` and ``tower_tests_baseline`` are opt-in for the post-merge
count gates, which keeps legacy envelopes working.  That opt-in was also a
silent escape hatch: an envelope that simply omitted a field skipped the gate.
``envelope-new`` now rejects such an envelope before writing anything, so every
new envelope is counted against an explicit baseline.  A hand-written envelope
file could still skip that command, so ``queue-add`` enforces the same rule for
every envelope it admits to the merge queue (PILOT-030).

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
sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)
TASK = "T-BASE-001"
ENVELOPE = "ENV-BASE-001"
LEGACY_ENVELOPE = "ENV-LEGACY-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/baseline"
FIXED_TIME = "2026-10-22T00:00:00+08:00"

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


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


class EnvelopeBaselineTestCase(unittest.TestCase):
    """A new envelope needs ``tests_baseline`` and ``tower_tests_baseline``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-envelope-baseline-", ignore_cleanup_errors=True)
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
            "title": "baseline gate",
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
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
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

    def record(self) -> dict:
        return read_json(self.root / "tasks" / TASK / "record.json")

    def supervision_ledger(self) -> str:
        path = self.root / "ledger" / "supervision.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def queue_bytes(self) -> bytes:
        return (self.root / "supervision" / "MERGE_QUEUE.json").read_bytes()

    def supervision_ledger_bytes(self) -> bytes:
        path = self.root / "ledger" / "supervision.jsonl"
        return path.read_bytes() if path.exists() else b""

    def queue_entries(self) -> list:
        return read_json(self.root / "supervision" / "MERGE_QUEUE.json")["entries"]

    def queue_events(self) -> list:
        events = [json.loads(line) for line in self.supervision_ledger().splitlines()
                  if line.strip()]
        return [e for e in events if e.get("type") == "QUEUE_ADD"]

    def write_handwritten_envelope(self, missing=None) -> Path:
        """Write the envelope file directly, bypassing ``envelope-new``."""
        data = self.payload()
        data.update({
            "envelope_head_sha": self.envelope_head,
            "status": "DRAFT",
        })
        if missing is not None:
            del data[missing]
        write_json(self.envelope_path(), data)
        return self.envelope_path()

    def snapshot(self) -> dict:
        """Everything the rejected command could have changed."""
        envelopes = self.root / "supervision" / "envelopes"
        return {
            "envelopes": sorted(p.name for p in envelopes.iterdir()),
            "supervision_ledger": self.supervision_ledger(),
            "primary_ledger": (self.root / "ledger" / "primary.jsonl")
                              .read_text(encoding="utf-8"),
            "record": (self.root / "tasks" / TASK / "record.json")
                      .read_text(encoding="utf-8"),
            "queue": (self.root / "supervision" / "MERGE_QUEUE.json")
                     .read_text(encoding="utf-8"),
        }

    def assert_rejected(self, payload: dict) -> subprocess.CompletedProcess:
        self.write_payload(payload)
        before = self.snapshot()
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = cp.stdout + cp.stderr
        # One error must name both fields and the valid form.
        self.assertIn("tests_baseline", blob)
        self.assertIn("tower_tests_baseline", blob)
        self.assertIn("int >= 1", blob)
        # No side effects: no DRAFT, no ENVELOPE_NEW, no record/queue change.
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.envelope_path().exists())
        self.assertNotIn("ENVELOPE_NEW", self.supervision_ledger())
        self.assertEqual(self.record()["status"], "accepted")
        return cp

    def assert_queue_rejected(self, missing: str) -> subprocess.CompletedProcess:
        self.write_handwritten_envelope(missing=missing)
        before = self.snapshot()
        queue_before = self.queue_bytes()
        ledger_before = self.supervision_ledger_bytes()
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = cp.stdout + cp.stderr
        # One error must name both fields and the valid form.
        self.assertIn("tests_baseline", blob)
        self.assertIn("tower_tests_baseline", blob)
        self.assertIn("int >= 1", blob)
        # No writes: the queue and supervision ledger are byte-identical and
        # no QUEUE_ADD event was appended.
        self.assertEqual(self.queue_bytes(), queue_before)
        self.assertEqual(self.supervision_ledger_bytes(), ledger_before)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("QUEUE_ADD", self.supervision_ledger())
        self.assertEqual(self.queue_entries(), [])
        return cp

    # -- rejection -------------------------------------------------------
    def test_missing_tests_baseline_is_rejected(self) -> None:
        payload = self.payload()
        del payload["tests_baseline"]
        self.assert_rejected(payload)

    def test_missing_tower_tests_baseline_is_rejected(self) -> None:
        payload = self.payload()
        del payload["tower_tests_baseline"]
        self.assert_rejected(payload)

    def test_invalid_baseline_values_are_rejected(self) -> None:
        # ``True`` is an ``int`` in Python, so the gate must exclude ``bool``;
        # ``"2"`` and ``1.0`` are the plausible-but-wrong JSON types.
        for field in ("tests_baseline", "tower_tests_baseline"):
            for bad in (0, -1, True, "2", 1.0):
                with self.subTest(field=field, value=bad):
                    self.assert_rejected(self.payload(**{field: bad}))

    # -- acceptance ------------------------------------------------------
    def test_valid_baselines_create_draft_and_ledger_event(self) -> None:
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        self.assertEqual(payload["envelope"], ENVELOPE)
        written = self.envelope_path()
        self.assertTrue(written.exists(), msg=cp.stdout)
        envelope = read_json(written)
        self.assertEqual(envelope["status"], "DRAFT")
        self.assertEqual(envelope["tests_baseline"], 1)
        self.assertEqual(envelope["tower_tests_baseline"], 1)
        events = [json.loads(line) for line in self.supervision_ledger().splitlines()
                  if line.strip()]
        created = [e for e in events if e.get("type") == "ENVELOPE_NEW"]
        self.assertEqual(len(created), 1, msg=self.supervision_ledger())
        self.assertEqual(created[0]["payload"]["envelope"], ENVELOPE)
        self.assertEqual(self.record()["status"], "accepted")

    # -- queue-add gate (PILOT-030) --------------------------------------
    def test_queue_add_rejects_handwritten_missing_tests_baseline(self) -> None:
        self.assert_queue_rejected("tests_baseline")

    def test_queue_add_rejects_handwritten_missing_tower_tests_baseline(self) -> None:
        self.assert_queue_rejected("tower_tests_baseline")

    def test_queue_add_accepts_handwritten_valid_baselines(self) -> None:
        self.write_handwritten_envelope()
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        self.assertEqual(payload["status"], "WAITING")
        entries = [e for e in self.queue_entries()
                   if e.get("envelope_id") == ENVELOPE]
        self.assertEqual(len(entries), 1, msg=self.queue_entries())
        self.assertEqual(entries[0]["status"], "WAITING")
        events = self.queue_events()
        self.assertEqual(len(events), 1, msg=self.supervision_ledger())
        self.assertEqual(events[0]["payload"]["envelope"], ENVELOPE)

    def test_queue_add_accepts_envelope_created_by_envelope_new(self) -> None:
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["ok"], msg=cp.stdout)
        entries = [e for e in self.queue_entries()
                   if e.get("envelope_id") == ENVELOPE]
        self.assertEqual(len(entries), 1, msg=self.queue_entries())
        self.assertEqual(entries[0]["status"], "WAITING")
        self.assertEqual(len(self.queue_events()), 1,
                         msg=self.supervision_ledger())

    def test_duplicate_queue_add_is_still_rejected(self) -> None:
        self.write_handwritten_envelope()
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        queue_before = self.queue_bytes()
        ledger_before = self.supervision_ledger_bytes()
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        # A ledger-backed entry is a real duplicate, not a half-write.
        self.assertIn("already queued", cp.stdout + cp.stderr)
        self.assertEqual(self.queue_bytes(), queue_before)
        self.assertEqual(self.supervision_ledger_bytes(), ledger_before)
        self.assertEqual(len(self.queue_entries()), 1, msg=self.queue_entries())
        self.assertEqual(len(self.queue_events()), 1,
                         msg=self.supervision_ledger())

    # -- half-written queue window repair (PILOT-035) --------------------
    def test_queue_add_repairs_half_written_queue_entry(self) -> None:
        # Crash residue: the queue entry landed, the ``QUEUE_ADD`` event did
        # not.  ``state-verify`` reports ``queue_unbacked`` and the old retry
        # refused the entry as a duplicate forever.
        self.write_handwritten_envelope()
        self.handwrite_queue_entry()
        self.assertEqual(self.queue_events(), [])
        before = run_cli(self.root, "state-verify")
        self.assertEqual(before.returncode, 2,
                         msg=before.stdout + before.stderr)
        self.assertIn({"kind": "queue_unbacked", "target": ENVELOPE,
                       "expected": "QUEUE_ADD ledger event",
                       "actual": "no lifecycle events"},
                      json.loads(before.stdout)["drift"])

        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        self.assertEqual(payload["envelope"], ENVELOPE)
        self.assertEqual(payload["status"], "WAITING")
        self.assertIs(payload.get("repaired"), True, msg=cp.stdout)
        # Exactly one new event backs the existing entry; the entry itself is
        # neither duplicated nor rewritten.
        events = self.queue_events()
        self.assertEqual(len(events), 1, msg=self.supervision_ledger())
        self.assertEqual(events[0]["payload"]["envelope"], ENVELOPE)
        self.assertEqual(events[0]["payload"]["task"], TASK)
        entries = self.queue_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        self.assertEqual(entries[0]["envelope_id"], ENVELOPE)
        self.assertEqual(entries[0]["status"], "WAITING")
        # The repair clears the exact drift it was written for.
        after = run_cli(self.root, "state-verify")
        kinds = [row["kind"] for row in json.loads(after.stdout)["drift"]]
        self.assertNotIn("queue_unbacked", kinds, msg=after.stdout)

    def test_queue_add_repair_still_requires_baselines(self) -> None:
        # The repair sits behind the same baseline gate as a first-time add: a
        # half-written entry whose envelope lacks a baseline stays rejected and
        # appends neither an event nor a second entry.
        self.write_handwritten_envelope(missing="tower_tests_baseline")
        self.handwrite_queue_entry()
        queue_before = self.queue_bytes()
        ledger_before = self.supervision_ledger_bytes()

        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        blob = cp.stdout + cp.stderr
        self.assertIn("tests_baseline", blob)
        self.assertIn("tower_tests_baseline", blob)
        self.assertIn("int >= 1", blob)
        self.assertEqual(self.queue_bytes(), queue_before)
        self.assertEqual(self.supervision_ledger_bytes(), ledger_before)
        self.assertEqual(self.queue_events(), [])
        entries = self.queue_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        self.assertEqual(entries[0]["status"], "WAITING")

    # -- ledger-backed queue requirement (PILOT-033) ---------------------
    def handwrite_queue_entry(self) -> None:
        """Queue the envelope by editing ``MERGE_QUEUE.json`` directly."""
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": ENVELOPE, "task": TASK,
                "branch": BRANCH, "base": "main",
                "status": "WAITING", "added_at": FIXED_TIME,
            }],
        })

    def test_handwritten_queue_entry_fails_merge_check(self) -> None:
        # New-style envelope (both baselines) with no ENVELOPE_NEW and a queue
        # row with no QUEUE_ADD: every file-level check passes, so only the
        # two ledger lifecycle checks can reject the hand-written bypass.
        self.write_handwritten_envelope()
        self.handwrite_queue_entry()
        self.assertNotIn("QUEUE_ADD", self.supervision_ledger())
        self.assertNotIn("ENVELOPE_NEW", self.supervision_ledger())

        cp = run_cli(self.root, "merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        # PILOT-034 adds the lifecycle gate: a hand-written envelope never
        # produced ENVELOPE_NEW either, so both ledger checks fail.
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded",
                          "queue entry backed by ledger"])
        details = {c["name"]: c["detail"] for c in payload["errors"]}
        self.assertEqual(details["envelope_new recorded"],
                         "ENVELOPE_NEW event missing")
        self.assertEqual(details["queue entry backed by ledger"],
                         "QUEUE_ADD event missing")

    def test_handwritten_queue_entry_blocks_merge(self) -> None:
        self.write_handwritten_envelope()
        self.handwrite_queue_entry()

        cp = run_cli(self.root, "merge", "--role", "supervisor",
                     "--supervisor", "sup-1", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded",
                          "queue entry backed by ledger"])
        # The shared check fails before any git merge: the entry is marked for
        # correction and never reaches MERGING/MERGED.
        self.assertEqual(self.queue_entries()[0]["status"], "CORRECTION_REQUIRED")
        self.assertNotIn(read_json(self.envelope_path())["status"],
                         ("MERGED", "POST_MERGE_VERIFIED"))
        self.assertIn("MERGE_BLOCKED", self.supervision_ledger())
        self.assertNotIn("MERGE_START", self.supervision_ledger())

    def test_queue_add_backs_merge_check(self) -> None:
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(len(self.queue_events()), 1,
                         msg=self.supervision_ledger())

        cp = run_cli(self.root, "merge-check", "--envelope", ENVELOPE)

        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        checks = {c["name"]: c for c in payload["checks"]}
        self.assertTrue(checks["envelope identity matches request"]["ok"],
                        msg=cp.stdout)
        self.assertTrue(checks["ledger chain intact"]["ok"], msg=cp.stdout)
        self.assertEqual(checks["ledger chain intact"]["detail"], "ok")
        self.assertTrue(checks["envelope_new recorded"]["ok"], msg=cp.stdout)
        self.assertEqual(checks["envelope_new recorded"]["detail"],
                         "ENVELOPE_NEW event present")
        check = checks["queue entry backed by ledger"]
        self.assertTrue(check["ok"])
        self.assertEqual(check["detail"], "QUEUE_ADD event present")

    # -- self-verifying merge gate (PILOT-034) ---------------------------
    def append_forged_queue_add(self, envelope: str = ENVELOPE) -> None:
        """Append a parsed-but-unchained ``QUEUE_ADD`` row to the ledger.

        The row names the envelope and carries the correct ``seq``/``prev_hash``
        so only the hash chain itself betrays the forgery.
        """
        path = self.root / "ledger" / "supervision.jsonl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        event = {
            "seq": (rows[-1].get("seq", 0) + 1) if rows else 1,
            "at": FIXED_TIME,
            "type": "QUEUE_ADD",
            "actor": "primary",
            "payload": {"envelope": envelope, "task": TASK},
            "prev_hash": (rows[-1].get("hash") if rows else None) or "GENESIS",
            "hash": "f" * 64,
        }
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def test_forged_queue_add_row_fails_ledger_chain_check(self) -> None:
        # A forged row can name the envelope and satisfy the queue-backed
        # check; only chain verification detects the tampering.
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.handwrite_queue_entry()
        self.append_forged_queue_add()

        cp = run_cli(self.root, "merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["ledger chain intact"])
        detail = payload["errors"][0]["detail"]
        self.assertTrue(detail.startswith("supervision: "), msg=detail)
        self.assertIn("hash mismatch", detail)

        # The same tower, read by the ledger verifier: same verdict.
        cp = run_cli(self.root, "verify-ledger", "--ledger", "supervision")
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertFalse(json.loads(cp.stdout)["ok"])

        # merge refuses on the same broken chain and never starts merging.
        cp = run_cli(self.root, "merge", "--role", "supervisor",
                     "--supervisor", "sup-1", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertIn("ledger chain intact", cp.stdout)
        self.assertNotIn("MERGE_START", self.supervision_ledger())

    def test_queue_add_without_envelope_new_fails_merge_check(self) -> None:
        # ``queue-add`` appends a perfectly valid QUEUE_ADD but cannot
        # manufacture ENVELOPE_NEW: queueing a hand-written envelope is not
        # enough to pass the merge gate.
        self.write_handwritten_envelope()
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("QUEUE_ADD", self.supervision_ledger())
        self.assertNotIn("ENVELOPE_NEW", self.supervision_ledger())

        cp = run_cli(self.root, "merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual([c["name"] for c in payload["errors"]],
                         ["envelope_new recorded"])
        self.assertEqual(payload["errors"][0]["detail"],
                         "ENVELOPE_NEW event missing")

    def test_copied_envelope_identity_is_rejected(self) -> None:
        # Copy a fully backed envelope's JSON under a new filename/id: the
        # file content still names the original, and the requested id is
        # authoritative.
        cp = run_cli(self.root, "envelope-new", "--task", TASK,
                     "--file", str(self.envelope_file))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = run_cli(self.root, "queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        copy_id = "ENV-COPY-001"
        write_json(self.envelope_path(copy_id), read_json(self.envelope_path()))
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        queue["entries"].append({
            "envelope_id": copy_id, "task": TASK,
            "branch": BRANCH, "base": "main",
            "status": "WAITING", "added_at": FIXED_TIME,
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", queue)

        cp = run_cli(self.root, "merge-check", "--envelope", copy_id)
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        # The command-level identity gate fires before any check, so the only
        # error is a string naming the declared id and the requested id.
        blob = json.dumps(payload)
        self.assertIn("envelope identity matches request", blob)
        self.assertIn(ENVELOPE, blob)
        self.assertIn(copy_id, blob)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIsInstance(payload["errors"][0], str)

    def test_identity_check_names_both_ids_when_called_directly(self) -> None:
        # Direct callers pass ``expected_id``; the same binding is a check.
        env = self.payload()
        env.update({"envelope_head_sha": self.envelope_head, "status": "DRAFT"})
        checks = towerctl.envelope_checks(self.root, env,
                                          expected_id="ENV-OTHER-001")
        identity = next(c for c in checks
                        if c["name"] == "envelope identity matches request")
        self.assertFalse(identity["ok"])
        self.assertIn(ENVELOPE, identity["detail"])
        self.assertIn("ENV-OTHER-001", identity["detail"])

        # Without an expected id the check is absent (legacy direct callers).
        names = [c["name"] for c in towerctl.envelope_checks(self.root, env)]
        self.assertNotIn("envelope identity matches request", names)

    # -- legacy compatibility -------------------------------------------
    def test_legacy_envelope_without_baselines_still_merge_checks(self) -> None:
        # Written directly on purpose: envelope-new would refuse it, but an
        # envelope that predates the requirement must keep working.
        write_json(self.envelope_path(LEGACY_ENVELOPE), {
            "schema": "tower/merge-envelope@1",
            "envelope_id": LEGACY_ENVELOPE,
            "task": TASK,
            "repository": "..",
            "branch": BRANCH,
            "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head,
            "status": "DRAFT",
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{
                "envelope_id": LEGACY_ENVELOPE, "task": TASK,
                "branch": BRANCH, "base": "main",
                "status": "WAITING", "added_at": FIXED_TIME,
            }],
        })
        cp = run_cli(self.root, "merge-check", "--envelope", LEGACY_ENVELOPE)
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], msg=cp.stdout)
        self.assertNotIn("int >= 1", cp.stdout)
        self.assertNotIn("tests_baseline", cp.stdout)
        # Legacy envelopes keep the old opt-in semantics: the three new-style
        # ledger checks are not injected when the baselines are absent.  The
        # identity binding (a CLI-level requirement) still applies.
        names = [c["name"] for c in payload["checks"]]
        for name in ("ledger chain intact", "envelope_new recorded",
                     "queue entry backed by ledger"):
            self.assertNotIn(name, names)
        identity = next(c for c in payload["checks"]
                        if c["name"] == "envelope identity matches request")
        self.assertTrue(identity["ok"])


if __name__ == "__main__":
    unittest.main()
