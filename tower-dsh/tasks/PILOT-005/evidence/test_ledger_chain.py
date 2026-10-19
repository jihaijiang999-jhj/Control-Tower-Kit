"""Hash-chain, writer-lock and verify-ledger tests (PILOT-005).

Each test builds an isolated tower root with ``tempfile`` so the real tower
ledgers are never touched. Events are appended through the real
``towerctl`` functions (or the CLI for verification) with the writer lock
active, exactly as production appends behave.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)

GENESIS = "GENESIS"


def canonical_hash(event: dict) -> str:
    """Independent re-implementation of the documented canonical hash."""
    body = {k: v for k, v in event.items() if k != "hash"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class LedgerChainTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-ledger-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        self.ledger = self.root / "ledger" / "primary.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def append(self, i: int = 0) -> dict:
        return towerctl.append_ledger(
            self.root, "TEST", "executor", {"i": i})

    def events(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in
                self.ledger.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def write_events(self, events: list[dict]) -> None:
        self.ledger.write_text(
            "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events),
            encoding="utf-8", newline="\n")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def verify(self, ledger: str | None = None) -> tuple[dict, int]:
        args = ["verify-ledger"]
        if ledger is not None:
            args += ["--ledger", ledger]
        proc = self.run_cli(*args)
        return json.loads(proc.stdout), proc.returncode

    def assert_chain_ok(self, ledger: str | None = None) -> dict:
        out, code = self.verify(ledger)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["errors"], [])
        return out

    # -- 1. new events are hashed and verify -----------------------------
    def test_new_events_carry_valid_hash_chain(self) -> None:
        first = self.append(1)
        second = self.append(2)
        third = self.append(3)

        for event in (first, second, third):
            self.assertEqual(
                set(event),
                {"seq", "at", "type", "actor", "payload", "prev_hash", "hash"})
            self.assertEqual(event["hash"], canonical_hash(event))

        self.assertEqual(first["prev_hash"], GENESIS)
        self.assertEqual(second["prev_hash"], first["hash"])
        self.assertEqual(third["prev_hash"], second["hash"])
        self.assertEqual([first["seq"], second["seq"], third["seq"]], [1, 2, 3])

        out = self.assert_chain_ok()
        self.assertEqual(set(out["files"]), {"primary", "supervision"})
        self.assertEqual(out["files"]["primary"]["events"], 3)
        self.assertEqual(out["files"]["primary"]["legacy_unhashed"], 0)
        self.assertTrue(out["files"]["primary"]["exists"])

    # -- 2. payload tampering --------------------------------------------
    def test_tampered_payload_is_detected(self) -> None:
        self.append(1)
        self.append(2)
        events = self.events()
        events[1]["payload"] = {"i": 999}
        self.write_events(events)

        out, code = self.verify()
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("hash mismatch" in e
                            for e in out["files"]["primary"]["errors"]), out)

    # -- 3. hash tampering -----------------------------------------------
    def test_tampered_hash_is_detected(self) -> None:
        self.append(1)
        self.append(2)
        events = self.events()
        events[1]["hash"] = "0" * 64
        self.write_events(events)

        out, code = self.verify()
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("hash mismatch" in e
                            for e in out["files"]["primary"]["errors"]), out)

    # -- 4. prev_hash tampering (hash recomputed to isolate the check) ---
    def test_tampered_prev_hash_is_detected(self) -> None:
        self.append(1)
        self.append(2)
        events = self.events()
        events[1]["prev_hash"] = "f" * 64
        events[1]["hash"] = canonical_hash(events[1])
        self.write_events(events)

        out, code = self.verify()
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("prev_hash" in e
                            for e in out["files"]["primary"]["errors"]), out)

    # -- 5. deleted middle row -> seq gap --------------------------------
    def test_deleted_row_breaks_seq_continuity(self) -> None:
        for i in range(4):
            self.append(i)
        events = self.events()
        del events[1]
        self.write_events(events)

        out, code = self.verify()
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("seq" in e
                            for e in out["files"]["primary"]["errors"]), out)

    # -- 6. legacy prefix + new hashed events ----------------------------
    def test_legacy_prefix_is_counted_and_chained(self) -> None:
        legacy = [
            {"seq": 1, "at": "2026-10-19T00:00:00+08:00", "type": "INIT",
             "actor": "primary", "payload": {"note": "旧行-1"}},
            {"seq": 2, "at": "2026-10-19T00:00:01+08:00", "type": "TASK_NEW",
             "actor": "primary", "payload": {"note": "旧行-2"}},
            {"seq": 3, "at": "2026-10-19T00:00:02+08:00", "type": "DISPATCH",
             "actor": "primary", "payload": {"note": "旧行-3"}},
        ]
        self.write_events(legacy)
        anchor = hashlib.sha256(
            self.ledger.read_bytes().split(b"\n")[-2]).hexdigest()

        fourth = self.append(4)
        fifth = self.append(5)

        self.assertEqual(fourth["prev_hash"], anchor)
        self.assertEqual(fourth["seq"], 4)
        self.assertEqual(fifth["prev_hash"], fourth["hash"])

        out = self.assert_chain_ok()
        self.assertEqual(out["files"]["primary"]["events"], 5)
        self.assertEqual(out["files"]["primary"]["legacy_unhashed"], 3)

    # -- 7. concurrent writers keep seq and chain intact ------------------
    def test_concurrent_appends_keep_sequence_and_chain(self) -> None:
        workers, per_worker = 8, 5
        failures: list[BaseException] = []

        def work(worker: int) -> None:
            for i in range(per_worker):
                try:
                    towerctl.append_ledger(
                        self.root, "CONCURRENT", f"t{worker}", {"w": worker, "i": i})
                except BaseException as exc:  # noqa: BLE001 - collected below
                    failures.append(exc)

        threads = [threading.Thread(target=work, args=(n,))
                   for n in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "worker thread did not finish")
        self.assertEqual(failures, [])

        events = self.events()
        self.assertEqual(len(events), workers * per_worker)
        self.assertEqual([ev["seq"] for ev in events],
                         list(range(1, workers * per_worker + 1)))
        for previous, current in zip(events, events[1:]):
            self.assertEqual(current["prev_hash"], previous["hash"])
        self.assert_chain_ok()

    # -- 8. stale lock is cleaned up -------------------------------------
    def test_stale_lock_is_cleared(self) -> None:
        lock = self.root / "ledger" / ".lock"
        lock.write_text("stale\n", encoding="utf-8")
        old = time.time() - 120
        os.utime(lock, (old, old))

        event = self.append(1)
        self.assertEqual(event["seq"], 1)
        self.assertFalse(lock.exists())
        self.assert_chain_ok()

    # -- 9. a held lock times out instead of blocking forever ------------
    def test_held_lock_times_out(self) -> None:
        lock = self.root / "ledger" / ".lock"
        lock.write_text("busy\n", encoding="utf-8")
        old_timeout = towerctl.LEDGER_LOCK_TIMEOUT
        old_stale = towerctl.LEDGER_LOCK_STALE_AFTER
        try:
            towerctl.LEDGER_LOCK_TIMEOUT = 0.25
            towerctl.LEDGER_LOCK_STALE_AFTER = 60.0
            with self.assertRaises(towerctl.LedgerLockTimeout):
                self.append(1)
        finally:
            towerctl.LEDGER_LOCK_TIMEOUT = old_timeout
            towerctl.LEDGER_LOCK_STALE_AFTER = old_stale

        self.assertFalse(self.ledger.exists())
        self.assertTrue(lock.exists(), "someone else's lock must not be removed")

    # -- 10. unhashed row after the chain started is a failure -----------
    def test_unhashed_row_after_chain_start_is_detected(self) -> None:
        self.append(1)
        events = self.events()
        events.append({"seq": 2, "at": "2026-10-19T00:00:03+08:00",
                       "type": "LEGACY", "actor": "primary", "payload": {}})
        self.write_events(events)

        out, code = self.verify()
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("unhashed" in e
                            for e in out["files"]["primary"]["errors"]), out)

    # -- 11. supervision ledger uses the same chain ----------------------
    def test_supervision_ledger_chains(self) -> None:
        first = towerctl.append_supervision_ledger(
            self.root, "SUP", "supervision", {"i": 1})
        second = towerctl.append_supervision_ledger(
            self.root, "SUP", "supervision", {"i": 2})

        self.assertEqual(first["prev_hash"], GENESIS)
        self.assertEqual(second["prev_hash"], first["hash"])
        out = self.assert_chain_ok("supervision")
        self.assertEqual(out["files"]["supervision"]["events"], 2)
        self.assertEqual(out["files"]["supervision"]["legacy_unhashed"], 0)


if __name__ == "__main__":
    unittest.main()
