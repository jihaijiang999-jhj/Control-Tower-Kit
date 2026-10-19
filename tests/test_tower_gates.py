"""Root-level harness so `unittest discover -s tests` (used by towerctl post-merge)
runs the tower's real gate suite instead of vacuously passing with zero tests.

Fixes AUDIT-2026-10-19 P1-9.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOWER = ROOT / "tower-dsh"


class TowerGateSuite(unittest.TestCase):
    def test_tower_gate_suite(self):
        cp = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tools/tests", "-v"],
            cwd=TOWER,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        match = re.search(r"Ran (\d+) test", cp.stderr)
        self.assertIsNotNone(match, cp.stderr)
        self.assertGreaterEqual(int(match.group(1)), 8, cp.stderr)


if __name__ == "__main__":
    unittest.main()
