"""PILOT-079: ``ledger_guard`` pins ledger history to the git base commit.

``verify-ledger`` only proves the current files hash-chain correctly, so an
attacker who rewrites row 1 and re-derives every ``hash``/``prev_hash`` passes
it.  ``tools/ledger_guard.py`` closes that seam by comparing bytes against the
``--base`` commit: every ``ledger/*.jsonl`` must be a **byte-prefix extension**
of the base blob, no ledger file may be deleted, no ledger file may be added.

These tests build a throw-away git kit (``<tmp>/kit/tower-dsh``) instead of
touching the real tower, then drive the real CLI in a subprocess:

* unchanged and pure-append ledgers exit 0;
* rewritten history exits 2 even when the tampered file is re-hashed with the
  tower's own ``event_hash`` so ``verify-ledger`` would see a valid chain;
* truncated (whole-row, mid-row and 0-byte) ledgers exit 2;
* a deleted ledger file and a brand-new ledger file both exit 2;
* a base commit without ledger files, and an unresolvable base ref, fail
  closed instead of silently passing;
* the default base is ``origin/main`` (the CI invocation) and the guard is
  read-only.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_ledger_guard -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
GUARD = TOOLS_DIR / "ledger_guard.py"
LEDGER = "ledger"
PRIMARY = "primary.jsonl"
SUPERVISION = "supervision.jsonl"
FIXED_TIME = "2026-11-20T00:00:00+08:00"
BRANCH = "feature/ledger-guard-079"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

sys.path.insert(0, str(TOOLS_DIR))
import tower_ledger  # noqa: E402  (import after sys.path setup)


def chained_events(types: tuple[str, ...], payloads: list[dict] | None = None) -> list[dict]:
    """Build a self-consistent ledger chain with the tower's own algorithm."""
    events: list[dict] = []
    prev = tower_ledger.GENESIS_PREV_HASH
    for index, event_type in enumerate(types, start=1):
        payload = payloads[index - 1] if payloads else {"n": index}
        event = {
            "seq": index,
            "at": FIXED_TIME,
            "type": event_type,
            "actor": "primary",
            "payload": payload,
            "prev_hash": prev,
        }
        event["hash"] = tower_ledger.event_hash(event)
        prev = event["hash"]
        events.append(event)
    return events


