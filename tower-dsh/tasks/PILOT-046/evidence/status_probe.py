"""PILOT-046 probe: exercise the four status commands and contrast main vs now.

Run from the worktree root::

    python -B scratch/status_probe.py

Every command runs against throw-away towers under ``TMP``; the real tower is
only read (for its own ``campaign-check``), never written.  Outputs:

* ``scratch/probe.txt``          — new-code behaviour + byte-stability evidence
* ``scratch/probe-old-code.txt`` — ``main``'s code vs the new code
* ``scratch/index-sample.json``  — a sample ``status/index.json``

``scratch/old/towerctl.py`` is the ``main`` version of the tool, extracted with
``git show main:tower-dsh/tools/towerctl.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parent
TOWER = WORKTREE / "tower-dsh"
NEW = TOWER / "tools" / "towerctl.py"
OLD = HERE / "old" / "towerctl.py"
DAY = "2026-10-28"
WEEK = "2026-W44"


def write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(board: str = '{"schema": "tower/task-board@1", "tasks": [{"id": "PILOT-045"}]}') -> Path:
    """A valid strategy/campaign/board/records tower under TMP."""
    root = Path(tempfile.mkdtemp(prefix="pilot046-probe-")) / "tower"
    write(root, "command/STRATEGY.md",
          "---\nschema: tower/strategy@1\nid: S-2026-Q4\nhorizon: 2026-Q4\n"
          "owner: mac\nstatus: active\nreview_by: 2026-12-31\n"
          "goals:\n  - id: G1\n    text: 可信交付\n"
          "non_goals:\n  - 多写者并行\n---\n# 战略\n")
    write(root, "command/campaigns/C-2026-Q4-01.md",
          "---\nschema: tower/campaign@1\nid: C-2026-Q4-01\ngoal: G1\n"
          "status: active\nowner: mac\nobjective: \"状态历史\"\n"
          "task_forces:\n  - PILOT-045\nsequence: \"046\"\n"
          "budget: \"2 cards / 2 weeks\"\nwip_limit: 1\n"
          "review_by: 2026-11-30\n---\n# 战役\n")
    write(root, "primary/TASK_BOARD.json", board)
    write(root, "primary/CURRENT_STATE.json",
          '{"schema": "tower/current-state@1", "owner": {"name": "mac"}}')
    write(root, "tasks/PILOT-045/record.json",
          '{"schema": "tower/task@1", "id": "PILOT-045", "status": "closed"}')
    write(root, "tasks/PILOT-046/record.json",
          '{"schema": "tower/task@1", "id": "PILOT-046", '
          '"status": "dispatched", "review": {"verdict": "PASS"}}')
    return root


def env() -> dict[str, str]:
    """``main``'s tool lives outside ``tools/``; keep its sibling imports working."""
    return {**os.environ, "PYTHONPATH": str(TOWER / "tools")}


def run(tool: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env())


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def show(label: str, cp: subprocess.CompletedProcess) -> list[str]:
    lines = [f"$ {label}", f"exit: {cp.returncode}"]
    if cp.stdout.strip():
        lines += ["stdout:", cp.stdout.strip()]
    if cp.stderr.strip():
        lines += ["stderr:", cp.stderr.strip()]
    return lines


