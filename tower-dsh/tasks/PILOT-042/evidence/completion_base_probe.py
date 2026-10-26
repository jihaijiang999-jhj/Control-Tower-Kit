#!/usr/bin/env python3
"""PILOT-042 probe: authorized completions and the ``base_sha`` deliver anchor.

The probe builds a throw-away tower inside a real git repository with a real
``git worktree`` and runs one ``towerctl.py`` against it.  It never touches the
real tower, and the same probe runs against the ``main`` compiler of the tool
(``scratch/old/towerctl.py``) to contrast the old and new gates.

Two fixtures:

* ``scenario_completion_path`` -- a branch change to a file that is neither in
  ``allowed_paths`` nor (for the old tool) in any completion list.  The new
  tool accepts it after ``completion-add``; the old tool has no completion
  concept and rejects it.
* ``scenario_rewritten_main`` -- the branch changes an out-of-scope file and
  then rewrites the local ``main`` ref to HEAD.  The new tool diffs from the
  recorded ``dispatch.base_sha`` and rejects; the old tool diffed from
  ``merge-base main HEAD`` (now empty) and accepted.

Usage::

    python -B scratch/completion_base_probe.py
    python -B scratch/completion_base_probe.py --tool scratch/old/towerctl.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DEFAULT_TOOL = PROJECT / "tower-dsh" / "tools" / "towerctl.py"
TOOLS_DIR = PROJECT / "tower-dsh" / "tools"
TASK_ID = "PROBE-042"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
OWNER = "mac"
PROOF_REL = "work/proof.txt"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def git_ok(cwd: Path, *args: str) -> str:
    cp = run_git(cwd, *args)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr or cp.stdout or f"git {' '.join(args)}")
    return cp.stdout.strip()


def run_cli(tool: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # The old copy lives outside tools/, so make its sibling imports resolve.
    env["PYTHONPATH"] = str(TOOLS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def build_fixture(base: Path, *, dispatch=None) -> tuple[Path, Path, Path]:
    kit = base / "kit"
    tower = kit / "tower-dsh"
    worktree = tower / WORKTREE_REL
    (kit / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / ".gitignore").write_text("tower-dsh/pilot/worktrees/\n",
                                    encoding="utf-8")
    (tower / "tools").mkdir(parents=True, exist_ok=True)
    (tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (tower / "pilot").mkdir(parents=True, exist_ok=True)
    (tower / "pilot" / "other.json").write_text("{}\n", encoding="utf-8")
    if run_git(kit, "init").returncode != 0:
        raise RuntimeError("git init failed")
    if run_git(kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode != 0:
        raise RuntimeError("symbolic-ref failed")
    run_git(kit, "add", "-A")
    commit = run_git(kit, "commit", "-m", "base")
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr or commit.stdout)

    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = run_git(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK_ID}")
    if added.returncode != 0:
        raise RuntimeError(added.stderr or added.stdout)

    write_json(tower / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "primary": {"id": "probe"},
        "owner": {"name": OWNER},
    })
    write_json(tower / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    (tower / "ledger").mkdir(parents=True, exist_ok=True)
    (tower / "ledger" / "primary.jsonl").touch()
    record = {
        "schema": "tower/task@1", "id": TASK_ID, "title": "probe",
        "status": "dispatched", "authority": "workspace_write",
        "scope": ["probe"], "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
        "forbidden": ["merge"], "acceptance": ["probe"],
        "depends_on": [], "worktree": WORKTREE_REL, "executor": "probe",
        "dispatch": dispatch,
        "evidence": [], "review": None, "decision": None, "closeout": None,
        "created_at": "2026-10-20T00:00:00+08:00",
        "updated_at": "2026-10-20T00:00:00+08:00", "next": "",
    }
    write_json(tower / "tasks" / TASK_ID / "record.json", record)
    return kit, tower, worktree


def commit_change(worktree: Path, relpath: str, text: str, message: str) -> str:
    path = worktree / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(worktree, "add", "-A")
    commit = run_git(worktree, "commit", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr or commit.stdout)
    return git_ok(worktree, "rev-parse", "HEAD")


def proof(tower: Path) -> None:
    path = tower / PROOF_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("proof\n", encoding="utf-8")


def deliver(tool: Path, tower: Path) -> dict:
    proof(tower)
    cp = run_cli(tool, tower, "deliver", "--task", TASK_ID, "--evidence", PROOF_REL)
    try:
        payload = json.loads(cp.stdout)
    except ValueError:
        payload = {"stdout": cp.stdout, "stderr": cp.stderr}
    result = {
        "deliver_exit": cp.returncode,
        "deliver_ok": payload.get("ok"),
        "deliver_errors": payload.get("errors", []),
    }
    if "scope_completions" in payload:
        result["scope_completions"] = payload["scope_completions"]
    else:
        result["scope_completions"] = "<absent (pre-PILOT-042 tool)>"
    return result


def scenario_completion_path(tool: Path, base: Path) -> dict:
    _, tower, worktree = build_fixture(base / "case-completion")
    completion = run_cli(
        tool, tower, "completion-add", "--task", TASK_ID,
        "--path", f"{WORKTREE_REL}/tower-dsh/tools/helper.py",
        "--by", OWNER, "--reason", "§6.11 authorized completion (probe)",
        "--decision", "D-PROBE")
    supported = "invalid choice" not in completion.stderr
    result = {
        "completion_add_supported": supported,
        "completion_add_exit": completion.returncode,
        "changed_file": "tower-dsh/tools/helper.py",
        "in_allowed_paths": False,
    }
    if supported:
        result["completion_add_already"] = json.loads(completion.stdout).get("already")
    commit_change(worktree, "tower-dsh/tools/helper.py", "helper = 1\n",
                  "completion-authorized helper")
    result.update(deliver(tool, tower))
    return result


def scenario_rewritten_main(tool: Path, base: Path) -> dict:
    kit, tower, worktree = build_fixture(base / "case-main")
    base_sha = git_ok(kit, "rev-parse", "main")
    record_path = tower / "tasks" / TASK_ID / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["dispatch"] = {"executor": "probe", "worktree": WORKTREE_REL,
                          "at": "2026-10-20T00:00:00+08:00",
                          "base_sha": base_sha}
    write_json(record_path, record)

    head = commit_change(worktree, "tower-dsh/pilot/other.json", '{"v": 2}\n',
                         "out of scope change")
    moved = run_git(worktree, "update-ref", "refs/heads/main", "HEAD")
    if moved.returncode != 0:
        raise RuntimeError(moved.stderr or moved.stdout)
    result = {
        "recorded_base_sha": base_sha,
        "head": head,
        "rewritten_main": git_ok(worktree, "rev-parse", "main"),
        "changed_file": "tower-dsh/pilot/other.json",
        "in_allowed_paths": False,
    }
    result.update(deliver(tool, tower))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default=str(DEFAULT_TOOL),
                        help="towerctl.py to probe (default: the worktree tool)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the probe scratch directory")
    args = parser.parse_args(argv)
    tool = Path(args.tool).resolve()
    if not tool.is_file():
        print(json.dumps({"ok": False, "error": f"tool not found: {tool}"}))
        return 2

    tmp = tempfile.mkdtemp(prefix="pilot042-probe-")
    base = Path(tmp)
    try:
        report = {
            "probe": "PILOT-042 completion scope + base_sha anchor",
            "tool": str(tool),
            "scenario_completion_path": scenario_completion_path(tool, base),
            "scenario_rewritten_main": scenario_rewritten_main(tool, base),
        }
    finally:
        if not args.keep:
            import shutil
            shutil.rmtree(base, ignore_errors=True)
    report["ok"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
