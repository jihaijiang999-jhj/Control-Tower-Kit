#!/usr/bin/env python3
"""PILOT-041 probe: old (main) towerctl vs new tool on two scope fixtures.

Case 1 (additive): the worktree commits one allowed file and one file that is
not in ``allowed_paths``.

Case 2 (rename): the worktree renames a tracked, out-of-scope file *into* the
allowed path with ``git mv``.  With rename detection ``git diff --name-only``
reports only the new (allowed) path, so the old tool lets the delivery through
(and the pre-fix gate did too); ``--no-renames`` separates the diff into the
deleted source and the added target, so the new gate rejects it.

The old tool is ``git show main:tower-dsh/tools/towerctl.py`` extracted to
``scratch/old/towerctl.py`` (no scope gate at all).  Results are written to
``scratch/probe.txt`` and ``scratch/probe-old-code.txt``.

Usage (from the task worktree)::

    python -B scratch/deliver_scope_probe.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
WORKTREE = SCRATCH.parent
NEW_TOOL = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
OLD_TOOL = SCRATCH / "old" / "towerctl.py"
TASK_ID = "TEST-041"
TASK_REL = f"pilot/worktrees/{TASK_ID}"
FIXED_TIME = "2026-10-19T00:00:00+08:00"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Pilot 041 Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Pilot 041 Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_case(base: Path, case: str) -> tuple[Path, list[str]]:
    """Build a minimal tower + real worktree and commit the case's changes."""
    kit = base / "kit"
    tower = kit / "tower-dsh"
    worktree = tower / TASK_REL
    (kit / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / ".gitignore").write_text("tower-dsh/pilot/worktrees/\n", encoding="utf-8")
    (tower / "tools").mkdir(parents=True, exist_ok=True)
    (tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (tower / "pilot").mkdir(parents=True, exist_ok=True)
    (tower / "pilot" / f"{TASK_ID}.spec.json").write_text("{}\n", encoding="utf-8")
    (tower / "pilot" / "other.json").write_text("{}\n", encoding="utf-8")

    assert run_git(kit, "init").returncode == 0
    assert run_git(kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode == 0
    assert run_git(kit, "add", "-A").returncode == 0
    cp = run_git(kit, "commit", "-m", "base")
    assert cp.returncode == 0, cp.stderr
    worktree.parent.mkdir(parents=True, exist_ok=True)
    cp = run_git(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK_ID}")
    assert cp.returncode == 0, cp.stderr

    if case == "additive":
        allowed = [f"{TASK_REL}/tower-dsh/tools/x.py"]
        (worktree / "tower-dsh" / "tools" / "x.py").write_text(
            "x = 2\n", encoding="utf-8")
        (worktree / "tower-dsh" / "tools" / "y.py").write_text(
            "y = 2\n", encoding="utf-8")
        cp = run_git(worktree, "add", "-A")
        assert cp.returncode == 0, cp.stderr
        cp = run_git(worktree, "commit", "-m", "in scope + out of scope")
        assert cp.returncode == 0, cp.stderr
    elif case == "rename":
        allowed = [f"{TASK_REL}/tower-dsh/tools/new.py"]
        cp = run_git(worktree, "mv", "tower-dsh/pilot/other.json",
                     "tower-dsh/tools/new.py")
        assert cp.returncode == 0, cp.stderr
        cp = run_git(worktree, "commit", "-m", "rename out of scope into allowed")
        assert cp.returncode == 0, cp.stderr
    else:  # pragma: no cover - programming error
        raise SystemExit(f"unknown case: {case}")

    write_json(tower / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "role": "primary",
        "primary": {"id": "ctl-probe"}, "owner": {"name": "mac"},
    })
    write_json(tower / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    (tower / "ledger").mkdir(parents=True, exist_ok=True)
    (tower / "ledger" / "primary.jsonl").touch()
    write_json(tower / "tasks" / TASK_ID / "record.json", {
        "schema": "tower/task@1",
        "id": TASK_ID,
        "title": f"probe deliver scope ({case})",
        "status": "dispatched",
        "authority": "workspace_write",
        "scope": ["probe"],
        "allowed_paths": allowed,
        "forbidden": ["merge"],
        "acceptance": ["probe"],
        "depends_on": [],
        "worktree": TASK_REL,
        "executor": "probe-exec",
        "dispatch": {"executor": "probe-exec", "worktree": TASK_REL, "at": FIXED_TIME},
        "evidence": [],
        "review": None,
        "decision": None,
        "closeout": None,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        "next": "等待 executor 交付",
    })
    (tower / "work").mkdir(parents=True, exist_ok=True)
    (tower / "work" / "proof.txt").write_text("proof\n", encoding="utf-8")
    return tower, allowed


def run_deliver(tool: Path, tower: Path,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(tower),
         "deliver", "--task", TASK_ID, "--evidence", "work/proof.txt"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def old_env() -> dict[str, str]:
    """Env for the copied main ``towerctl``: resolve its unchanged siblings.

    The copied file lives in ``scratch/old`` and imports ``spec_coverage`` /
    ``spec_lint`` from the tower's ``tools`` directory.  Those modules are not
    modified by this task (only ``towerctl.py`` differs from main), so putting
    the live ``tools`` directory on ``PYTHONPATH`` exercises the old
    ``towerctl.py`` logic without copying anything else.
    """
    env = dict(os.environ)
    parts = [str(NEW_TOOL.parent)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def describe(cp: subprocess.CompletedProcess) -> list[str]:
    lines = [f"exit={cp.returncode}"]
    if cp.stdout.strip():
        try:
            payload = json.loads(cp.stdout)
        except ValueError:
            lines.append(f"stdout={cp.stdout.strip()}")
        else:
            lines.append("stdout=" + json.dumps(payload, ensure_ascii=False))
            if not payload.get("ok"):
                for error in payload.get("errors") or []:
                    lines.append(f"  error: {error}")
    if cp.stderr.strip():
        lines.append(f"stderr={cp.stderr.strip()}")
    return lines


def diff_names(worktree: Path, *extra: str) -> list[str]:
    cp = run_git(worktree, "diff", "--name-only", *extra, "main..HEAD")
    return [line.strip() for line in cp.stdout.splitlines() if line.strip()]


def run_case(base: Path, case: str) -> tuple[list[str], list[str], bool]:
    """Run both tools on one fixture; return (probe lines, old-code lines, ok)."""
    tower, allowed = build_case(base, case)
    worktree = tower / TASK_REL
    plain = diff_names(worktree)
    no_renames = diff_names(worktree, "--no-renames")

    new_cp = run_deliver(NEW_TOOL, tower)
    record_after_new = json.loads(
        (tower / "tasks" / TASK_ID / "record.json").read_text(encoding="utf-8"))
    evidence_after_new = (tower / "tasks" / TASK_ID / "evidence").exists()
    old_cp = run_deliver(OLD_TOOL, tower, old_env())
    record_after_old = json.loads(
        (tower / "tasks" / TASK_ID / "record.json").read_text(encoding="utf-8"))

    ok = (new_cp.returncode == 2 and old_cp.returncode == 0
          and not evidence_after_new
          and record_after_new["status"] == "dispatched")
    probe = [
        f"case: {case}",
        f"  fixture: {tower}",
        f"  allowed_paths: {allowed}",
        f"  git diff --name-only main..HEAD: {plain}",
        f"  git diff --name-only --no-renames main..HEAD: {no_renames}",
        "  NEW tool:",
    ]
    probe += [f"    {line}" for line in describe(new_cp)]
    probe += [
        f"    record.status after new = {record_after_new['status']}",
        f"    evidence dir exists after new = {evidence_after_new}",
        "  OLD tool:",
    ]
    probe += [f"    {line}" for line in describe(old_cp)]
    probe += [
        f"    record.status after old = {record_after_old['status']}",
        "",
    ]

    old = [
        f"case: {case}",
        f"  allowed_paths: {allowed}",
        f"  rename-aware diff: {plain}",
        f"  --no-renames diff: {no_renames}",
        "  NEW tool:",
    ]
    old += [f"    {line}" for line in describe(new_cp)]
    old += ["  OLD tool:"]
    old += [f"    {line}" for line in describe(old_cp)]
    old += [""]
    return probe, old, ok


def main() -> int:
    if not OLD_TOOL.exists():
        print(f"old tool missing: {OLD_TOOL}; run "
              "git show main:tower-dsh/tools/towerctl.py > scratch/old/towerctl.py",
              file=sys.stderr)
        return 2
    old_text = OLD_TOOL.read_text(encoding="utf-8")
    main_sha = subprocess.run(
        ["git", "-C", str(WORKTREE), "rev-parse", "main"],
        capture_output=True, text=True, encoding="utf-8").stdout.strip()

    base = Path(tempfile.mkdtemp(prefix="pilot041-probe-"))
    try:
        probe_lines = [
            "PILOT-041 deliver scope probe (rename fix included)",
            "===================================================",
            "",
        ]
        old_lines = [
            "PILOT-041 old-code comparison (main towerctl has no scope gate)",
            "===============================================================",
            "old source: git show main:tower-dsh/tools/towerctl.py",
            f"main commit: {main_sha}",
            f"old file: {OLD_TOOL}",
            f"old bytes: {OLD_TOOL.stat().st_size}",
            f"old sha256: {sha256_file(OLD_TOOL)}",
            f"old contains 'deliver_scope': {'deliver_scope' in old_text}",
            f"old contains 'scope_checked': {'scope_checked' in old_text}",
            f"old executed with PYTHONPATH={NEW_TOOL.parent} "
            "(spec_coverage.py/spec_lint.py are unchanged from main; only "
            "towerctl.py differs)",
            "",
        ]
        all_ok = True
        for case in ("additive", "rename"):
            lines, old_case, ok = run_case(base / case, case)
            probe_lines += lines
            old_lines += old_case
            all_ok = all_ok and ok

        probe_lines += [
            "verdict: " + (
                "new rejects both fixtures with exit 2 and zero writes; old "
                "accepts both with exit 0"
                if all_ok else
                "UNEXPECTED: expected new exit 2 / old exit 0 for every case"),
            "",
        ]
        old_lines += [
            "conclusion: the old tool delivers both the additive and the "
            "renamed out-of-scope worktree with exit 0 (no scope check); the "
            "new tool fails closed with exit 2 and writes no evidence.  The "
            "rename case additionally shows why the diff must be collected "
            "with --no-renames: rename detection reports only the new "
            "(allowed) path.",
            "",
        ]
        report = "\n".join(probe_lines)
        (SCRATCH / "probe.txt").write_text(report, encoding="utf-8")
        (SCRATCH / "probe-old-code.txt").write_text(
            "\n".join(old_lines), encoding="utf-8")
        print(report)
        print("wrote:", SCRATCH / "probe.txt")
        print("wrote:", SCRATCH / "probe-old-code.txt")
        return 0 if all_ok else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
