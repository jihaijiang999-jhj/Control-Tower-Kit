"""PILOT-051 probe: does a ready card with an unmet ``depends_on`` pass?

Builds a throw-away tower whose card ``TEST-NEW`` depends on ``TEST-DEP``, and
``TEST-DEP`` is still ``ready`` (not closed).  It then runs ``check --phase
ready`` and ``dispatch`` with a caller-supplied ``towerctl.py`` and prints the
exit code plus the resulting record status.

    python dependency_probe.py <path-to-towerctl.py> [label]

The same fixture is used for the old (``main``) and the new (PILOT-051) tool,
so the printed exits are directly comparable.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FIXED_TIME = "2026-10-30T00:00:00+08:00"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def spec_data(task_id: str, depends_on: list[str]) -> dict:
    return {
        "schema": "tower/spec@2",
        "id": task_id,
        "title": f"{task_id} probe",
        "authority": "workspace_write",
        "scope": ["probe depends_on"],
        "worktree": f"pilot/worktrees/{task_id}",
        "allowed_paths": ["tools/example.py"],
        "forbidden": ["merge", "production access"],
        "acceptance": ["probe only"],
        "depends_on": depends_on,
        "objective": {
            "problem": "depends_on is not enforced by the scheduler",
            "outcome": "unmet dependencies block ready and dispatch",
            "approach": "closure plus acyclicity gates on every entry",
            "non_goals_and_done": "no spec graph; probe exits are the evidence",
        },
    }


def build_tower(root: Path) -> None:
    for directory in ("primary", "ledger", "specs"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tower_id": "tower-dsh", "tasks": []})
    for task_id, status, deps in (("TEST-DEP", "ready", []),
                                  ("TEST-NEW", "ready", ["TEST-DEP"])):
        (root / "pilot" / "worktrees" / task_id).mkdir(parents=True, exist_ok=True)
        spec_path = root / "specs" / f"{task_id}.spec.json"
        write_json(spec_path, spec_data(task_id, deps))
        write_json(root / "tasks" / task_id / "record.json", {
            "schema": "tower/task@1", "id": task_id, "title": f"{task_id} probe",
            "status": status, "authority": "workspace_write",
            "scope": ["probe"], "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"], "acceptance": ["probe only"],
            "depends_on": list(deps), "worktree": f"pilot/worktrees/{task_id}",
            "spec_path": f"specs/{task_id}.spec.json",
            "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            "spec_gate": "PASS", "executor": None, "dispatch": None,
            "evidence": [], "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME, "next": "",
        })
        (root / "tasks" / task_id / "TASK.md").write_text(
            f"# {task_id} probe\n", encoding="utf-8")


def run(tcli: Path, root: Path, *args: str) -> tuple[int, str]:
    cp = subprocess.run(
        [sys.executable, "-B", str(tcli), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    text = out if not err else f"{out}\n[stderr]\n{err}"
    return cp.returncode, text


def state(root: Path) -> str:
    record = json.loads((root / "tasks" / "TEST-NEW" / "record.json")
                        .read_text(encoding="utf-8"))
    ledger = (root / "ledger" / "primary.jsonl")
    events = 0
    if ledger.exists():
        events = sum(1 for line in ledger.read_text(encoding="utf-8").splitlines()
                     if line.strip())
    return f"TEST-NEW status={record.get('status')} ledger_events={events}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: dependency_probe.py <towerctl.py> [label]", file=sys.stderr)
        return 2
    tcli = Path(argv[1]).resolve()
    label = argv[2] if len(argv) > 2 else tcli.as_posix()
    print(f"== {label} ({tcli})")
    check_root = Path(tempfile.mkdtemp(prefix="dep-probe-check-"))
    build_tower(check_root)
    rc, out = run(tcli, check_root, "check", "--task", "TEST-NEW", "--phase", "ready")
    print(f"-- check --phase ready -> exit {rc}")
    print(out)
    print("after:", state(check_root))
    dispatch_root = Path(tempfile.mkdtemp(prefix="dep-probe-dispatch-"))
    build_tower(dispatch_root)
    tcli_fixed = tcli
    rc, out = run(tcli_fixed, dispatch_root, "dispatch", "--task", "TEST-NEW",
                  "--executor", "exec-a")
    print(f"-- dispatch -> exit {rc}")
    print(out)
    print("after:", state(dispatch_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