def new_status_probe() -> tuple[list[str], dict]:
    """Drive the four new commands and record their bytes."""
    root = fixture()
    lines = ["== fixture ==", f"throw-away tower: {root}", ""]
    lines.append("== new commands ==")
    for args in (("status-snapshot", "--task", "PILOT-046", "--event", "dispatched",
                  "--note", "initial status history", "--tests", "486",
                  "--at", f"{DAY}T10:00:00"),
                 ("status-snapshot", "--task", "PILOT-046", "--event", "note",
                  "--note", "index/rollup generated", "--at", f"{DAY}T11:30:00"),
                 ("status-index",),
                 ("status-rollup", "--week", WEEK),
                 ("status-archive", "--before", "2026-10-29")):
        lines += show(" ".join(args), run(NEW, root, *args))
    lines += ["", "== status/2026-10-28.md (two appended entries) =="]
    day_file = root / "status" / f"{DAY}.md"
    lines += day_file.read_text(encoding="utf-8").splitlines()
    index_file = root / "status" / "index.json"
    index_bytes = index_file.read_bytes()
    lines += ["", "== status/index.json =="]
    lines += index_bytes.decode("utf-8").splitlines()
    lines += ["", "== byte stability =="]
    run(NEW, root, "status-index")
    lines.append(f"index rerun identical: {index_file.read_bytes() == index_bytes}")
    index_file.unlink()
    run(NEW, root, "status-index")
    lines.append(f"index rebuilt after delete identical: "
                 f"{index_file.read_bytes() == index_bytes}")
    weekly = root / "status" / "weekly" / f"{WEEK}.md"
    weekly_first = weekly.read_bytes()
    run(NEW, root, "status-rollup", "--week", WEEK)
    lines.append(f"rollup rerun identical: {weekly.read_bytes() == weekly_first}")
    archive = root / "status" / "archive" / "2026-Q4.md"
    archive_first = archive.read_bytes()
    run(NEW, root, "status-archive", "--before", "2026-10-29")
    lines.append(f"archive rerun identical: {archive.read_bytes() == archive_first}")
    lines.append(f"snapshots kept by archive: "
                 f"{(root / 'status' / f'{DAY}.md').is_file()}")
    lines += ["", "== status/weekly/2026-W44.md =="]
    lines += weekly_first.decode("utf-8").splitlines()
    (HERE / "index-sample.json").write_bytes(index_bytes)
    lines += ["", f"index-sample.json sha256: {sha_bytes(index_bytes)}"]
    return lines, {"root": root, "index": index_bytes}


def old_code_probe() -> list[str]:
    """Contrast ``main``'s tool (no status commands, board traceback) with now."""
    lines = ["== old code ==",
             f"source: git show main:tower-dsh/tools/towerctl.py -> {OLD}",
             f"sha256: {sha_bytes(OLD.read_bytes())}"
             if OLD.is_file() else "MISSING: run the extraction step first", ""]
    if not OLD.is_file():
        return lines
    root = fixture()
    lines += show("main: status-snapshot --task PILOT-046 --event note",
                  run(OLD, root, "status-snapshot", "--task", "PILOT-046",
                      "--event", "note"))
    lines += show("main: status-index", run(OLD, root, "status-index"))
    lines += show("main: status-rollup --week " + WEEK,
                  run(OLD, root, "status-rollup", "--week", WEEK))
    lines += show("main: status-archive --before 2026-10-29",
                  run(OLD, root, "status-archive", "--before", "2026-10-29"))
    lines += ["", "== board [] =="]
    bad = fixture(board="[]")
    old_bad = run(OLD, bad, "campaign-check")
    lines += show("main: campaign-check (board [])", old_bad)
    new_bad = run(NEW, bad, "campaign-check")
    lines += show("now: campaign-check (board [])", new_bad)
    traceback = "Traceback" in (old_bad.stdout + old_bad.stderr)
    lines += ["", f"old traceback: {traceback}",
              f"new exit 2 with E7: "
              f"{'\"E7\"' in new_bad.stdout and new_bad.returncode == 2}"]
    return lines


def main() -> int:
    for required in (NEW,):
        if not required.is_file():
            print(f"missing {required}")
            return 1
    lines, _ = new_status_probe()
    probe = "\n".join(lines) + "\n"
    (HERE / "probe.txt").write_text(probe, encoding="utf-8")
    old = "\n".join(old_code_probe()) + "\n"
    (HERE / "probe-old-code.txt").write_text(old, encoding="utf-8")
    print(probe)
    print(old)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
