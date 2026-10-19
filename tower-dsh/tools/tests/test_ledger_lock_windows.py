"""Windows ledger-lock race regression tests (PILOT-006).

On Windows, ``os.open(..., O_CREAT | O_EXCL | O_WRONLY)`` can report a lock
file that another thread is currently deleting as ``PermissionError`` (errno
13, "Permission denied") instead of ``FileExistsError``.  These tests drive
the real ``towerctl`` writers with many threads to prove that this is treated
as lock contention, that the hash chain stays intact under load, and that
timeout / stale-lock recovery still behave correctly.

Every test builds an isolated tower root with ``tempfile``; the real tower
ledgers are never touched.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)

GENESIS = "GENESIS"
WORKERS = 8
PER_WORKER = 5
STRESS_ROUNDS = 20
BATCH_PER_WORKER = 20


def append_many(root: Path, workers: int, per_worker: int,
                event_type: str) -> list[tuple[int, int, str, str]]:
    """Run ``workers * per_worker`` concurrent appends; collect exceptions."""
    failures: list[tuple[int, int, str, str]] = []

    def work(worker: int) -> None:
        for index in range(per_worker):
            try:
                towerctl.append_ledger(
                    root, event_type, f"t{worker}", {"w": worker, "i": index})
            except BaseException as exc:  # noqa: BLE001 - reported by the test
                failures.append(
                    (worker, index, type(exc).__name__, str(exc)))

    threads = [threading.Thread(target=work, args=(worker,), daemon=True)
               for worker in range(workers)]
    for thread in threads:
        thread.start()
    for worker, thread in enumerate(threads):
        thread.join(timeout=60)
        if thread.is_alive():
            failures.append((worker, -1, "StuckThread",
                             "append worker did not finish within 60s"))
    return failures


def read_events(root: Path) -> list[dict]:
    path = root / "ledger" / "primary.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class LedgerLockWindowsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Keep the stress test comfortably inside its ~30s budget; the poll
        # interval affects latency only, never lock semantics.
        self._old_poll = towerctl.LEDGER_LOCK_POLL_INTERVAL
        towerctl.LEDGER_LOCK_POLL_INTERVAL = 0.005
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-lock-win-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        self.ledger = self.root / "ledger" / "primary.jsonl"

    def tearDown(self) -> None:
        towerctl.LEDGER_LOCK_POLL_INTERVAL = self._old_poll
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def verify(self) -> tuple[dict, int]:
        proc = self.run_cli("verify-ledger")
        return json.loads(proc.stdout), proc.returncode

    def assert_chain(self, events: list[dict], expected_count: int,
                     label: str) -> None:
        self.assertEqual(len(events), expected_count, label)
        self.assertEqual([event.get("seq") for event in events],
                         list(range(1, expected_count + 1)), label)
        previous = GENESIS
        for row_no, event in enumerate(events, 1):
            self.assertEqual(event.get("prev_hash"), previous,
                             f"{label}: row {row_no} prev_hash")
            self.assertEqual(event.get("hash"),
                             towerctl.event_hash(event),
                             f"{label}: row {row_no} hash")
            previous = event.get("hash")

    # -- 1. 20 rounds of 8 x 5 concurrent appends on fresh roots ---------
    def test_stress_20_rounds_of_concurrent_appends(self) -> None:
        started = time.monotonic()
        failures: list[tuple[int, list[tuple[int, int, str, str]]]] = []
        chain_problems: list[str] = []

        for round_no in range(1, STRESS_ROUNDS + 1):
            with tempfile.TemporaryDirectory(
                    prefix=f"towerctl-stress-{round_no:02d}-",
                    ignore_cleanup_errors=True) as tmp:
                root = Path(tmp)
                (root / "ledger").mkdir(parents=True, exist_ok=True)
                errors = append_many(root, WORKERS, PER_WORKER, "STRESS")
                if errors:
                    failures.append((round_no, errors))
                    continue

                events = read_events(root)
                expected = WORKERS * PER_WORKER
                if len(events) != expected:
                    chain_problems.append(
                        f"round {round_no}: {len(events)} events != {expected}")
                    continue
                if [event.get("seq") for event in events] != \
                        list(range(1, expected + 1)):
                    chain_problems.append(
                        f"round {round_no}: seq gap: "
                        f"{[event.get('seq') for event in events]}")
                    continue
                previous = GENESIS
                for row_no, event in enumerate(events, 1):
                    if event.get("prev_hash") != previous:
                        chain_problems.append(
                            f"round {round_no}: row {row_no} prev_hash")
                        break
                    if event.get("hash") != towerctl.event_hash(event):
                        chain_problems.append(
                            f"round {round_no}: row {row_no} hash mismatch")
                        break
                    previous = event.get("hash")
                report = towerctl.verify_ledger_file(root, "primary")
                if report["errors"]:
                    chain_problems.append(
                        f"round {round_no}: verify errors {report['errors']}")

        elapsed = time.monotonic() - started
        if failures:
            detail = "; ".join(
                f"round {round_no}: {len(errors)} failure(s), first="
                f"{errors[0]}" for round_no, errors in failures)
            self.fail(f"{len(failures)}/{STRESS_ROUNDS} rounds failed: {detail}")
        self.assertEqual(chain_problems, [], "chain/seq problems: "
                         + "; ".join(chain_problems))
        self.assertLess(elapsed, 30.0,
                        f"stress run took {elapsed:.1f}s, expected ~30s max")

    # -- 2. 8 x 20 = 160 concurrent events keep seq and the chain ---------
    def test_large_batch_160_appends_keeps_chain(self) -> None:
        failures = append_many(self.root, WORKERS, BATCH_PER_WORKER, "BATCH")
        self.assertEqual(failures, [])

        events = read_events(self.root)
        expected = WORKERS * BATCH_PER_WORKER
        self.assert_chain(events, expected, "batch")

        out, code = self.verify()
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["files"]["primary"]["events"], expected)

    # -- 3a. a held lock still times out --------------------------------
    def test_held_lock_still_times_out(self) -> None:
        lock = self.root / "ledger" / ".lock"
        lock.write_text("busy\n", encoding="utf-8")
        old_timeout = towerctl.LEDGER_LOCK_TIMEOUT
        old_stale = towerctl.LEDGER_LOCK_STALE_AFTER
        try:
            towerctl.LEDGER_LOCK_TIMEOUT = 0.25
            towerctl.LEDGER_LOCK_STALE_AFTER = 60.0
            with self.assertRaises(towerctl.LedgerLockTimeout):
                towerctl.append_ledger(
                    self.root, "TIMEOUT", "executor", {"i": 1})
        finally:
            towerctl.LEDGER_LOCK_TIMEOUT = old_timeout
            towerctl.LEDGER_LOCK_STALE_AFTER = old_stale

        self.assertFalse(self.ledger.exists())
        self.assertTrue(lock.exists(), "someone else's lock must not be removed")

    # -- 3b. a >60s stale lock is cleaned up and the write succeeds ------
    def test_stale_lock_is_cleared_and_write_succeeds(self) -> None:
        lock = self.root / "ledger" / ".lock"
        lock.write_text("stale\n", encoding="utf-8")
        old = time.time() - 120
        os.utime(lock, (old, old))

        event = towerctl.append_ledger(
            self.root, "STALE", "executor", {"i": 1})
        self.assertEqual(event["seq"], 1)
        self.assertFalse(lock.exists())
        self.assertEqual(
            towerctl.verify_ledger_file(self.root, "primary")["errors"], [])

    # -- 4. direct platform-branch coverage -----------------------------
    def test_windows_permission_error_is_treated_as_contention(self) -> None:
        real_open = os.open
        state = {"raised": False}

        def flaky_open(path, flags, *args, **kwargs):
            if not state["raised"]:
                state["raised"] = True
                raise PermissionError(13, "Permission denied")
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(towerctl.os, "open", side_effect=flaky_open):
            event = towerctl.append_ledger(
                self.root, "WIN", "executor", {"i": 1})

        self.assertTrue(state["raised"])
        self.assertEqual(event["seq"], 1)
        self.assertFalse((self.root / "ledger" / ".lock").exists())

    def test_posix_permission_error_is_not_swallowed(self) -> None:
        lock = self.root / "ledger" / ".lock"
        with mock.patch.object(towerctl.os, "name", "posix"), \
                mock.patch.object(towerctl.os, "open",
                                  side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                towerctl._acquire_lock_file(lock, 0.2, 60.0)

    def test_lock_helpers_tolerate_windows_oserrors(self) -> None:
        lock = self.root / "ledger" / ".lock"
        lock.write_text("lock\n", encoding="utf-8")
        identity = lock.stat()

        with self.subTest("release tolerates stat PermissionError"):
            with mock.patch.object(Path, "stat",
                                   side_effect=PermissionError(13, "denied")):
                towerctl._release_lock_file(lock, identity)
            self.assertTrue(lock.exists())

        with self.subTest("release tolerates unlink PermissionError"):
            with mock.patch.object(Path, "unlink",
                                   side_effect=PermissionError(13, "denied")):
                towerctl._release_lock_file(lock, identity)
            self.assertTrue(lock.exists())

        with self.subTest("stale replacement tolerates PermissionError"):
            old = time.time() - 120
            os.utime(lock, (old, old))
            with mock.patch.object(towerctl.os, "replace",
                                   side_effect=PermissionError(13, "denied")):
                self.assertFalse(towerctl._clear_stale_lock(lock, 60.0))
            self.assertTrue(lock.exists())

        with self.subTest("ledger_lock uses identity=None when stat fails"):
            lock.unlink()
            real_stat = Path.stat

            def lock_stat_fails(path_self, *args, **kwargs):
                if path_self == lock:
                    raise PermissionError(13, "denied")
                return real_stat(path_self, *args, **kwargs)

            with mock.patch.object(Path, "stat", new=lock_stat_fails):
                with towerctl.ledger_lock(self.root):
                    pass
            # Release could not stat the lock either; it must not raise.
            self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
