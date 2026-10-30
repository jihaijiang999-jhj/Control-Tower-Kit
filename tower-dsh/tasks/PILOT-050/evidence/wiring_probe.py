"""PILOT-050 wiring probe: new vs old (main) dispatch / campaign-check.

Builds throw-away tower fixtures under the system temp dir, drives both the
worktree ``towerctl`` (new) and ``scratch/old/towerctl.py`` (main baseline)
through ``subprocess``, and prints one line per observable fact.  No network,
no external dependencies.

    python scratch/wiring_probe.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
NEW = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
OLD = WORKTREE / "scratch" / "old" / "towerctl.py"
TOWER_TOOLS = WORKTREE / "tower-dsh" / "tools"
TASK_ID = "TEST-PROBE-001"
LEGACY = [f"PILOT-{index:03d}" for index in range(1, 45)]


def run(tcli: Path, root: Path, *args: str) -> tuple[int, dict, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TOWER_TOOLS)
    cp = subprocess.run(
        [sys.executable, "-B", str(tcli), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        payload = {}
    return cp.returncode, payload, cp.stdout + cp.stderr


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: dict) -> None:
    write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def campaign(legacy=LEGACY, forces=(TASK_ID,), budget="8 张卡 / 8 周") -> str:
    lines = ["---", "schema: tower/campaign@1", "id: C-PROBE", "goal: G2",
             "status: active", "owner: mac", 'objective: "probe"',
             f'budget: "{budget}"', "wip_limit: 9", "review_by: 2026-12-31",
             "roadmap:", f"  - {TASK_ID}", "current: " + TASK_ID, "task_forces:"]
    lines += [f"  - {task_id}" for task_id in forces]
    if legacy is not None:
        lines += ["legacy_cards:"] + [f"  - {task_id}" for task_id in legacy]
    lines.append("---")
    return "\n".join(lines) + "\n"


def build(root: Path, *, dispatch_card: bool = True,
          board=() , legacy=LEGACY, closed_cards=()) -> None:
    for directory in ("primary", "ledger", "specs",
                      f"tasks/{TASK_ID}", f"pilot/worktrees/{TASK_ID}"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    spec = root / "specs" / "task.spec.json"
    write_json(spec, {"schema": "tower/spec@1", "id": TASK_ID, "title": "probe",
                      "authority": "workspace_write", "scope": ["probe"],
                      "worktree": f"pilot/worktrees/{TASK_ID}",
                      "allowed_paths": [], "forbidden": [], "acceptance": []})
    write_json(root / "tasks" / TASK_ID / "record.json", {
        "schema": "tower/task@1", "id": TASK_ID, "title": "probe",
        "status": "ready", "executor": None, "dispatch": None,
        "worktree": f"pilot/worktrees/{TASK_ID}",
        "spec_path": "specs/task.spec.json",
        "spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "spec_gate": "PASS", "created_at": "2026-10-30T00:00:00+08:00",
        "updated_at": "2026-10-30T00:00:00+08:00", "next": "",
    })
    write(root / "tasks" / TASK_ID / "TASK.md", f"# {TASK_ID}\n")
    write(root / "command" / "STRATEGY.md", "\n".join([
        "---", "schema: tower/strategy@1", "id: S-PROBE", 'title: "probe"',
        "goals:", "  - id: G2", '    text: "probe"', "review_by: 2026-12-31",
        "non_goals: []", "---", "", "# S-PROBE", ""]))
    write(root / "command" / "campaigns" / "C-PROBE.md", campaign(legacy=legacy))
    board_ids = list(board) or LEGACY
    write_json(root / "primary" / "TASK_BOARD.json", {
        "schema": "tower/task-board@1",
        "tasks": [{"id": task_id, "status": "closed"} for task_id in board_ids]})
    for task_id in closed_cards:
        write_json(root / "tasks" / task_id / "record.json", {
            "schema": "tower/task@1", "id": task_id, "title": task_id,
            "status": "closed"})


def record_of(root: Path) -> dict:
    return json.loads((root / "tasks" / TASK_ID / "record.json")
                      .read_text(encoding="utf-8"))


def ledger_payload(root: Path) -> dict | None:
    path = root / "ledger" / "primary.jsonl"
    if not path.is_file():
        return None
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    return json.loads(rows[-1])["payload"] if rows else None


def line(label: str, **facts) -> None:
    print(f"{label}: " + ", ".join(f"{key}={value}" for key, value in facts.items()))


def probe_dispatch() -> None:
    for label, tcli in (("old main", OLD), ("new", NEW)):
        with tempfile.TemporaryDirectory(prefix="probe-dispatch-") as tmp:
            root = Path(tmp)
            build(root)
            code, payload, _ = run(tcli, root, "dispatch", "--task", TASK_ID,
                                   "--executor", "probe")
            dispatch = record_of(root).get("dispatch") or {}
            line(f"dispatch without --campaign [{label}]", exit=code,
                 status=record_of(root).get("status"),
                 dispatch_campaign=dispatch.get("campaign", "<absent>"),
                 ledger_campaign=(ledger_payload(root) or {}).get("campaign", "<absent>"))
    with tempfile.TemporaryDirectory(prefix="probe-dispatch-") as tmp:
        root = Path(tmp)
        build(root)
        code, payload, _ = run(NEW, root, "dispatch", "--task", TASK_ID,
                               "--executor", "probe", "--campaign", "C-PROBE")
        dispatch = record_of(root).get("dispatch") or {}
        line("dispatch --campaign C-PROBE [new]", exit=code,
             record_campaign=dispatch.get("campaign"),
             ledger_campaign=(ledger_payload(root) or {}).get("campaign"))


def probe_campaign_check() -> None:
    for label, tcli in (("old main", OLD), ("new", NEW)):
        with tempfile.TemporaryDirectory(prefix="probe-campaign-") as tmp:
            root = Path(tmp)
            build(root, board=LEGACY + [TASK_ID])
            code, payload, _ = run(tcli, root, "campaign-check")
            warnings = payload.get("warnings", [])
            w1 = [item for item in warnings if item.get("code") == "W1"]
            line(f"campaign-check [{label}]", exit=code, W1=len(w1),
                 W4=sum(1 for item in warnings if item.get("code") == "W4"),
                 errors=len(payload.get("errors", [])))


def probe_w1_sources() -> None:
    with tempfile.TemporaryDirectory(prefix="probe-w1-") as tmp:
        root = Path(tmp)
        build(root, board=["PILOT-070", "PILOT-071", "PILOT-072"],
              legacy=["PILOT-072"])
        (root / "command" / "campaigns" / "C-PROBE.md").write_text(
            campaign(legacy=["PILOT-072"], forces=("PILOT-070",)),
            encoding="utf-8")
        for task_id in ("PILOT-070", "PILOT-071", "PILOT-072"):
            write_json(root / "tasks" / task_id / "record.json", {
                "schema": "tower/task@1", "id": task_id,
                "status": "closed", "executor": None})
        write_json(root / "tasks" / "PILOT-071" / "record.json", {
            "schema": "tower/task@1", "id": "PILOT-071", "status": "closed",
            "dispatch": {"executor": "e", "campaign": "C-PROBE"}})
        code, payload, _ = run(NEW, root, "campaign-check")
        w1 = [item for item in payload.get("warnings", []) if item["code"] == "W1"]
        line("W1 three sources (task_forces/dispatch.campaign/legacy_cards)",
             exit=code, W1=len(w1), targets=[item["target"] for item in w1])
        (root / "command" / "campaigns" / "C-PROBE.md").write_text(
            campaign(legacy=None, forces=("PILOT-070",)), encoding="utf-8")
        code, payload, _ = run(NEW, root, "campaign-check")
        w1 = [item for item in payload.get("warnings", []) if item["code"] == "W1"]
        line("W1 without legacy_cards", exit=code, W1=len(w1),
             targets=[item["target"] for item in w1])


def probe_w2_open_only() -> None:
    ids = ["PILOT-080", "PILOT-081", "PILOT-082"]
    with tempfile.TemporaryDirectory(prefix="probe-w2-") as tmp:
        root = Path(tmp)
        build(root, board=ids, legacy=None)
        (root / "command" / "campaigns" / "C-PROBE.md").write_text(
            "\n".join(["---", "schema: tower/campaign@1", "id: C-PROBE",
                       "goal: G2", "status: active", "owner: mac",
                       'budget: "2 张卡 / 8 周"', "wip_limit: 9",
                       "review_by: 2026-12-31", "task_forces:",
                       *[f"  - {task_id}" for task_id in ids], "---"]),
            encoding="utf-8")
        for task_id in ids:
            write_json(root / "tasks" / task_id / "record.json", {
                "schema": "tower/task@1", "id": task_id, "status": "dispatched"})
        write_json(root / "tasks" / ids[0] / "record.json", {
            "schema": "tower/task@1", "id": ids[0], "status": "closed"})
        code, payload, _ = run(NEW, root, "campaign-check")
        w2 = [item for item in payload.get("warnings", []) if item["code"] == "W2"]
        line("W2 one closed + two open, budget 2", exit=code, W2=len(w2))
        write_json(root / "tasks" / ids[0] / "record.json", {
            "schema": "tower/task@1", "id": ids[0], "status": "dispatched"})
        code, payload, _ = run(NEW, root, "campaign-check")
        w2 = [item for item in payload.get("warnings", []) if item["code"] == "W2"]
        line("W2 three open, budget 2", exit=code, W2=len(w2),
             detail=w2[0]["detail"] if w2 else "")


def probe_post_merge_gates() -> None:
    sys.path.insert(0, str(NEW.parent))
    import towerctl  # noqa: E402

    with tempfile.TemporaryDirectory(prefix="probe-pm-") as tmp:
        root = Path(tmp)
        line("post-merge gates, no campaign/arch",
             names=[check["name"] for check in towerctl.wiring_checks(root)])
        write(root / "command" / "STRATEGY.md", "\n".join([
            "---", "schema: tower/strategy@1", "id: S-PROBE", 'title: "probe"',
            "goals:", "  - id: G2", '    text: "probe"', "review_by: 2026-12-31",
            "non_goals: []", "---", "", "# S-PROBE", ""]))
        (root / "command" / "campaigns").mkdir(parents=True, exist_ok=True)
        (root / "command" / "campaigns" / "C-PROBE.md").write_text(
            campaign(legacy=None, forces=()), encoding="utf-8")
        checks = towerctl.wiring_checks(root)
        line("post-merge gates, campaign only", names=[c["name"] for c in checks],
             ok=[c["ok"] for c in checks])
        write_json(root / "arch" / "GATES.json", {})
        checks = towerctl.wiring_checks(root)
        line("post-merge gates, campaign + broken arch",
             names=[c["name"] for c in checks], ok=[c["ok"] for c in checks])


def main() -> None:
    print(f"new towerctl: {NEW}")
    print(f"old towerctl: {OLD}")
    print()
    probe_dispatch()
    print()
    probe_campaign_check()
    print()
    probe_w1_sources()
    print()
    probe_w2_open_only()
    print()
    probe_post_merge_gates()


if __name__ == "__main__":
    main()
