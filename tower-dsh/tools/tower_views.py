"""Read-only tower views: init, wiring and startup."""
from __future__ import annotations

import uuid
from pathlib import Path
from tower_common import emit, fail, jdump, jload, now, rel
from tower_ledger import append_ledger
from tower_task import load_board
from tower_authority import authority_drift
from tower_authority_cmd import authority_state_check


def cmd_init(root: Path, args) -> None:
    for d in ["shared", "primary", "primary/registries", "primary/handoffs",
              "supervision", "tasks", "ledger", "receipts", "handoffs",
              "tools", "tools/templates", "pilot/repo", "pilot/worktrees"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    state_path = root / "primary" / "CURRENT_STATE.json"
    if not state_path.exists():
        jdump(state_path, {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "phase": "G0",
            "objective": "用 tower-dsh 的内部任务跑通控制塔首版闭环",
            "owner": {
                "name": "mac",
                "gates": {"merge": "owner", "external_call": "owner",
                          "deploy_prod": "owner", "l0_main": "owner"},
            },
            "primary": {"id": f"ctl-{uuid.uuid4()}", "session": "phase1-pilot"},
            "next_action": "创建 PILOT-001 任务卡",
            "blockers": [],
            "updated_at": now(),
            "revision": 1,
        })
    board_path = root / "primary" / "TASK_BOARD.json"
    if not board_path.exists():
        jdump(board_path, {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                           "tasks": [], "updated_at": now()})
    ledger = root / "ledger" / "primary.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.touch()
    append_ledger(root, "INIT", "primary", {"root": str(root)})
    emit({"ok": True, "root": str(root), "state": str(state_path),
          "board": str(board_path), "ledger": str(ledger)})


def cmd_wiring(root: Path, args) -> None:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    tower = root / "TOWER.md"
    add("TOWER.md", tower.exists(), rel(root, tower))
    own_agents = root / "AGENTS.md"
    own_text = own_agents.read_text(encoding="utf-8") if own_agents.exists() else ""
    add("tower/AGENTS.md -> TOWER.md", "TOWER.md" in own_text, rel(root, own_agents))
    parent_agents = root.parent / "AGENTS.md"
    parent_text = parent_agents.read_text(encoding="utf-8") if parent_agents.exists() else ""
    add("workspace/AGENTS.md -> tower-dsh/TOWER.md",
        "tower-dsh/TOWER.md" in parent_text, str(parent_agents))
    start = root / "START-HERE.md"
    start_text = start.read_text(encoding="utf-8") if start.exists() else ""
    add("START-HERE.md -> CURRENT_STATE", "CURRENT_STATE" in start_text, rel(root, start))
    profile = root / "shared" / "PROJECT_PROFILE.json"
    if profile.exists():
        try:
            data = jload(profile)
            root_ok = Path(data.get("workspace_root", "")).exists()
            add("PROJECT_PROFILE.workspace_root exists", root_ok,
                data.get("workspace_root", ""))
        except Exception as exc:
            add("PROJECT_PROFILE parse", False, str(exc))
    else:
        add("PROJECT_PROFILE exists", False, rel(root, profile))
    for name in ["primary/CURRENT_STATE.json", "primary/TASK_BOARD.json"]:
        p = root / name
        try:
            jload(p)
            add(f"{name} parse", True, rel(root, p))
        except Exception as exc:
            add(f"{name} parse", False, str(exc))
    failed = [c for c in checks if not c["ok"]]
    if failed:
        emit({"ok": False, "status": "ORPHANED", "checks": checks}, 2)
    emit({"ok": True, "status": "WIRED", "checks": checks})


def cmd_startup(root: Path, args) -> None:
    required = [
        "TOWER.md", "AGENTS.md", "START-HERE.md",
        "shared/PROJECT_PROFILE.json", "shared/AUTHORITY_MODEL.json",
        "primary/CURRENT_STATE.json", "primary/TASK_BOARD.json",
        "ledger/primary.jsonl",
    ]
    errors = [f"missing: {p}" for p in required if not (root / p).exists()]
    if errors:
        fail(errors)
    state = jload(root / "primary" / "CURRENT_STATE.json")
    if state.get("role") != "primary":
        errors.append("current state role is not primary")
    if not (state.get("primary") or {}).get("id"):
        errors.append("primary.id missing")
    if not (state.get("owner") or {}).get("name"):
        errors.append("owner.name missing")
    if errors:
        fail(errors)
    board = load_board(root)
    drift = authority_drift(root)
    authority = authority_state_check(root)
    emit({"ok": True, "tower_id": state.get("tower_id"), "role": state.get("role"),
          "phase": state.get("phase"), "primary": state.get("primary"),
          "tasks": len(board.get("tasks", [])), "next_action": state.get("next_action"),
          "authority_dirty_count": None if drift is None else len(drift),
          "authority_state": authority["status"]})
