"""PILOT-037: one registered merge authority (``state/AUTHORITY.json``).

The file is not the authority: the last ``AUTHORITY_SET`` event in
``ledger/primary.jsonl`` is, and the file must repeat its payload field for
field.  ``authority-set`` is the only writer: it refuses a caller that is not
the registered owner and a supervisor that is not the registered supervisor,
and it writes nothing on refusal.  ``merge`` then pins ``--supervisor`` to the
registered ``merge_authority``; a missing, unbacked or mismatched state fails
closed before the queue is even read.  A tower with neither half stays
``legacy`` so old fixtures and old towers keep working.

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
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"

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


class AuthorityStateTestCase(unittest.TestCase):
    """A tower with one primary, one supervision state and a merge branch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-authority-state-", ignore_cleanup_errors=True)
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
            "title": "authority state",
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

    def authority_path(self) -> Path:
        return self.root / AUTHORITY_FILE

    def authority_state(self) -> dict:
        return read_json(self.authority_path())

    def primary_events(self) -> list[dict]:
        path = self.root / "ledger" / "primary.jsonl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def authority_events(self) -> list[dict]:
        return [event for event in self.primary_events()
                if event.get("type") == "AUTHORITY_SET"]

    def supervision_ledger(self) -> str:
        path = self.root / "ledger" / "supervision.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def queue_entries(self) -> list[dict]:
        return read_json(self.root / "supervision" / "MERGE_QUEUE.json")["entries"]

    def write_queue(self, entries: list[dict]) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": entries})

    def queue_entry(self) -> dict:
        return self.queue_entries()[0]

    def write_authority_file(self, **overrides) -> None:
        """Hand-write a file that claims authority without a ledger event."""
        data = {
            "schema": "tower/authority-state@1",
            "tower_id": "tower-dsh",
            "owner": "mac",
            "primary": {"id": PRIMARY_ID},
            "supervision": {"id": SUPERVISOR_ID},
            "merge_authority": SUPERVISOR_ID,
            "revision": 1,
            "set_by": "mac",
            "decision": "D-X",
            "set_at": FIXED_TIME,
        }
        data.update(overrides)
        write_json(self.authority_path(), data)

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

    def assert_zero_writes(self) -> None:
        self.assertFalse(self.authority_path().exists(),
                         msg="a rejected authority-set must not write the file")
        self.assertEqual(self.authority_events(), [],
                         msg="a rejected authority-set must not append an event")

    def find_check(self, payload: dict, needle: str) -> dict:
        for check in payload["checks"]:
            if needle in check["name"]:
                return check
        self.fail(f"no check containing {needle!r} in {payload['checks']}")

    # -- 1. the happy path ------------------------------------------------
    def test_authority_set_writes_file_and_exactly_one_event(self) -> None:
        cp = self.run_cli("authority-set", "--supervisor", SUPERVISOR_ID,
                          "--decision", "D-X", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["path"], AUTHORITY_FILE)
        self.assertEqual(out["revision"], 1)
        self.assertEqual(out["merge_authority"], SUPERVISOR_ID)

        state = self.authority_state()
        self.assertEqual(state["schema"], "tower/authority-state@1")
        self.assertEqual(state["tower_id"], "tower-dsh")
        self.assertEqual(state["owner"], "mac")
        self.assertEqual(state["primary"], {"id": PRIMARY_ID})
        self.assertEqual(state["supervision"], {"id": SUPERVISOR_ID})
        self.assertEqual(state["merge_authority"], SUPERVISOR_ID)
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["set_by"], "mac")
        self.assertEqual(state["decision"], "D-X")

        events = self.authority_events()
        self.assertEqual(len(events), 1, msg=events)
        payload = events[0]["payload"]
        self.assertEqual(payload["owner"], "mac")
        self.assertEqual(payload["primary_id"], PRIMARY_ID)
        self.assertEqual(payload["supervision_id"], SUPERVISOR_ID)
        self.assertEqual(payload["merge_authority"], SUPERVISOR_ID)
        self.assertEqual(payload["revision"], 1)
        self.assertEqual(payload["set_by"], "mac")
        self.assertEqual(payload["decision"], "D-X")
        self.assertEqual(payload["set_at"], state["set_at"])

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        self.assertTrue(all(item["ok"] for item in check["checks"]), check)

    # -- 2-4. refusals write nothing --------------------------------------
    def test_authority_set_rejects_non_owner(self) -> None:
        ledger_before = (self.root / "ledger" / "primary.jsonl").read_bytes()

        cp = self.run_cli("authority-set", "--supervisor", SUPERVISOR_ID,
                          "--decision", "D-X", "--by", "mallory")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = cp.stdout + cp.stderr
        self.assertIn("mallory", blob)
        self.assertIn("owner", blob)
        self.assert_zero_writes()
        self.assertEqual(
            (self.root / "ledger" / "primary.jsonl").read_bytes(),
            ledger_before)

    def test_authority_set_rejects_primary_id_as_supervisor(self) -> None:
        cp = self.run_cli("authority-set", "--supervisor", PRIMARY_ID,
                          "--decision", "D-X", "--by", "mac")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("must differ from primary.id", cp.stdout)
        self.assert_zero_writes()

    def test_authority_set_rejects_unregistered_supervisor(self) -> None:
        cp = self.run_cli("authority-set", "--supervisor", "sup-rogue",
                          "--decision", "D-X", "--by", "mac")

        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("sup-rogue", cp.stdout)
        self.assertIn(SUPERVISOR_ID, cp.stdout)
        self.assert_zero_writes()

    # -- 5. tampering the file is a mismatch ------------------------------
    def test_tampered_merge_authority_fails_check_and_state_verify(self) -> None:
        self.assertEqual(self.run_cli(
            "authority-set", "--supervisor", SUPERVISOR_ID,
            "--decision", "D-X", "--by", "mac").returncode, 0)
        state = self.authority_state()
        state["merge_authority"] = "sup-rogue"
        write_json(self.authority_path(), state)

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertEqual(check["status"], "configured")
        mismatch = self.find_check(check, "matches last AUTHORITY_SET")
        self.assertFalse(mismatch["ok"], mismatch)
        self.assertIn("sup-rogue", mismatch["detail"])

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in out["drift"]],
                         ["authority_mismatch"])
        drift = out["drift"][0]
        self.assertEqual(drift["target"], "AUTHORITY")
        self.assertEqual(drift["expected"]["merge_authority"], SUPERVISOR_ID)
        self.assertEqual(drift["actual"]["merge_authority"], "sup-rogue")

    # -- 6. event without file: missing, merge blocked --------------------
    def test_deleted_file_is_missing_and_blocks_merge(self) -> None:
        self.assertEqual(self.run_cli(
            "authority-set", "--supervisor", SUPERVISOR_ID,
            "--decision", "D-X", "--by", "mac").returncode, 0)
        self.write_queue([{"envelope_id": ENVELOPE, "task": TASK,
                           "branch": BRANCH, "base": "main",
                           "status": "WAITING", "added_at": FIXED_TIME}])
        queue_before = (self.root / "supervision" /
                        "MERGE_QUEUE.json").read_bytes()
        self.authority_path().unlink()

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertIn("missing", json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertIn("authority_missing",
                      [item["kind"] for item in out["drift"]], msg=out)

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertIn("missing", json.dumps(payload["errors"]))
        # The queue is untouched and the merge never started.
        self.assertEqual(
            (self.root / "supervision" / "MERGE_QUEUE.json").read_bytes(),
            queue_before)
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        self.assertNotIn("MERGE_START", self.supervision_ledger())
        self.assertNotIn("MERGING", self.supervision_ledger())

    # -- 7. file without event: unbacked ----------------------------------
    def test_file_without_event_is_unbacked(self) -> None:
        self.write_authority_file()

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        self.assertFalse(check["ok"], check)
        self.assertIn("no AUTHORITY_SET event", json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in out["drift"]],
                         ["authority_unbacked"])

    # -- 8. configured tower pins the merge identity ----------------------
    def test_configured_tower_pins_merge_authority(self) -> None:
        self.assertEqual(self.run_cli(
            "authority-set", "--supervisor", SUPERVISOR_ID,
            "--decision", "D-X", "--by", "mac").returncode, 0)
        self.write_queue([{"envelope_id": ENVELOPE, "task": TASK,
                           "branch": BRANCH, "base": "main",
                           "status": "WAITING", "added_at": FIXED_TIME}])

        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", "rogue", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertIn("merge authority mismatch",
                      json.dumps(payload["errors"]))
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        self.assertNotIn("MERGE_START", self.supervision_ledger())

        # The registered id passes the identity gate and fails later, on the
        # missing envelope -- never on authority.
        cp = self.run_cli("merge", "--role", "supervisor",
                          "--supervisor", SUPERVISOR_ID,
                          "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = cp.stdout + cp.stderr
        self.assertNotIn("merge authority mismatch", blob)
        self.assertIn("envelope not found", blob)
        self.assertEqual(self.queue_entry()["status"], "WAITING")
        self.assertNotIn("MERGE_START", self.supervision_ledger())

        # merge-check reports the pin as an explicit ok=true check.
        self.write_legacy_envelope()
        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)
        pinned = self.find_check(check, "merge authority")
        self.assertTrue(pinned["ok"], pinned)
        self.assertIn(SUPERVISOR_ID, pinned["detail"])

    # -- 9. legacy tower keeps passing ------------------------------------
    def test_legacy_tower_merge_check_still_passes(self) -> None:
        self.write_legacy_envelope()
        self.write_queue([{"envelope_id": ENVELOPE, "task": TASK,
                           "branch": BRANCH, "base": "main",
                           "status": "WAITING", "added_at": FIXED_TIME}])

        cp = self.run_cli("merge-check", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"], payload)
        legacy = self.find_check(payload, "merge authority")
        self.assertTrue(legacy["ok"], legacy)
        self.assertEqual(legacy["detail"], "legacy: no AUTHORITY_SET")

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "legacy")

    # -- 10. re-running repairs an event without a file -------------------
    def test_rerun_repairs_event_without_file(self) -> None:
        self.assertEqual(self.run_cli(
            "authority-set", "--supervisor", SUPERVISOR_ID,
            "--decision", "D-X", "--by", "mac").returncode, 0)
        self.authority_path().unlink()

        cp = self.run_cli("authority-set", "--supervisor", SUPERVISOR_ID,
                          "--decision", "D-Y", "--by", "mac")

        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual(out["revision"], 2)
        state = self.authority_state()
        self.assertEqual(state["revision"], 2)
        self.assertEqual(state["decision"], "D-Y")
        events = self.authority_events()
        self.assertEqual(len(events), 2, msg=events)
        self.assertEqual(events[-1]["payload"]["revision"], 2)
        self.assertEqual(events[-1]["payload"]["decision"], "D-Y")

        check = self.cli_json("authority-check")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status"], "configured")

    # -- 11. an unreadable file is an audit failure, never a traceback -----
    def test_unreadable_file_is_reported_without_traceback(self) -> None:
        directory = self.root / "state" / "AUTHORITY.json"
        directory.mkdir(parents=True)

        cp = self.run_cli("authority-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        check = json.loads(cp.stdout)  # a traceback would not parse
        self.assertFalse(check["ok"], check)
        self.assertIn("not a parseable JSON object", json.dumps(check))

        cp = self.run_cli("state-verify")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual([item["kind"] for item in out["drift"]],
                         ["authority_unreadable"])


if __name__ == "__main__":
    unittest.main()
