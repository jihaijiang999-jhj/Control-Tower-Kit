"""PILOT-056: the 22 long functions moved files, not thresholds.

Every entry below is the frozen ``lines``/``branches`` pair from the pre-split
``state/SHAPE-BASELINE.json`` (``tools/towerctl.py``).  The split may only move
the entry to the module that now owns the function; the numbers are copied
verbatim, so the frozen debt stays identical and no new debt is added.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
BASELINE_REL = "state/SHAPE-BASELINE.json"
TOWERCTL_REL = "tools/towerctl.py"
MAX_LINES = 80
MAX_BRANCHES = 12
FROZEN_DEBT = 1080

# (module, lines, branches) — values are the pre-split frozen pairs.
MOVED = {
    "_authority_state_drift": ("tools/tower_authority.py", 129, 27),
    "_completion_drift": ("tools/tower_state_verify.py", 79, 19),
    "_evidence_entry_drift": ("tools/tower_state_verify.py", 94, 21),
    "_spec_drift": ("tools/tower_state_verify.py", 45, 17),
    "authority_require_locked": ("tools/tower_authority_cmd.py", 102, 29),
    "authority_set_locked": ("tools/tower_authority_cmd.py", 93, 21),
    "authority_state_check": ("tools/tower_authority_cmd.py", 186, 36),
    "build_parser": ("tools/tower_cli.py", 169, 0),
    "cmd_check": ("tools/tower_lookup.py", 73, 35),
    "cmd_completion_add": ("tools/tower_delivery.py", 114, 18),
    "cmd_envelope_new": ("tools/tower_envelope.py", 66, 15),
    "cmd_handoff_new": ("tools/tower_handoff.py", 189, 30),
    "cmd_merge": ("tools/tower_merge.py", 197, 35),
    "cmd_post_merge": ("tools/tower_post_merge.py", 171, 30),
    "current_snapshot": ("tools/tower_handoff.py", 63, 23),
    "deliver_scope": ("tools/tower_delivery.py", 112, 21),
    "envelope_checks": ("tools/tower_envelope.py", 121, 20),
    "handoff_checks": ("tools/tower_handoff.py", 46, 16),
    "pr_remote_merge": ("tools/tower_merge.py", 69, 17),
    "resolve_pilot_paths": ("tools/tower_profile.py", 42, 13),
    "state_verify_drift": ("tools/tower_state_verify.py", 189, 49),
    "verify_ledger_file": ("tools/tower_ledger_replay.py", 64, 14),
}


def load_baseline() -> dict:
    return json.loads((TOWER_ROOT / BASELINE_REL).read_text(encoding="utf-8"))


def scan() -> dict:
    sys.path.insert(0, str(TOOLS_DIR))
    import towerctl  # noqa: E402  (import after sys.path setup)
    return towerctl.shape_scan(TOWER_ROOT)


def debt(lines: int, branches: int) -> int:
    return max(0, lines - MAX_LINES) + max(0, branches - MAX_BRANCHES)


class BaselineMoveCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_baseline()
        cls.current = scan()

    def test_moved_entries_keep_exact_metrics(self) -> None:
        self.assertEqual(len(MOVED), 22)
        for name, (module, lines, branches) in MOVED.items():
            with self.subTest(function=name):
                frozen = self.baseline["files"][module]["functions"][name]
                self.assertEqual(frozen, {"lines": lines, "branches": branches})
                current = self.current["files"][module]["functions"][name]
                self.assertLessEqual(current["lines"], lines)
                self.assertLessEqual(current["branches"], branches)

    def test_towerctl_no_longer_owns_the_moved_functions(self) -> None:
        functions = self.baseline["files"][TOWERCTL_REL]["functions"]
        for name in MOVED:
            with self.subTest(function=name):
                self.assertNotIn(name, functions)

    def test_no_new_long_function_debt(self) -> None:
        long_functions = {}
        for key, entry in self.current["files"].items():
            if not Path(key).name.startswith("tower_"):
                continue
            for name, stats in entry["functions"].items():
                if stats["lines"] > MAX_LINES or stats["branches"] > MAX_BRANCHES:
                    long_functions[name] = (key, stats)
        self.assertEqual(set(long_functions), set(MOVED))
        frozen = sum(debt(lines, branches)
                     for _module, lines, branches in MOVED.values())
        self.assertEqual(frozen, FROZEN_DEBT)
        current = sum(debt(stats["lines"], stats["branches"])
                      for _key, stats in long_functions.values())
        self.assertLessEqual(current, frozen)

    def test_baseline_is_never_loosened(self) -> None:
        for key, entry in sorted(self.baseline["files"].items()):
            with self.subTest(file=key):
                self.assertIn(key, self.current["files"])
                current_functions = self.current["files"][key]["functions"]
                for name, frozen in entry["functions"].items():
                    if name not in current_functions:
                        continue
                    current = current_functions[name]
                    self.assertLessEqual(current["lines"], frozen["lines"])
                    self.assertLessEqual(current["branches"],
                                         frozen["branches"])


if __name__ == "__main__":
    unittest.main()
