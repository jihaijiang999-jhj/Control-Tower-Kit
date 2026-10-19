"""Tests for ``towerctl spec-lint`` policy linting and ``--strict`` (PILOT-008).

Each test builds a throw-away tower root under ``tempfile`` and drives the real
CLI via ``subprocess``, so exit codes and JSON are asserted exactly as a caller
sees them. Policy documents live at the root (``RED-LINES.md`` /
``CHANGE-LEVELS.md`` style); workflow fixtures live in ``specs/``.

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
from collections import Counter
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"

VALID_POLICY = r"""---
schema: tower/policy@1
id: POL-TEST
title: test policy
owner: tester
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# POL-TEST — test policy

## 1. 范围

Test only.

## 2. 条款

| ID | 条款 | 级别 | enforcement | 判定方法 |
|---|---|---|---|---|
| C-01 | never do the thing | MUST NOT | owner-gate | check the thing did not happen |
| C-02 | always record evidence | MUST | tool-check | check the ledger event |

## 3. 证据

- proof

## 4. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | something broke | stop |
| FM-02 | unclear | ask owner |

## 5. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | init | owner |
"""

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


def remove_section(text: str, number: int) -> str:
    pattern = re.compile(rf"^## {number}\.[^\n]*\n.*?(?=^## \d+\.)", re.S | re.M)
    return pattern.sub("", text)


class PolicyLintTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-policy-lint-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.specs = self.root / "specs"
        self.specs.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_policy(self, text: str, name: str = "POL-TEST.md") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_spec(self, text: str, name: str = "wf-test.md") -> Path:
        path = self.specs / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_at(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return self.run_at(self.root, *args)

    def lint(self, *args: str) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.run_cli("spec-lint", *args)
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

    # -- 1. the real tower root: 4 workflows + 2 policies -----------------
    def test_real_tower_root_lints_six_documents(self) -> None:
        cp = self.run_at(TOWER_ROOT, "spec-lint")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])
        self.assertEqual(len(data["files"]), 6)
        kinds = Counter(entry["kind"] for entry in data["files"])
        self.assertEqual(kinds, {"workflow": 4, "policy": 2})
        policy_ids = {entry["id"] for entry in data["files"]
                      if entry["kind"] == "policy"}
        self.assertEqual(policy_ids, {"POL-RED-LINES", "POL-CHANGE-LEVELS"})
        for entry in data["files"]:
            self.assertEqual(entry["errors"], [], msg=entry["path"])

    def test_real_tower_root_strict_passes(self) -> None:
        cp = self.run_at(TOWER_ROOT, "spec-lint", "--strict")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["files"]), 6)
        self.assertEqual(data["errors"], [])
        for entry in data["files"]:
            self.assertEqual(entry["errors"], [], msg=entry["path"])

    # -- 2. a valid policy passes ----------------------------------------
    def test_valid_policy_passes(self) -> None:
        self.write_policy(VALID_POLICY)
        cp, data = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])
        self.assertEqual(len(data["files"]), 1)
        entry = data["files"][0]
        self.assertEqual(entry["kind"], "policy")
        self.assertEqual(entry["id"], "POL-TEST")
        self.assertEqual(entry["clauses"], ["C-01", "C-02"])
        self.assertEqual(entry["failures"], ["FM-01", "FM-02"])

    # -- 3. missing clause ID --------------------------------------------
    def test_missing_clause_id_fails(self) -> None:
        self.write_policy(VALID_POLICY.replace("| C-01 |", "| |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "empty clause id")

    # -- 4. invalid level ------------------------------------------------
    def test_invalid_clause_level_fails(self) -> None:
        self.write_policy(VALID_POLICY.replace("| MUST |", "| MUSTISH |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "level", "MUSTISH")

    # -- 5. enforcement outside the legend -------------------------------
    def test_invalid_clause_enforcement_fails(self) -> None:
        self.write_policy(VALID_POLICY.replace("| owner-gate |", "| vibes |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "enforcement", "vibes")

    # -- 6. empty judgment method ----------------------------------------
    def test_empty_judgment_method_fails(self) -> None:
        self.write_policy(
            VALID_POLICY.replace("| check the ledger event |", "| |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "判定方法")

    # -- 7. duplicate failure-mode ID ------------------------------------
    def test_duplicate_failure_id_fails(self) -> None:
        self.write_policy(VALID_POLICY.replace("| FM-02 |", "| FM-01 |"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "duplicate failure id", "FM-01")

    # -- 8. --strict: a bare | misaligns a row ---------------------------
    def test_strict_bare_pipe_column_mismatch_fails(self) -> None:
        broken = VALID_SPEC.replace(
            "| `READY` | ready | 否 |",
            "| `READY` | ready | 否 | extra |",
        )
        self.write_spec(broken)
        cp, data = self.lint("--strict")
        self.assert_rejected(cp, data, "cells", "expected 3")

    # -- 9. --strict: a blank line truncates a table ---------------------
    def test_strict_table_interrupted_by_blank_line_fails(self) -> None:
        broken = VALID_SPEC.replace(
            "| INV-01 | something holds | tool-check |",
            "| INV-01 | something holds | tool-check |\n\n"
            "| INV-02 | another holds | tool-check |",
        )
        self.write_spec(broken)
        cp, data = self.lint("--strict")
        self.assert_rejected(cp, data, "table interrupted by blank line")

    # -- 10. --strict: duplicate section number --------------------------
    def test_strict_duplicate_section_number_fails(self) -> None:
        broken = VALID_SPEC + "\n## 5. 证据\n\nduplicate heading.\n"
        self.write_spec(broken)
        cp, data = self.lint("--strict")
        self.assert_rejected(cp, data, "duplicate section number", "## 5")

    # -- 11. --strict: plain-text command cell ---------------------------
    def test_strict_plain_text_command_fails(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "frobnicate"))
        cp, data = self.lint("--strict")
        self.assert_rejected(cp, data, "command", "frobnicate")

    # -- 11b. --strict: Chinese prose in the command column is allowed ---
    def test_strict_chinese_command_text_passes(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "任意写事件命令"))
        cp, data = self.lint("--strict")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])

    # -- 12. the same fixtures pass without --strict ---------------------
    def test_strict_fixtures_pass_without_strict(self) -> None:
        fixtures = {
            "a-misaligned.md": VALID_SPEC.replace(
                "| `READY` | ready | 否 |",
                "| `READY` | ready | 否 | extra |",
            ),
            "b-blank-line.md": VALID_SPEC.replace(
                "| INV-01 | something holds | tool-check |",
                "| INV-01 | something holds | tool-check |\n\n"
                "| INV-02 | another holds | tool-check |",
            ),
            "c-duplicate-section.md": VALID_SPEC + "\n## 5. 证据\n\nduplicate.\n",
            "d-plain-command.md": VALID_SPEC.replace("`task-new`", "frobnicate"),
        }
        for name, text in fixtures.items():
            self.write_spec(text, name)
        cp, data = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["files"]), 4)
        self.assertEqual(data["errors"], [])
        for entry in data["files"]:
            self.assertEqual(entry["errors"], [], msg=entry["path"])

    # -- 13. towerctl <subcommand> is accepted as a command --------------
    def test_towerctl_subcommand_is_accepted(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "`towerctl spec-lint`"))
        cp, data = self.lint("--strict")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])

    # -- extra: bare towerctl names no subcommand, so it is not unknown --
    def test_bare_towerctl_is_accepted(self) -> None:
        self.write_spec(VALID_SPEC.replace("`task-new`", "`towerctl`"))
        cp, data = self.lint("--strict")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])

    # -- extra: invalid policy id ----------------------------------------
    def test_invalid_policy_id_fails(self) -> None:
        self.write_policy(VALID_POLICY.replace("id: POL-TEST", "id: POL-test"))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "does not match", "POL-test")

    # -- extra: missing policy section -----------------------------------
    def test_missing_policy_section_fails(self) -> None:
        self.write_policy(remove_section(VALID_POLICY, 4))
        cp, data = self.lint()
        self.assert_rejected(cp, data, "missing required section", "4")


if __name__ == "__main__":
    unittest.main()
