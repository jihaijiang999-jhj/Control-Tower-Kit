"""Read-only probe for PILOT-055 re-dispatch repair.

Compares the *old* DISPATCH source-state table with the repaired one against
the real tower ledger, then runs ``state-verify`` through the worktree CLI.
The real tower is only read: no record, board or ledger byte is written.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
# The worktree holds its own copy of the tower; the real tower is two levels
# above the task worktree (PILOT-055 -> worktrees -> pilot -> tower-dsh).
TOWER = WORKTREE / "tower-dsh"
REAL = WORKTREE.parents[2]
TCLI = TOWER / "tools" / "towerctl.py"

sys.path.insert(0, str(TOWER / "tools"))
import towerctl  # noqa: E402


def transitions_for(table: frozenset) -> list[dict]:
    original = towerctl.TASK_TRANSITIONS["DISPATCH"]
    towerctl.TASK_TRANSITIONS["DISPATCH"] = table
    try:
        rows: list[dict] = []
        states = towerctl.replay_task_statuses(REAL, rows)
    finally:
        towerctl.TASK_TRANSITIONS["DISPATCH"] = original
    return [row for row in rows if row["target"] == "PILOT-055"], states


def main() -> int:
    print(f"tower root: {REAL}")
    print(f"repaired DISPATCH sources: "
          f"{sorted(towerctl.TASK_TRANSITIONS['DISPATCH'])}")

    events = towerctl.ledger_payloads_by_task(REAL, "DISPATCH").get(
        "PILOT-055", [])
    print(f"PILOT-055 DISPATCH events: {len(events)}")
    for index, event in enumerate(events, start=1):
        print(f"  [{index}] executor={event.get('executor')!r} "
              f"kind={event.get('kind')!r} at={event.get('at')!r}")

    old_rows, old_states = transitions_for(frozenset({"ready", "rework"}))
    new_rows, new_states = transitions_for(
        frozenset({"ready", "rework", "dispatched"}))
    print(f"old table drift rows: {old_rows}")
    print(f"new table drift rows: {new_rows}")
    print(f"old folded status: {old_states.get('PILOT-055')!r}")
    print(f"new folded status: {new_states.get('PILOT-055')!r}")

    cp = subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(REAL),
         "state-verify"],
        capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(cp.stdout)
    print(f"state-verify exit: {cp.returncode}")
    print(f"state-verify drift: {payload['drift']}")
    print(f"state-verify tasks: {payload['tasks']} "
          f"envelopes: {payload['envelopes']}")
    return 0 if cp.returncode == 0 and not new_rows and old_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