def ledger_bytes(events: list[dict]) -> bytes:
    """Serialize rows exactly like ``append_ledger`` does (LF terminator)."""
    return b"".join(
        (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        for event in events)


BASE_PRIMARY = chained_events(("SEED_A", "SEED_B"))
BASE_SUPERVISION = chained_events(("SUP_A",), payloads=[{"supervision": 1}])


class LedgerGuardTestCase(unittest.TestCase):
    """A kit repository: ``kit/tower-dsh/ledger`` on a feature branch off main."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="ledger-guard-079-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        (self.root / LEDGER).mkdir(parents=True, exist_ok=True)
        self.init_repo()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixtures --------------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(["git", "-C", str(self.kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              env=env)

    def commit(self, message: str) -> str:
        add = self.git("add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def init_repo(self) -> None:
        self.assertEqual(self.git("init").returncode, 0)
        self.assertEqual(
            self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("kit\n", encoding="utf-8")
        self.skeleton_head = self.commit("skeleton")
        self.write_ledger(BASE_PRIMARY, BASE_SUPERVISION)
        self.base_head = self.commit("base ledger")
        self.assertEqual(self.git("checkout", "-b", BRANCH).returncode, 0)

    def ledger_path(self, name: str) -> Path:
        return self.root / LEDGER / name

    def write_ledger(self, primary: list[dict] | bytes,
                     supervision: list[dict] | bytes) -> None:
        for name, content in ((PRIMARY, primary), (SUPERVISION, supervision)):
            data = content if isinstance(content, bytes) else ledger_bytes(content)
            self.ledger_path(name).write_bytes(data)

    def primary_bytes(self) -> bytes:
        return self.ledger_path(PRIMARY).read_bytes()

    def run_guard(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(GUARD), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env)

    def guard_json(self, *args: str) -> tuple[int, dict]:
        cp = self.run_guard(*args)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr,
                         msg=f"guard crashed:\n{cp.stdout}\n{cp.stderr}")
        try:
            payload = json.loads(cp.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
            self.fail(f"guard emitted non-JSON stdout={cp.stdout!r} "
                      f"stderr={cp.stderr!r}: {exc}")
        return cp.returncode, payload

    def assert_fails_closed(self, args: tuple[str, ...], kind: str) -> dict:
        code, payload = self.guard_json(*args)
        self.assertEqual(code, 2, msg=json.dumps(payload, indent=2))
        self.assertFalse(payload["ok"], payload)
        self.assertTrue(payload["errors"], payload)
        self.assertIn(kind, {item["kind"] for item in payload["errors"]},
                      msg=json.dumps(payload, indent=2))
        return payload

    # -- 1. the happy path ------------------------------------------------
    def test_unchanged_ledger_passes(self) -> None:
        code, payload = self.guard_json("--base", "main")
        self.assertEqual(code, 0, msg=json.dumps(payload, indent=2))
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["base"], "main")
        self.assertEqual(payload["base_commit"], self.base_head)
        self.assertEqual(payload["errors"], [])
        self.assertEqual([check["path"] for check in payload["checks"]],
                         [f"tower-dsh/{LEDGER}/{PRIMARY}",
                          f"tower-dsh/{LEDGER}/{SUPERVISION}"])
        self.assertTrue(all(check["ok"] for check in payload["checks"]))
        self.assertTrue(all(check["detail"] == "unchanged"
                            for check in payload["checks"]))

    def test_pure_append_passes(self) -> None:
        appended = chained_events(("SEED_A", "SEED_B", "APPEND_C"))
        self.ledger_path(PRIMARY).write_bytes(ledger_bytes(appended))
        self.commit("append event")

        code, payload = self.guard_json("--base", "main")
        self.assertEqual(code, 0, msg=json.dumps(payload, indent=2))
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["errors"], [])
        primary = [check for check in payload["checks"]
                   if check["path"].endswith(PRIMARY)][0]
        self.assertTrue(primary["ok"], primary)
        self.assertEqual(primary["base_bytes"],
                         len(ledger_bytes(BASE_PRIMARY)))
        self.assertEqual(primary["current_bytes"], len(ledger_bytes(appended)))
        self.assertIn("pure append", primary["detail"])

    # -- 2. rewritten history, even when re-hashed ------------------------
    def test_rewritten_history_fails_even_when_rehashed(self) -> None:
        # The audit scenario: edit a historical row, then recompute the whole
        # hash chain.  ``verify-ledger`` would accept this file.
        tampered = chained_events(("SEED_A", "SEED_B"),
                                  payloads=[{"n": 999}, {"n": 2}])
        tampered_bytes = ledger_bytes(tampered)
        self.ledger_path(PRIMARY).write_bytes(tampered_bytes)
        self.commit("rewrite and rehash")

        # The tampered file is a valid chain under the tower's own algorithm:
        # recorded hashes match a fresh re-derivation.
        prev = tower_ledger.GENESIS_PREV_HASH
        for event in tampered:
            self.assertEqual(event["prev_hash"], prev, msg=event)
            self.assertEqual(event["hash"], tower_ledger.event_hash(event))
            prev = event["hash"]
        self.assertNotEqual(tampered_bytes, ledger_bytes(BASE_PRIMARY))

        payload = self.assert_fails_closed(("--base", "main"), "history")
        self.assertEqual(len(payload["errors"]), 1, payload)
        detail = payload["errors"][0]["detail"]
        self.assertIn("not a byte-prefix", detail)
        self.assertIn("byte-prefix extension of the base blob", detail)
        check = [item for item in payload["checks"]
                 if item["path"].endswith(PRIMARY)][0]
        self.assertFalse(check["ok"], check)

    def test_rewriting_one_byte_is_refused(self) -> None:
        original = self.primary_bytes()
        tampered = bytearray(original)
        tampered[len(tampered) // 2] ^= 0xFF
        self.ledger_path(PRIMARY).write_bytes(bytes(tampered))
        self.commit("flip one byte")

        self.assert_fails_closed(("--base", "main"), "history")

    # -- 3. truncation ----------------------------------------------------
    def test_truncated_rows_are_refused(self) -> None:
        first_row = ledger_bytes(BASE_PRIMARY).split(b"\n", 1)[0] + b"\n"
        self.ledger_path(PRIMARY).write_bytes(first_row)
        self.commit("drop trailing rows")

        payload = self.assert_fails_closed(("--base", "main"), "history")
        self.assertIn("truncated", payload["errors"][0]["detail"])
        self.assertIn("base_bytes", payload["checks"][0])

    def test_mid_row_truncation_is_refused(self) -> None:
        original = self.primary_bytes()
        self.ledger_path(PRIMARY).write_bytes(original[:-7])
        self.commit("cut mid-row")

        payload = self.assert_fails_closed(("--base", "main"), "history")
        self.assertIn("truncated", payload["errors"][0]["detail"])

    def test_zero_byte_truncation_is_refused(self) -> None:
        self.ledger_path(PRIMARY).write_bytes(b"")
        self.commit("truncate to zero")

        payload = self.assert_fails_closed(("--base", "main"), "history")
        self.assertIn("truncated", payload["errors"][0]["detail"])

    # -- 4. deletion / addition ------------------------------------------
    def test_deleted_ledger_file_is_refused(self) -> None:
        self.ledger_path(SUPERVISION).unlink()
        self.commit("delete supervision ledger")

        payload = self.assert_fails_closed(("--base", "main"), "deleted")
        self.assertIn(f"tower-dsh/{LEDGER}/{SUPERVISION}",
                      payload["errors"][0]["path"])
        self.assertIn("deleted", payload["errors"][0]["detail"])

    def test_removing_the_ledger_directory_is_refused(self) -> None:
        for name in (PRIMARY, SUPERVISION):
            self.ledger_path(name).unlink()
        self.ledger_path(PRIMARY).parent.rmdir()
        self.commit("remove ledger directory")

        payload = self.assert_fails_closed(("--base", "main"), "deleted")
        self.assertEqual({item["kind"] for item in payload["errors"]},
                         {"deleted"})

    def test_new_ledger_file_is_refused(self) -> None:
        added = chained_events(("EXTRA_A",))
        (self.root / LEDGER / "extra.jsonl").write_bytes(ledger_bytes(added))
        self.commit("add a brand-new ledger file")

        payload = self.assert_fails_closed(("--base", "main"), "new")
        self.assertEqual(len(payload["errors"]), 1, payload)
        self.assertIn("new ledger file refused", payload["errors"][0]["detail"])
        self.assertIn("extra.jsonl", payload["errors"][0]["path"])

    # -- 5. fail closed when the base cannot testify ----------------------
    def test_base_without_ledger_files_refuses_every_ledger_file(self) -> None:
        # ``main~1`` is the skeleton commit, before ledger/ existed at all:
        # every current ledger file is "new" against that base.
        payload = self.assert_fails_closed(
            ("--base", "main~1"), "new")
        self.assertEqual({item["kind"] for item in payload["errors"]}, {"new"})
        self.assertEqual(len(payload["errors"]), 2, payload)

    def test_unresolvable_base_ref_fails_closed(self) -> None:
        payload = self.assert_fails_closed(("--base", "origin/nope"), "guard")
        self.assertIn("cannot be resolved", payload["errors"][0]["detail"])
        self.assertIn("never contacts a remote", payload["errors"][0]["detail"])

    def test_not_a_git_repository_fails_closed(self) -> None:
        outside = Path(self._tmp.name) / "not-a-repo"
        (outside / LEDGER).mkdir(parents=True)
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        cp = subprocess.run(
            [sys.executable, "-B", str(GUARD), "--root", str(outside),
             "--base", "main"],
            capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertIn("guard", {item["kind"] for item in payload["errors"]})

    # -- 6. the CI invocation and read-only behaviour ---------------------
    def test_default_base_is_origin_main(self) -> None:
        self.assertEqual(
            self.git("update-ref", "refs/remotes/origin/main",
                     self.base_head).returncode, 0)
        appended = chained_events(("SEED_A", "SEED_B", "APPEND_C"))
        self.ledger_path(PRIMARY).write_bytes(ledger_bytes(appended))
        self.commit("append event")

        code, payload = self.guard_json()
        self.assertEqual(code, 0, msg=json.dumps(payload, indent=2))
        self.assertEqual(payload["base"], "origin/main")
        self.assertEqual(payload["base_commit"], self.base_head)

    def test_guard_does_not_modify_the_ledger(self) -> None:
        before = {name: self.ledger_path(name).read_bytes()
                  for name in (PRIMARY, SUPERVISION)}
        code, _ = self.guard_json("--base", "main")
        self.assertEqual(code, 0)
        after = {name: self.ledger_path(name).read_bytes()
                 for name in (PRIMARY, SUPERVISION)}
        self.assertEqual(after, before,
                         msg="the guard must be read-only")

        # A failed run must not repair or rewrite anything either.
        self.ledger_path(PRIMARY).write_bytes(before[PRIMARY][:-3])
        tampered = self.ledger_path(PRIMARY).read_bytes()
        self.assertEqual(self.guard_json("--base", "main")[0], 2)
        self.assertEqual(self.ledger_path(PRIMARY).read_bytes(), tampered)


if __name__ == "__main__":
    unittest.main()
