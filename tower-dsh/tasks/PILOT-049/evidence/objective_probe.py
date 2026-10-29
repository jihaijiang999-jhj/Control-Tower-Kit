#!/usr/bin/env python3
"""PILOT-049 objective probe: reproduce the gate's positive/negative values.

Runs the worktree CLI against throw-away tower roots (a real worktree directory
plus ``pilot/T-1.spec.json``) and prints one line per case.  It is evidence,
not a test: the same assertions live in ``tools/tests/test_objective.py``.

    python -B scratch/objective_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER_ROOT = WORKTREE / "tower-dsh"
TCLI = TOWER_ROOT / "tools" / "towerctl.py"
TASK_ID = "T-1"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
OBJECTIVE = {
    "problem": "任务卡可以只写标题，施工时被收窄成单点补丁。",
    "outcome": "新卡创建时必须携带四字段施工目标并通过机检。",
    "approach": "在 task-new 与 spec-lint 各校验一次同一份原生规则。",
    "non_goals_and_done": "不回写旧卡；正反例测试全绿且证据落盘即完成。",
}


def make_spec(schema: str = "tower/spec@2", **overrides) -> dict:
    data = {
        "schema": schema,
        "id": TASK_ID,
        "title": "objective probe",
        "authority": "workspace_write",
        "scope": ["probe the objective gate"],
        "allowed_paths": ["tools/example.py"],
        "forbidden": ["merge", "production access"],
        "acceptance": ["probe passes"],
        "depends_on": [],
        "worktree": WORKTREE_REL,
        "objective": dict(OBJECTIVE),
    }
    data.update(overrides)
    return data


class Tower:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="pilot049-probe-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs", WORKTREE_REL):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.spec_path = self.root / "pilot" / f"{TASK_ID}.spec.json"

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def write(self, data) -> None:
        text = (data if isinstance(data, str)
                else json.dumps(data, ensure_ascii=False, indent=2))
        self.spec_path.write_text(text, encoding="utf-8")

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env)

    def task_new(self) -> subprocess.CompletedProcess:
        return self.run("task-new", "--spec", f"pilot/{TASK_ID}.spec.json")

    def task_dir_exists(self) -> bool:
        return (self.root / "tasks" / TASK_ID).exists()

    def task_new_events(self) -> int:
        ledger = self.root / "ledger" / "primary.jsonl"
        if not ledger.exists():
            return 0
        events = [json.loads(line) for line in
                  ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        return sum(1 for event in events if event.get("type") == "TASK_NEW")


def errors_of(cp: subprocess.CompletedProcess) -> list[str]:
    try:
        return json.loads(cp.stdout).get("errors", [])
    except ValueError:
        return [f"<not json: {cp.stdout[:80]!r}>"]


def report(label: str, cp: subprocess.CompletedProcess, tower: Tower) -> None:
    zeros = (not tower.task_dir_exists()) and tower.task_new_events() == 0
    print(f"{label}: rc={cp.returncode} zero_write={zeros} "
          f"tasks/{TASK_ID}={tower.task_dir_exists()} "
          f"TASK_NEW={tower.task_new_events()}")
    for message in errors_of(cp):
        print(f"    error: {message}")
    if cp.stderr.strip():
        print(f"    stderr: {cp.stderr.strip()[:200]}")


def case(label: str, spec) -> None:
    tower = Tower()
    try:
        tower.write(spec)
        report(label, tower.task_new(), tower)
    finally:
        tower.cleanup()


def lint_case(label: str, spec) -> None:
    tower = Tower()
    try:
        tower.write(spec)
        cp = tower.run("spec-lint")
        print(f"{label}: rc={cp.returncode} errors={errors_of(cp)}")
    finally:
        tower.cleanup()


def main() -> None:
    template = json.loads((TOWER_ROOT / "templates" / "task.spec.json")
                          .read_text(encoding="utf-8"))
    template["id"] = TASK_ID
    template["worktree"] = WORKTREE_REL
    case("template @2 (id/worktree rewritten)", template)
    case("complete @2", make_spec())

    missing = make_spec()
    missing.pop("objective")
    case("missing objective", missing)
    for field, value, label in (
        ("problem", 42, "problem non-string"),
        ("outcome", "", "outcome empty"),
        ("approach", "   ", "approach whitespace"),
        ("non_goals_and_done", "short", "non_goals short"),
        ("approach", "__FILL__", "approach __FILL__"),
        ("problem", "<待填写的问题描述>", "problem <...> placeholder"),
    ):
        spec = make_spec()
        spec["objective"][field] = value
        case(label, spec)

    spec1 = make_spec(schema="tower/spec@1")
    spec1.pop("objective")
    lint_case("spec-lint @1 without objective", spec1)
    lint_case("spec-lint @2 good", make_spec())
    bad = make_spec()
    bad["objective"]["problem"] = ""
    lint_case("spec-lint @2 bad", bad)
    case("bad JSON", "{not json")

    tower = Tower()
    try:
        real = json.loads((TOWER_ROOT / "pilot" / "PILOT-049.spec.json")
                          .read_text(encoding="utf-8"))
        (tower.root / "pilot" / "PILOT-049.spec.json").write_text(
            json.dumps(real, ensure_ascii=False, indent=2), encoding="utf-8")
        (tower.root / "pilot" / "worktrees" / "PILOT-049").mkdir(
            parents=True, exist_ok=True)
        cp = tower.run("task-new", "--spec", "pilot/PILOT-049.spec.json")
        print(f"real 049 bootstrap spec (@1 + objective): rc={cp.returncode} "
              f"errors={errors_of(cp)}")
    finally:
        tower.cleanup()


if __name__ == "__main__":
    main()
