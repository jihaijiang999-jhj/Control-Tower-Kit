"""PILOT-032 probe: TASK_NEW rebuild rules on isolated temporary towers.

Builds one throw-away tower per case through the real ``towerctl`` ledger
helpers (hash chain included) and drives the ``state-verify`` CLI exactly like
the control plane does.  Never touches the real tower.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TCLI = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
sys.path.insert(0, str(TCLI.parent))
import towerctl  # noqa: E402


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def new_tower(root: Path) -> None:
    for directory in ("ledger", "primary", "tasks", "supervision",
                      "supervision/envelopes"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()


def primary(root: Path, event_type: str, **payload) -> None:
    towerctl.append_ledger(root, event_type, "primary", payload)


def finish(root: Path, status: str) -> None:
    write_json(root / "tasks" / "T-001" / "record.json",
               {"schema": "tower/task@1", "id": "T-001",
                "title": "T-001", "status": status})
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                "tasks": [{"id": "T-001", "title": "T-001",
                           "status": status}]})
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})


def lifecycle(root: Path, *, close: bool) -> None:
    for event_type in ("TASK_NEW", "DISPATCH", "DELIVER"):
        primary(root, event_type, task="T-001")
    primary(root, "CHECKBACK", task="T-001", verdict="PASS")
    primary(root, "ACCEPT", task="T-001", decision="D-001")
    if close:
        primary(root, "CLOSEOUT", task="T-001",
                closeout="tasks/T-001/CLOSEOUT.md")


def run_case(name: str, build, expected_status: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="pilot032-probe-") as tmp:
        root = Path(tmp)
        new_tower(root)
        build(root)
        finish(root, expected_status)
        proc = subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(root),
             "state-verify"],
            capture_output=True, text=True, encoding="utf-8")
        out = json.loads(proc.stdout)
        return {"case": name, "exit": proc.returncode, "ok": out["ok"],
                "tasks": out["tasks"], "drift": out["drift"]}


def first_task_new(root: Path) -> None:
    primary(root, "TASK_NEW", task="T-001")


def dispatched_rebuild(root: Path) -> None:
    for event_type in ("TASK_NEW", "DISPATCH", "TASK_NEW"):
        primary(root, event_type, task="T-001")


def closed_rebuild(root: Path) -> None:
    lifecycle(root, close=True)
    primary(root, "TASK_NEW", task="T-001")


def accepted_rebuild(root: Path) -> None:
    lifecycle(root, close=False)
    primary(root, "TASK_NEW", task="T-001")


def main() -> int:
    cases = [
        run_case("first TASK_NEW (None -> ready)", first_task_new, "ready"),
        run_case("dispatched -> TASK_NEW (in-flight rebuild)",
                 dispatched_rebuild, "ready"),
        run_case("closed -> TASK_NEW (completed reset)", closed_rebuild,
                 "ready"),
        run_case("accepted -> TASK_NEW (completed reset)", accepted_rebuild,
                 "ready"),
    ]
    print(json.dumps(cases, ensure_ascii=False, indent=2))
    print("\nMATRIX")
    print(f"{'case':46} {'exit':>4} {'ok':>5}  drift")
    for case in cases:
        kinds = ",".join(item["kind"] for item in case["drift"]) or "-"
        print(f"{case['case']:46} {case['exit']:>4} "
              f"{str(case['ok']):>5}  {kinds}")
    illegal = [c for c in cases if c["drift"]]
    return 0 if len(illegal) == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
