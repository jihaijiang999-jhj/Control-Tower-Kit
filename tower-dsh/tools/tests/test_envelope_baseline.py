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
        # "already queued" keeps priority over the baseline gate.
        self.assertIn("already queued", cp.stdout + cp.stderr)
        self.assertEqual(self.queue_bytes(), queue_before)
        self.assertEqual(self.supervision_ledger_bytes(), ledger_before)
        self.assertEqual(len(self.queue_entries()), 1, msg=self.queue_entries())
        self.assertEqual(len(self.queue_events()), 1,
                         msg=self.supervision_ledger())

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


if __name__ == "__main__":
    unittest.main()
