#!/usr/bin/env python3
"""PILOT-059 probe: exercise the per-card acceptance CLI on a throw-away root.

Writes nothing outside its own temp directory.  Every step prints the command,
the exit code and the decisive fragment, so ``probe.txt`` is a readable log::

    python -B scratch/acceptance_probe.py > scratch/probe.txt
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOWER = Path(__file__).resolve().parents[1] / "tower-dsh"
CLI = TOWER / "tools" / "towerctl.py"
TASK = "PILOT-702"


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    cp = subprocess.run([sys.executable, "-B", str(CLI), "--root", str(root), *args],
                        capture_output=True, text=True, encoding="utf-8")
    return cp


def show(label: str, cp: subprocess.CompletedProcess) -> None:
    payload = {}
    try:
        payload = json.loads(cp.stdout)
    except ValueError:
        pass
    detail = payload.get("errors") or payload.get("ok")
    print(f"[{cp.returncode}] {label}: {detail}")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pilot059-probe-") as raw:
        root = Path(raw)
        for name in ("primary", "ledger", "specs", "state"):
            (root / name).mkdir(parents=True, exist_ok=True)
        spec = {
            "schema": "tower/spec@2", "id": TASK,
            "title": "probe card", "authority": "workspace_write",
            "scope": ["probe the acceptance list"],
            "worktree": f"pilot/worktrees/{TASK}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "objective": {"problem": "probe the per-card acceptance list",
                          "outcome": "probe exercises every accept branch",
                          "approach": "drive the real CLI on a temp root",
                          "non_goals_and_done": "done when all steps print"},
        }
        write_json(root / "specs" / f"{TASK}.spec.json", spec)
        (root / "pilot" / "worktrees" / TASK).mkdir(parents=True)

        print("== task-new ==")
        show("task-new", cli(root, "task-new", "--spec", f"specs/{TASK}.spec.json"))
        data = json.loads((root / "tasks" / TASK / "ACCEPTANCE.json").read_text("utf-8"))
        print("json:", json.dumps(data, ensure_ascii=False))
        print("md-table:", [line for line in
                            (root / "tasks" / TASK / "ACCEPTANCE.md").read_text(
                                "utf-8").splitlines() if line.startswith("|")])

        print("== acceptance-add ==")
        show("add A-02 auto passed",
             cli(root, "acceptance-add", "--task", TASK, "--id", "A-02",
                 "--kind", "auto", "--status", "passed", "--note", "suite green"))
        show("add M-01 manual pending",
             cli(root, "acceptance-add", "--task", TASK, "--id", "M-01",
                 "--kind", "manual", "--status", "pending",
                 "--note", "owner runs smoke after merge"))
        show("duplicate A-02 without --replace",
             cli(root, "acceptance-add", "--task", TASK, "--id", "A-02",
                 "--kind", "auto", "--status", "failed"))
        show("unknown task",
             cli(root, "acceptance-add", "--task", "PILOT-999", "--id", "A-01",
                 "--kind", "auto", "--status", "passed"))

        print("== accept gate ==")
        record = {
            "schema": "tower/task@1", "id": TASK, "title": "probe card",
            "status": "reviewed", "authority": "workspace_write",
            "scope": ["probe"], "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"], "acceptance": ["tests"],
            "depends_on": [], "worktree": f"pilot/worktrees/{TASK}",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [], "decision": None, "closeout": None,
            "created_at": "2026-11-01T21:00:00+08:00",
            "updated_at": "2026-11-01T21:00:00+08:00", "next": "",
        }
        proof = root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("probe proof\n", encoding="utf-8")
        import hashlib
        record["evidence"] = [{
            "path": f"tasks/{TASK}/evidence/proof.txt",
            "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "bytes": proof.stat().st_size}]
        write_json(root / "tasks" / TASK / "record.json", record)

        show("A-01 still pending",
             cli(root, "accept", "--task", TASK, "--decision", "D-1"))
        show("A-01 passed, M-01 pending no flag",
             cli(root, "acceptance-add", "--task", TASK, "--id", "A-01",
                 "--kind", "auto", "--status", "passed", "--note", "",
                 "--replace"))
        show("accept without flag",
             cli(root, "accept", "--task", TASK, "--decision", "D-1"))
        show("accept with flag",
             cli(root, "accept", "--task", TASK, "--decision", "D-1",
                 "--allow-manual-pending"))
        print("[status]",
              json.loads((root / "tasks" / TASK / "record.json")
                         .read_text("utf-8"))["status"])
        print("[accept md]")
        print((root / "tasks" / TASK / "ACCEPTANCE.md").read_text("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
