"""PILOT-071 end-to-end probe: task-supersede on a throw-away 069/070 tower.

Runs the real ``towerctl`` CLI through ``subprocess`` (never the in-process
functions) so the probe observes exactly what an operator observes.  The probe
must write nothing outside its temporary tower.

    cd <worktree>\\tower-dsh
    python -B ..\\scratch\\supersede_probe.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH = Path(__file__).resolve().parent
TOWER = SCRATCH.parent / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
sys.path.insert(0, str(TOWER / "tools"))
import towerctl  # noqa: E402  (the hash-chained ledger writer)

CURRENT_STATE = {"schema": "tower/current-state@1", "owner": {"name": "mac"}}
ROADMAP = tuple(f"PILOT-{number:03d}" for number in range(61, 71))
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def write_json(root: Path, relpath: str, data) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def add_card(root: Path, task_id: str, status: str) -> None:
    write_json(root, f"tasks/{task_id}/record.json", {
        "schema": "tower/task@1", "id": task_id, "title": f"{task_id} card",
        "status": status, "next": "probe"})
    board_path = root / "primary" / "TASK_BOARD.json"
    board = (json.loads(board_path.read_text(encoding="utf-8"))
             if board_path.is_file() else {"schema": "tower/task-board@1",
                                           "tower_id": "tower-dsh",
                                           "tasks": []})
    tasks = [entry for entry in board["tasks"] if entry["id"] != task_id]
    tasks.append({"id": task_id, "title": f"{task_id} card", "status": status})
    board["tasks"] = tasks
    write_json(root, "primary/TASK_BOARD.json", board)


def lifecycle(root: Path, task_id: str, closed: bool = False) -> None:
    def event(event_type: str, **payload) -> None:
        towerctl.append_ledger(root, event_type, "primary",
                               {"task": task_id, **payload})

    event("TASK_NEW", title=f"{task_id} card")
    event("DISPATCH", executor=f"exec-{task_id[-3:]}",
          worktree=f"pilot/worktrees/{task_id}")
    event("DELIVER", evidence=0)
    if closed:
        event("CHECKBACK", reviewer="rev-070", verdict="PASS")
        event("ACCEPT", decision="D-PILOT-070")
        event("CLOSEOUT", closeout="tasks/PILOT-070/CLOSEOUT.md")


def campaign(root: Path) -> None:
    lines = ["---", "schema: tower/campaign@1", "id: C-2026-Q4-04",
             "goal: G2", "status: active", "owner: mac",
             'objective: "交付硬化"', "key_results:", '  - "TASK_SUPERSEDE"',
             "roadmap:"]
    lines += [f"  - {task_id}" for task_id in ROADMAP]
    lines += ["current: PILOT-070", "task_forces:"]
    lines += [f"  - {task_id}" for task_id in ROADMAP
              if task_id != "PILOT-069"]
    lines += ['sequence: "061 → 070"', "stop_conditions:", '  - "drift 停"',
              'budget: "12 张卡 / 12 周"', "wip_limit: 1",
              "review_by: 2026-11-20", "---", "# C-2026-Q4-04 — 交付硬化", ""]
    path = root / "command" / "campaigns" / "C-2026-Q4-04.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build(root: Path) -> None:
    for name in ("primary", "ledger", "state", "supervision/envelopes"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    write_json(root, "primary/CURRENT_STATE.json", CURRENT_STATE)
    write_json(root, "supervision/MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})
    lifecycle(root, "PILOT-069")
    lifecycle(root, "PILOT-070", closed=True)
    for task_id, status in (("PILOT-069", "delivered"),
                            ("PILOT-070", "closed"), ("PILOT-071", "ready")):
        add_card(root, task_id, status)
    for task_id in ROADMAP[:-2]:
        add_card(root, task_id, "closed")
    campaign(root)


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def events(root: Path, name: str) -> list[dict]:
    path = root / "ledger" / f"{name}.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    tmp = tempfile.TemporaryDirectory(prefix="pilot071-probe-",
                                      ignore_cleanup_errors=True)
    root = Path(tmp.name) / "tower"
    build(root)

    cp = run(root, "task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-070", "--reason", "070 replaces 069", "--by", "mac")
    payload = json.loads(cp.stdout) if cp.stdout.strip() else {}
    check("delivered -> superseded exits 0", cp.returncode == 0,
          cp.stdout + cp.stderr)
    check("response status is superseded", payload.get("status") == "superseded")
    record = json.loads((root / "tasks/PILOT-069/record.json")
                        .read_text(encoding="utf-8"))
    check("record.status is superseded", record.get("status") == "superseded")
    check("record.superseded_by is PILOT-070",
          record.get("superseded_by") == "PILOT-070")
    board = json.loads((root / "primary/TASK_BOARD.json")
                       .read_text(encoding="utf-8"))
    entry = next(item for item in board["tasks"] if item["id"] == "PILOT-069")
    check("board.status is superseded", entry.get("status") == "superseded")
    supersede = [event for event in events(root, "primary")
                 if event["type"] == "TASK_SUPERSEDE"]
    check("exactly one TASK_SUPERSEDE in the primary ledger",
          len(supersede) == 1)
    check("payload keys are task/by/reason/superseded_by/at",
          sorted(supersede[0]["payload"]) == ["at", "by", "reason",
                                              "superseded_by", "task"]
          if supersede else False)
    registry = json.loads((root / "state/TASK_IDS.json")
                          .read_text(encoding="utf-8"))["ids"]
    check("TASK_IDS voids PILOT-069", registry["PILOT-069"]["status"] == "void")
    check("no envelope was created",
          list((root / "supervision/envelopes").glob("*.json")) == [])
    check("no MERGE event anywhere",
          all(event["type"] != "MERGE"
              for name in ("primary", "supervision")
              for event in events(root, name)))
    verify = run(root, "state-verify")
    check("state-verify is clean",
          verify.returncode == 0
          and json.loads(verify.stdout)["drift"] == [],
          verify.stdout + verify.stderr)

    before = snapshot(root)
    repeat = run(root, "task-supersede", "--task", "PILOT-069", "--by-task",
                 "PILOT-070", "--reason", "again", "--by", "mac")
    check("repeat supersede exits 2", repeat.returncode == 2)
    check("repeat supersede writes nothing", snapshot(root) == before)

    for name, task_id, target, by in (
            ("closed card", "PILOT-070", "PILOT-071", "mac"),
            ("non-owner", "PILOT-071", "PILOT-069", "intruder"),
            ("missing target", "PILOT-071", "PILOT-999", "mac")):
        baseline = snapshot(root)
        refused = run(root, "task-supersede", "--task", task_id,
                      "--by-task", target, "--reason", "probe", "--by", by)
        check(f"{name} exits 2", refused.returncode == 2,
              refused.stdout + refused.stderr)
        check(f"{name} writes nothing", snapshot(root) == baseline)

    where = run(root, "where", "--json")
    position = json.loads(where.stdout) if where.stdout.strip() else {}
    check("where exits 0", where.returncode == 0, where.stdout + where.stderr)
    check("where total is 10", position.get("total") == 10)
    check("where index is 10/10", position.get("index") == 10)
    check("where next is None", position.get("next") is None)
    nodes = {node["id"]: node["status"] for node in position.get("nodes", [])}
    check("where counts PILOT-069 done", nodes.get("PILOT-069") == "done")
    check("where counts every node done",
          all(status == "done" for status in nodes.values()))
    human = run(root, "where")
    check("human bar shows a done 069", "[✅069]" in human.stdout)
    check("human view says 10/10", "位置 10/10" in human.stdout)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"SUMMARY {passed}/{len(CHECKS)} checks passed")
    tmp.cleanup()
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
