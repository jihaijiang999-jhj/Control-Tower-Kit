"""Tests for the ``tower/spec@2`` objective gate (PILOT-049).

Every case builds a throw-away tower root with a real worktree directory and
``pilot/T-1.spec.json``, then drives the real CLI through ``subprocess`` so the
exit code, the single-JSON contract and the zero-write promise are asserted
exactly as a caller observes them.

Run from the tower root (``tower-dsh``) with
``python -B tools/run_tests.py --pattern test_objective.py``.
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
TASK_ID = "T-1"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
OBJECTIVE_FIELDS = ("problem", "outcome", "approach", "non_goals_and_done")
OBJECTIVE = {
    "problem": "任务卡可以只写标题，施工时被收窄成单点补丁。",
    "outcome": "新卡创建时必须携带四字段施工目标并通过机检。",
    "approach": "在 task-new 与 spec-lint 各校验一次同一份原生规则。",
    "non_goals_and_done": "不回写旧卡；正反例测试全绿且证据落盘即完成。",
}


def make_spec(schema: str = "tower/spec@2", **overrides) -> dict:
    """A sound task spec; ``overrides`` replace top-level keys."""
    data = {
        "schema": schema,
        "id": TASK_ID,
        "title": "objective gate fixture",
        "authority": "workspace_write",
        "scope": ["exercise the objective gate"],
        "allowed_paths": ["tools/example.py"],
        "forbidden": ["merge", "production access"],
        "acceptance": ["tests pass"],
        "depends_on": [],
        "worktree": WORKTREE_REL,
        "objective": dict(OBJECTIVE),
    }
    data.update(overrides)
    return data


def ledger_events(root: Path) -> list[dict]:
    path = root / "ledger" / "primary.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ObjectiveCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-objective-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs", WORKTREE_REL):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.spec_path = self.root / "pilot" / f"{TASK_ID}.spec.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_spec(self, data) -> Path:
        if isinstance(data, dict):
            text = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            text = str(data)
        self.spec_path.write_text(text, encoding="utf-8")
        return self.spec_path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def task_new(self) -> subprocess.CompletedProcess:
        return self.run_cli("task-new", "--spec", f"pilot/{TASK_ID}.spec.json")

    def lint(self) -> subprocess.CompletedProcess:
        return self.run_cli("spec-lint")

    def assert_rejected(self, cp: subprocess.CompletedProcess,
                        *keywords: str) -> dict:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertNotIn("Traceback", cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = "\n".join(payload["errors"])
        for keyword in keywords:
            self.assertIn(keyword, blob,
                          msg=f"missing {keyword!r} in errors={payload['errors']}")
        return payload

    def assert_zero_writes(self) -> None:
        self.assertFalse((self.root / "tasks" / TASK_ID).exists())
        self.assertEqual(
            [event for event in ledger_events(self.root)
             if event.get("type") == "TASK_NEW"], [])
        board = self.root / "primary" / "TASK_BOARD.json"
        if board.exists():
            self.assertEqual(json.loads(board.read_text(encoding="utf-8"))
                             .get("tasks"), [])

    # -- positive cases --------------------------------------------------
    def test_accepts_complete_spec2(self) -> None:
        self.write_spec(make_spec())
        cp = self.task_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue((self.root / "tasks" / TASK_ID / "record.json").is_file())
        types = [event.get("type") for event in ledger_events(self.root)]
        self.assertEqual(types.count("TASK_NEW"), 1)

    def test_accepts_spec1_bootstrap_with_objective(self) -> None:
        self.write_spec(make_spec(schema="tower/spec@1"))
        cp = self.task_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def test_accepts_real_049_bootstrap_spec(self) -> None:
        data = json.loads((TOWER_ROOT / "pilot" / "PILOT-049.spec.json")
                          .read_text(encoding="utf-8"))
        (self.root / "pilot" / "PILOT-049.spec.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.root / "pilot" / "worktrees" / "PILOT-049").mkdir(
            parents=True, exist_ok=True)
        cp = self.run_cli("task-new", "--spec", "pilot/PILOT-049.spec.json")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    # -- refusal cases ---------------------------------------------------
    def test_rejects_missing_objective(self) -> None:
        spec = make_spec()
        spec.pop("objective")
        self.write_spec(spec)
        self.assert_rejected(self.task_new(), "objective")
        self.assert_zero_writes()

    def test_rejects_each_missing_field(self) -> None:
        for field in OBJECTIVE_FIELDS:
            with self.subTest(field=field):
                spec = make_spec()
                spec["objective"].pop(field)
                self.write_spec(spec)
                self.assert_rejected(self.task_new(), f"objective.{field}")
                self.assert_zero_writes()

    def test_rejects_non_string_field(self) -> None:
        spec = make_spec()
        spec["objective"]["problem"] = 42
        self.write_spec(spec)
        self.assert_rejected(self.task_new(), "objective.problem")
        self.assert_zero_writes()

    def test_rejects_empty_and_too_short_field(self) -> None:
        for value in ("", "   ", "short"):
            with self.subTest(value=value):
                spec = make_spec()
                spec["objective"]["outcome"] = value
                self.write_spec(spec)
                self.assert_rejected(self.task_new(), "objective.outcome")
                self.assert_zero_writes()

    def test_rejects_fill_marker(self) -> None:
        spec = make_spec()
        spec["objective"]["approach"] = "__FILL__"
        self.write_spec(spec)
        self.assert_rejected(self.task_new(), "objective.approach", "__FILL__")
        self.assert_zero_writes()

    def test_rejects_angle_placeholder(self) -> None:
        spec = make_spec()
        spec["objective"]["non_goals_and_done"] = "<待填写的完成标准>"
        self.write_spec(spec)
        self.assert_rejected(self.task_new(), "objective.non_goals_and_done",
                             "placeholder")
        self.assert_zero_writes()

    def test_rejects_bad_json_cleanly(self) -> None:
        self.write_spec("{not json")
        cp = self.task_new()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        self.assertFalse(json.loads(cp.stdout)["ok"])
        self.assert_zero_writes()

    # -- spec-lint -------------------------------------------------------
    def test_spec_lint_skips_frozen_spec1(self) -> None:
        spec = make_spec(schema="tower/spec@1")
        spec.pop("objective")
        self.write_spec(spec)
        cp = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["files"], [])

    def test_spec_lint_rejects_bad_spec2(self) -> None:
        spec = make_spec()
        spec["objective"]["problem"] = ""
        self.write_spec(spec)
        self.assert_rejected(self.lint(), "objective.problem",
                             f"pilot/{TASK_ID}.spec.json")

    def test_spec_lint_accepts_good_spec2(self) -> None:
        self.write_spec(make_spec())
        cp = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["ok"])

    def test_spec_lint_ignores_nested_copy(self) -> None:
        self.write_spec(make_spec())
        nested = make_spec()
        nested["objective"]["problem"] = ""
        (self.root / WORKTREE_REL / "PILOT-049.spec.json").write_text(
            json.dumps(nested, ensure_ascii=False), encoding="utf-8")
        cp = self.lint()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    # -- template --------------------------------------------------------
    def test_template_is_spec2_with_real_objective(self) -> None:
        data = json.loads((TOWER_ROOT / "templates" / "task.spec.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "tower/spec@2")
        for field in OBJECTIVE_FIELDS:
            value = data["objective"][field]
            self.assertIsInstance(value, str, msg=field)
            self.assertGreaterEqual(len(value.strip()), 8, msg=field)
            self.assertNotIn("__FILL__", value, msg=field)
            self.assertIsNone(re.fullmatch(r"<[^>]+>", value.strip()), msg=field)

    def test_template_is_accepted_by_task_new(self) -> None:
        data = json.loads((TOWER_ROOT / "templates" / "task.spec.json")
                          .read_text(encoding="utf-8"))
        data["id"] = TASK_ID
        data["worktree"] = WORKTREE_REL
        self.write_spec(data)
        cp = self.task_new()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)


if __name__ == "__main__":
    unittest.main()
