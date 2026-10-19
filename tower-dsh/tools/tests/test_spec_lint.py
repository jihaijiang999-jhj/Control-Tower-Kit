"""Tests for ``towerctl spec-lint`` (PILOT-007).

Each test builds a throw-away ``specs/`` directory under ``tempfile`` and
drives the real CLI via ``subprocess``, so exit codes and JSON are asserted
exactly as a caller sees them. A minimal valid spec is written first and then
broken one rule at a time.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"

VALID_SPEC = r"""---
schema: tower/workflow@1
id: WF-TEST
title: test workflow
owner: tester
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-TEST — test workflow

## 1. 范围

Test only.

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `READY` | ready | 否 |
| `DONE` | done | 是 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `READY` | start | `task-new` | e | refuse |
| TR-02 | `READY` | `DONE` | finish | `close` | e | refuse |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | something holds | tool-check |

## 5. 证据

- proof

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | something broke | stop |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | init | owner |
"""


def strip_front_matter(text: str) -> str:
    start = text.index("---")
    end = text.index("\n---", start + 3) + len("\n---")
    return text[end:].lstrip("\n")


def remove_section(text: str, number: int) -> str:
    pattern = re.compile(rf"^## {number}\.[^\n]*\n.*?(?=^## \d+\.)", re.S | re.M)
    return pattern.sub("", text)


class SpecLintTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-spec-lint-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.specs = self.root / "specs"
        self.specs.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_spec(self, text: str, name: str = "wf-test.md") -> Path:
        path = self.specs / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def lint(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.run_cli("spec-lint")
        self.assertTrue(cp.stdout.strip(), msg=f"stderr={cp.stderr}")
        return cp, json.loads(cp.stdout)

    def assert_rejected(self, cp: subprocess.CompletedProcess, data: dict,
                        *keywords: str) -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertFalse(data["ok"])
        self.assertTrue(data["errors"])
        blob = "\n".join(data["errors"]).lower()
        for keyword in keywords:
            self.assertIn(keyword.lower(), blob,
                          msg=f"missing {keyword!r} in errors={data['errors']}")

    # -- 1. real specs ---------------------------------------------------
    def test_real_specs_directory_passes(self) -> None:
        cp = self.run_cli("spec-lint", "--dir", str(TOWER_ROOT / "specs"))
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["files"]), 4)
        self.assertEqual(data["errors"], [])
        for entry in data["files"]:
            self.assertEqual(entry["errors"], [], msg=entry["path"])

    # -- 2. missing front matter ----------------------------------------
    def test_missing_front_matter_fails(self) -> None:
        self.write_spec(strip_front_matter(VALID_SPEC))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "front matter")

    # -- 3. missing section ---------------------------------------------
    def test_missing_section_fails(self) -> None:
        self.write_spec(remove_section(VALID_SPEC, 5))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "missing required section", "5")

    # -- 4. transition references an undeclared state -------------------
    def test_transition_undeclared_state_fails(self) -> None:
        broken = VALID_SPEC.replace("| TR-02 | `READY` | `DONE`",
                                    "| TR-02 | `READY` | `GHOST`")
        self.write_spec(broken)
        cp, data = self.lint()
        self.assert_rejected(cp, data, "undeclared state", "GHOST")

    # -- 5. declared state is unreachable -------------------------------
    def test_unreachable_state_fails(self) -> None:
        broken = VALID_SPEC.replace(
            "| `DONE` | done | 是 |",
            "| `DONE` | done | 是 |\n| `ORPHAN` | orphan | 否 |",
        )
        self.write_spec(broken)
        cp, data = self.lint()
        self.assert_rejected(cp, data, "unreachable", "ORPHAN")

    # -- 6. enforcement value outside the legend ------------------------
    def test_invalid_enforcement_fails(self) -> None:
        broken = VALID_SPEC.replace("| INV-01 | something holds | tool-check |",
                                    "| INV-01 | something holds | vibes |")
        self.write_spec(broken)
        cp, data = self.lint()
        self.assert_rejected(cp, data, "enforcement", "vibes")

    # -- 7. unknown command in the command column -----------------------
    def test_unknown_command_fails(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "`frobnicate`"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "unknown command", "frobnicate")

    # -- 8. duplicate numbering -----------------------------------------
    def test_duplicate_transition_id_fails(self) -> None:
        self.write_spec(VALID_SPEC.replace("| TR-02 |", "| TR-01 |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "duplicate transition id", "TR-01")

    # -- 9. --dir does not exist ----------------------------------------
    def test_missing_specs_directory_fails(self) -> None:
        cp = self.run_cli("spec-lint", "--dir", str(self.root / "no-such-dir"))
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual(data["files"], [])
        self.assertIn("not found", "\n".join(data["errors"]))

    # -- 10. one bad file does not stop the good one --------------------
    def test_bad_file_does_not_block_good_file(self) -> None:
        self.write_spec(remove_section(VALID_SPEC, 5), "a-bad.md")
        self.write_spec(VALID_SPEC.replace("WF-TEST", "WF-GOOD"), "b-good.md")
        cp, data = self.lint()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertFalse(data["ok"])
        self.assertEqual(len(data["files"]), 2)
        by_id = {entry["id"]: entry for entry in data["files"]}
        self.assertTrue(by_id["WF-TEST"]["errors"])
        self.assertEqual(by_id["WF-GOOD"]["errors"], [])
        self.assertTrue(any("a-bad.md" in message for message in data["errors"]))
        self.assertFalse(any("b-good.md" in message for message in data["errors"]))

    # -- extra: invalid id, duplicate state, non-backtick command text --
    def test_invalid_id_fails(self) -> None:
        self.write_spec(VALID_SPEC.replace("id: WF-TEST", "id: WF-test"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "does not match")

    def test_duplicate_state_fails(self) -> None:
        broken = VALID_SPEC.replace(
            "| `DONE` | done | 是 |",
            "| `DONE` | done | 是 |\n| `READY` | again | 否 |",
        )
        self.write_spec(broken)
        cp, data = self.lint()
        self.assert_rejected(cp, data, "duplicate state", "READY")

    def test_non_backtick_command_text_is_skipped(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "任意写事件命令"))
        cp, data = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])


if __name__ == "__main__":
    unittest.main()
