"""Root-level harness so `unittest discover -s tests` (used by towerctl post-merge)
runs the tower's real gate suite instead of vacuously passing with zero tests.

Fixes AUDIT-2026-10-19 P1-9.  Also fixes PILOT-024's false red: the tower suite
child writes a locale code page (cp936 on this host) and the parent used to
decode its pipes as strict UTF-8, so a localized skip message crashed the gate
with ``UnicodeDecodeError`` and left ``stdout``/``stderr`` as ``None``.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOWER = ROOT / "tower-dsh"


def run_captured(argv, cwd):
    """Run *argv* in *cwd* and always return decoded text output.

    Two defenses make the capture survive a child that writes non-UTF-8 bytes
    (e.g. a cp936-encoded Windows error message):

    * ``PYTHONIOENCODING=utf-8`` is injected into a copy of the environment so
      Python children emit UTF-8; everything else in the environment is kept.
    * The bytes are decoded as UTF-8 with ``errors="replace"``, so undecodable
      bytes become U+FFFD instead of raising ``UnicodeDecodeError``.

    ``stdout``/``stderr`` are normalized to ``str`` so callers may concatenate
    them unconditionally.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cp = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # subprocess.run(text=True) already promises str; keep the gate's contract
    # explicit so a future refactor cannot reintroduce None concatenation.
    cp.stdout = cp.stdout if cp.stdout is not None else ""
    cp.stderr = cp.stderr if cp.stderr is not None else ""
    return cp


class TowerGateSuite(unittest.TestCase):
    def test_tower_gate_suite(self):
        cp = run_captured(
            [sys.executable, "-B", "tools/run_tests.py"],
            TOWER,
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        match = re.search(r"Ran (\d+) test", cp.stderr)
        self.assertIsNotNone(match, cp.stderr)
        self.assertGreaterEqual(int(match.group(1)), 8, cp.stderr)


class NonUtf8ChildOutput(unittest.TestCase):
    """Regression for PILOT-024: undecodable child bytes must not crash the gate."""

    def test_non_utf8_child_output_is_replaced_not_raised(self):
        cp = run_captured(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes([0xbf])); "
                "sys.stderr.buffer.write(bytes([0xbf]))",
            ],
            ROOT,
        )
        self.assertEqual(cp.returncode, 0)
        self.assertIsInstance(cp.stdout, str)
        self.assertIsInstance(cp.stderr, str)
        self.assertIn("\ufffd", cp.stdout)
        self.assertIn("\ufffd", cp.stderr)


if __name__ == "__main__":
    unittest.main()
