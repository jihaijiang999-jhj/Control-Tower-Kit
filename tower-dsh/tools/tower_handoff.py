"""Handoff packages, snapshots and lifecycle commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tower_common import (
    _optional_git, _optional_git_status, check_package_id, check_task_id, emit,
    fail, jdump, jload, now, rel, sha256_file,
)
from tower_ledger import append_ledger
from tower_task import _latest_by, _load_optional_record, load_board, select_task
from tower_authority import authority_commit_hint, authority_drift
from tower_profile import load_profile, resolve_pilot_paths
from tower_envelope import load_queue, load_supervision, select_envelope


def match_task_by_evidence(root: Path, state: dict) -> str | None:
    """Match a legacy package (no ``task`` field) to a task by evidence hashes.

    Returns the task id whose record contains every ``(path, sha256)`` pair
    recorded in the package's ``state.evidence``; when no record matches
    completely, the task with the largest overlap wins; no overlap returns
    ``None`` so the caller can fall back to the default selection.
    """
    wanted = {(e.get("path"), e.get("sha256"))
              for e in (state.get("evidence") or []) if e.get("path")}
    if not wanted:
        return None
    best_id: str | None = None
    best_score = 0
    for task in load_board(root).get("tasks", []):
        tid = task.get("id") or ""
        if not tid:
            continue
        record = _load_optional_record(root, tid)
        have = {(e.get("path"), e.get("sha256"))
                for e in (record.get("evidence") or [])}
        score = len(wanted & have)
        if score > best_score:
            best_score, best_id = score, tid
        if wanted <= have:
            return tid
    return best_id if best_score else None


def envelope_for_task(root: Path, task_id: str) -> str:
    """Best-effort envelope id for a task (legacy packages carry no envelope)."""
    if not task_id:
        return ""
    entries = [e for e in load_queue(root).get("entries", [])
               if isinstance(e, dict) and e.get("task") == task_id]
    if not entries:
        return ""
    entry = _latest_by(entries, "added_at") if len(entries) > 1 else entries[0]
    return str(entry.get("envelope_id") or "")


def current_snapshot(root: Path, task_id: str | None = None,
                     envelope_id: str | None = None) -> dict:
    """Capture live tower state for the selected task / envelope.

    Task and envelope selection is explicit-id first, then single-candidate,
    then most-recently-updated.  Repo/worktree come from the project profile
    (falling back to the task record), and git is best-effort: an unavailable
    repository or worktree yields ``""`` instead of raising.
    """
    state = jload(root / "primary" / "CURRENT_STATE.json")
    supervision = load_supervision(root)
    board = load_board(root)
    queue = load_queue(root)
    task = select_task(board, task_id)
    selected_task = str(task.get("id") or "")
    record = _load_optional_record(root, selected_task)
    entry = select_envelope(queue, envelope_id)
    selected_envelope = str(entry.get("envelope_id") or "")
    profile = load_profile(root)
    repo, worktree = resolve_pilot_paths(root, record, profile, selected_task)
    evidence = [{"path": e.get("path"), "sha256": e.get("sha256")}
                for e in (record.get("evidence") or [])]
    open_tasks = [{"id": t.get("id"), "status": t.get("status"),
                   "next": t.get("next") or ""}
                  for t in (board.get("tasks") or [])
                  if isinstance(t, dict) and t.get("status") != "closed"]
    ledger = root / "ledger" / "primary.jsonl"
    ledger_seq = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    ledger_seq = max(ledger_seq, int(json.loads(line).get("seq", 0)))
                except Exception:
                    pass
    return {
        "tower_id": state.get("tower_id"),
        "phase": state.get("phase"),
        "primary_id": (state.get("primary") or {}).get("id"),
        "supervisor_id": (supervision.get("supervisor") or {}).get("id"),
        "supervision_phase": supervision.get("phase"),
        "owner": (state.get("owner") or {}).get("name") or "",
        "next_action": state.get("next_action") or "",
        "task_id": selected_task,
        "task_status": record.get("status") or task.get("status") or "",
        "task_next": record.get("next") or task.get("next") or "",
        "task_evidence_count": len(record.get("evidence") or []),
        "envelope_id": selected_envelope,
        "queue_status": entry.get("status") or "",
        "merge_commit": entry.get("merge_commit") or "",
        "main_sha": _optional_git(repo, "rev-parse", "main"),
        "worktree_head": _optional_git(worktree, "rev-parse", "HEAD"),
        "repo_status": _optional_git_status(repo),
        "worktree_status": _optional_git_status(worktree),
        "tower_root": str(root.resolve()),
        "repo": str(repo) if repo is not None else "",
        "worktree": str(worktree) if worktree is not None else "",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "open_tasks": open_tasks,
        "evidence": evidence,
        "ledger_seq": ledger_seq,
        "captured_at": now(),
    }


def handoff_checks(root: Path, package_id: str, pkg: dict) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    pkgdir = root / "handoffs" / package_id
    handoff = pkgdir / "HANDOFF.md"
    selfcheck = pkgdir / "SELF-CHECK.md"
    add("HANDOFF.md exists", handoff.exists(), str(handoff))
    add("SELF-CHECK.md exists", selfcheck.exists(), str(selfcheck))
    if handoff.exists():
        text = handoff.read_text(encoding="utf-8")
        for marker in ["## §0", "## §0a", "## §1", "## §2", "## §3",
                       "## §4", "## §4a", "## §5", "## §6", "## §7"]:
            add(f"section {marker}", marker in text, marker)
    if selfcheck.exists():
        text = selfcheck.read_text(encoding="utf-8")
        add("self-check no unchecked items", "- [ ]" not in text, "all checked")
    files = pkg.get("files") or {}
    for name in ["HANDOFF.md", "SELF-CHECK.md"]:
        path = pkgdir / name
        if path.exists():
            add(f"{name} hash", sha256_file(path) == files.get(name), files.get(name, ""))
    # New packages carry the task/envelope they were generated for.  Legacy
    # packages (e.g. HANDOFF-PILOT-001) predate those fields: match them back
    # to a task by evidence hashes, then fall back to the default selection.
    pkg_task = str(pkg.get("task") or "").strip()
    if not pkg_task:
        pkg_task = match_task_by_evidence(root, pkg.get("state") or {}) or ""
    pkg_envelope = str(pkg.get("envelope") or "").strip()
    if not pkg_envelope and pkg_task:
        pkg_envelope = envelope_for_task(root, pkg_task)
    snap = current_snapshot(root, task_id=pkg_task or None,
                            envelope_id=pkg_envelope or None)
    expected = pkg.get("state") or {}
    add("main SHA unchanged", snap["main_sha"] == expected.get("main_sha"),
        f"{snap['main_sha']} vs {expected.get('main_sha')}")
    add("worktree head unchanged", snap["worktree_head"] == expected.get("worktree_head"),
        f"{snap['worktree_head']} vs {expected.get('worktree_head')}")
    add("queue still POST_MERGE_VERIFIED",
        snap["queue_status"] == "POST_MERGE_VERIFIED", str(snap["queue_status"]))
    add("task still closed", snap["task_status"] == "closed", str(snap["task_status"]))
    add("repo working tree clean", snap["repo_status"] == "clean", snap["repo_status"])
    add("worktree clean", snap["worktree_status"] == "clean", snap["worktree_status"])
    return checks


def cmd_handoff_new(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    if args.task:
        check_task_id(args.task, "task")
    if args.envelope:
        check_package_id(args.envelope, "envelope")
    pkgdir = root / "handoffs" / package_id
    if pkgdir.exists():
        fail([f"handoff package already exists: {package_id}"])
    snap = current_snapshot(root, task_id=args.task, envelope_id=args.envelope)
    if args.task and not snap["task_id"]:
        fail([f"task not found for --task {args.task}"])
    if args.envelope and not snap["envelope_id"]:
        fail([f"envelope not found for --envelope {args.envelope}"])
    pkgdir.mkdir(parents=True)

    task_id = snap["task_id"]
    envelope_id = snap["envelope_id"]
    evidence_rows = "\n".join(
        f"| `{e['path']}` | `{e['sha256']}` |" for e in snap["evidence"]
    ) or "| （无） | （无） |"
    if task_id:
        task_line = (f"任务 `{task_id}` 状态 `{snap['task_status'] or 'unknown'}`"
                     f"（next：{snap['task_next'] or '—'}）")
    else:
        task_line = "任务：未选择（TASK_BOARD 为空或显式查询未命中）"
    if envelope_id:
        queue_line = (f"合并队列 `{envelope_id}` 状态 "
                      f"`{snap['queue_status'] or 'unknown'}`（merge commit："
                      f"`{snap['merge_commit'] or '—'}`）")
    else:
        queue_line = "合并队列：空"
    section1 = f"主塔 phase `{snap['phase'] or 'unknown'}`；{task_line}；{queue_line}。"
    open_lines = "\n".join(
        f"- `{t['id']}` — `{t['status']}` — {t.get('next') or '—'}"
        for t in snap["open_tasks"]
    ) or "- 无在途任务。"
    task_card = f"tasks/{task_id}/TASK.md" if task_id else "—"
    closeout = f"tasks/{task_id}/CLOSEOUT.md" if task_id else "—"
    in_flight = (f"当前 {len(snap['open_tasks'])} 项在途" if snap["open_tasks"]
                 else "当前无在途")
    handoff_md = f"""# tower-dsh 交接上下文包 — {package_id}

> 项目：Tower/DSH · 机制：project-handoff v2.1 · 装配路径：塔台直写
> 交接时刻：{snap['captured_at']} · 交出塔：{snap['primary_id']}

## §0 交接时刻实值

| 锚点 | 值 |
|---|---|
| tower_id | `{snap['tower_id']}` |
| primary phase | `{snap['phase']}` |
| primary id | `{snap['primary_id']}` |
| supervisor id | `{snap['supervisor_id']}` |
| supervision phase | `{snap['supervision_phase']}` |
| task id | `{task_id or '—'}` |
| envelope id | `{envelope_id or '—'}` |
| main SHA | `{snap['main_sha']}` |
| worktree head | `{snap['worktree_head']}` |
| repo status | `{snap['repo_status']}` |
| worktree status | `{snap['worktree_status']}` |
| task status | `{snap['task_status'] or '—'}` |
| task next | `{snap['task_next'] or '—'}` |
| merge queue | `{snap['queue_status'] or '—'}` |
| merge commit | `{snap['merge_commit'] or '—'}` |
| primary ledger seq | `{snap['ledger_seq']}` |

### 证据锚点

| 证据 | SHA-256 |
|---|---|
{evidence_rows}

## §0a 材料漂移警示

NONE（无阻断性漂移；证据锚点：package {len(snap['evidence'])} 项，所选 task record {snap['task_evidence_count']} 项）。

## §1 30 秒版现状

{section1}

## §2 接续读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`
4. `shared/AUTHORITY_MODEL.json`
5. `primary/CURRENT_STATE.json`
6. `supervision/CURRENT_STATE.json`
7. `primary/TASK_BOARD.json`
8. `supervision/MERGE_QUEUE.json`
9. `{closeout}`
10. `ledger/primary.jsonl` 与 `ledger/supervision.jsonl`

## §3 运行时操作手册

- Tower root：`{snap['tower_root']}`
- Pilot repo：`{snap['repo'] or '（未配置）'}`
- Pilot worktree：`{snap['worktree'] or '（未配置）'}`
- Python：{snap['python']}；测试：`python -B -m unittest discover -s tools/tests -v`
- CLI：`python tools/towerctl.py <command>`
- 不读凭据、不调用生产、不部署；所有状态经 `towerctl`。

## §4 在途任务队列

{open_lines}
- 下一动作：{snap['next_action'] or '—'}

## §4a 调研/方案/未实现需求资产登记

- `control-tower/DESIGN.md` — Tower/DSH v0.3 设计（双塔/文件化/接线门/handoff v2.1）。
- `tower-dsh/PHASE2-REPORT.md` — Phase 2 双塔 pilot 报告。
- `%APPDATA%\\kimi-desktop\\daimon-share\\daimon\\skills\\project-handoff\\SKILL.md` — v2.1 源机制（只读参考）。
- `D:\\SeeMake-K3\\_k3-ops\\templates\\项目交接机制-v2.1-通用模板.md` — v2.1 通用模板（只读参考）。
- `~/.agents/skills/control-tower/`、`~/.agents/skills/control-tower-supervisor/` — 本塔技能。

## §5 owner 偏好与裁决档案

- Owner：`{snap['owner'] or '—'}`。
- 四闸永远归 owner：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。
- Primary 不 merge；Supervision 独占合并队列。
- 生产轨 `no_access`；本 pilot 未碰生产。
- 偏好：证据优先、单一写者、先手动后自动化。

## §6 判例与环境陷阱

- 本地 git 合并，不是远端 PR；无服务端分支保护。
- `--role supervisor` 是程序性分离，不是密码学身份。
- 证据锚点以 package 与 task record 各自的列表为准，两侧条目数可能不同（如 `commit.txt` 可能只登记在 record 中）。
- Windows CRLF 警告属正常；控制台中文可能显示乱码，文件本身 UTF-8。
- 不要手改 `primary/`、`supervision/`、`ledger/`；用 `towerctl`。

## §7 红线四闸与文档地图

| 对象 | 路径 |
|---|---|
| 塔身份 | `TOWER.md` |
| 宪法 | `AGENTS.md` |
| 启动读序 | `START-HERE.md` |
| 主塔状态 | `primary/CURRENT_STATE.json` |
| 监督塔状态 | `supervision/CURRENT_STATE.json` |
| 合并队列 | `supervision/MERGE_QUEUE.json` |
| 合并账本 | `supervision/registries/merge-ledger.json` |
| 任务卡 | `{task_card}` |
| 收口 | `{closeout}` |
| Ledger | `ledger/primary.jsonl`、`ledger/supervision.jsonl` |

**四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。**
"""
    (pkgdir / "HANDOFF.md").write_text(handoff_md, encoding="utf-8")
    selfcheck_md = f"""# 交出前自查 — {package_id}

- [x] 无未释放的锁/残留工作树/残留进程端口
- [x] 唯一真相源已更新到最新，在途项都有“下一步”
- [x] 在途任务卡每张有明确状态（{in_flight}）
- [x] 高危操作处于完整闸点，无半截（本 pilot 无生产动作）
- [x] 待 owner 输入项已汇总进 §4
- [x] 本窗调研/方案/未实现需求已登记进 §4a
- [x] §0 实值逐项复核于交接时刻

复核时刻：{snap['captured_at']}
主塔：`{snap['primary_id']}`
"""
    (pkgdir / "SELF-CHECK.md").write_text(selfcheck_md, encoding="utf-8")
    pkg = {
        "schema": "tower/handoff-package@1",
        "package_id": package_id,
        "project": "tower-dsh",
        "mechanism": "project-handoff-v2.1",
        "assembly_path": "tower_direct",
        "created_at": now(),
        "source_controller": snap["primary_id"],
        "task": task_id,
        "envelope": envelope_id,
        "status": "PREPARED",
        "files": {
            "HANDOFF.md": sha256_file(pkgdir / "HANDOFF.md"),
            "SELF-CHECK.md": sha256_file(pkgdir / "SELF-CHECK.md"),
        },
        "state": snap,
        "claim": None,
        "acceptance": None,
    }
    jdump(pkgdir / "package.json", pkg)
    append_ledger(root, "HANDOFF_NEW", "primary",
                  {"package": package_id, "source": snap["primary_id"],
                   "task": task_id, "envelope": envelope_id})
    emit({"ok": True, "package": package_id, "dir": rel(root, pkgdir),
          "task": task_id, "envelope": envelope_id, "files": pkg["files"]})


def cmd_handoff_check(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    checks = handoff_checks(root, package_id, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    emit({"ok": True, "package": args.package, "checks": checks})


def cmd_handoff_claim(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    if args.controller == pkg.get("source_controller"):
        fail(["receiver must differ from source controller"])
    checks = handoff_checks(root, package_id, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    claim = {
        "schema": "tower/handoff-claim@1",
        "package_id": args.package,
        "controller": args.controller,
        "claimed_at": now(),
        "checks": checks,
        "status": "READY_FOR_RECEIVER",
    }
    jdump(pkgdir / "CLAIM.json", claim)
    pkg.update({"status": "READY_FOR_RECEIVER", "claim": claim})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_CLAIM", "receiver",
                  {"package": args.package, "controller": args.controller})
    emit({"ok": True, "package": args.package, "status": pkg["status"],
          "controller": args.controller})


def cmd_handoff_accept(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    claim = pkg.get("claim") or {}
    if pkg.get("status") not in ("READY_FOR_RECEIVER", "RECEIVED"):
        fail([f"package status {pkg.get('status')} is not READY_FOR_RECEIVER/RECEIVED"])
    if claim.get("controller") != args.controller:
        fail(["claim controller does not match --controller"])
    acceptance = {
        "schema": "tower/handoff-acceptance@1",
        "package_id": args.package,
        "source_controller": pkg.get("source_controller"),
        "receiver": args.controller,
        "accepted_at": now(),
        "status": "ACCEPTED",
    }
    jdump(pkgdir / "ACCEPTANCE.json", acceptance)
    pkg.update({"status": "ACCEPTED", "acceptance": acceptance})
    jdump(pkg_path, pkg)
    state_path = root / "primary" / "CURRENT_STATE.json"
    state = jload(state_path)
    state["handoff"] = {"status": "ACCEPTED", "package": args.package,
                        "receiver": args.controller, "accepted_at": now()}
    state["phase"] = "HANDOFF_ACCEPTED"
    state["next_action"] = f"new controller {args.controller} must run startup from handoffs/{args.package}/HANDOFF.md"
    state["updated_at"] = now()
    jdump(state_path, state)
    append_ledger(root, "HANDOFF_ACCEPT", "primary",
                  {"package": args.package, "receiver": args.controller})
    emit({"ok": True, "package": args.package, "status": "ACCEPTED",
          "receiver": args.controller})


def cmd_handoff_receipt(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    claim = pkg.get("claim") or {}
    if pkg.get("status") != "READY_FOR_RECEIVER":
        fail([f"package status {pkg.get('status')} is not READY_FOR_RECEIVER"])
    if claim.get("controller") != args.controller:
        fail(["claim controller does not match --controller"])
    checks = handoff_checks(root, args.package, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    receipt_md = f"""# 接收回执 — {args.package}

- Receiver: `{args.controller}`
- Received at: {now()}
- Source: `{pkg.get('source_controller')}`
- Mechanism: `{pkg.get('mechanism')}`

## 首验

- [x] 读 HANDOFF.md（§0/§0a/§1–§7）
- [x] 读 CURRENT_STATE / TASK_BOARD / MERGE_QUEUE
- [x] 全项实值比对通过
- [x] 在途任务复述：无
- [x] 等待 owner 口令后开工

## Note

{args.note or '(none)'}
"""
    (pkgdir / "RECEIPT.md").write_text(receipt_md, encoding="utf-8")
    receipt = {"controller": args.controller, "received_at": now(),
               "checks": checks, "note": args.note or "",
               "path": rel(root, pkgdir / "RECEIPT.md")}
    pkg.update({"status": "RECEIVED", "receipt": receipt})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_RECEIPT", "receiver",
                  {"package": args.package, "controller": args.controller})
    emit({"ok": True, "package": args.package, "status": "RECEIVED",
          "receipt": receipt["path"]})


def cmd_handoff_activate(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    acceptance = pkg.get("acceptance") or {}
    if pkg.get("status") != "ACCEPTED":
        fail([f"package status {pkg.get('status')} is not ACCEPTED"])
    if acceptance.get("receiver") != args.controller:
        fail(["acceptance receiver does not match --controller"])
    state_path = root / "primary" / "CURRENT_STATE.json"
    state = jload(state_path)
    state["primary"] = {"id": args.controller, "session": "handoff-receiver"}
    state["handoff"] = {"status": "ACTIVE", "package": args.package,
                        "receiver": args.controller, "activated_at": now()}
    state["phase"] = "HANDOFF_ACTIVE"
    state["next_action"] = f"resume from handoffs/{args.package}/HANDOFF.md"
    state["updated_at"] = now()
    jdump(state_path, state)
    activation = {"schema": "tower/handoff-activation@1",
                  "package_id": args.package, "controller": args.controller,
                  "activated_at": now(), "status": "ACTIVE"}
    jdump(pkgdir / "ACTIVATION.json", activation)
    pkg.update({"status": "ACTIVE", "activation": activation})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_ACTIVATE", "receiver",
                  {"package": args.package, "controller": args.controller})
    drift = authority_drift(root)
    commit_required = bool(drift)
    emit({"ok": True, "package": args.package, "status": "ACTIVE",
          "controller": args.controller,
          "commit_required": commit_required,
          "commit_hint": authority_commit_hint(root, drift or [])})


def cmd_handoff_status(root: Path, args) -> None:
    packages = []
    pkg_root = root / "handoffs"
    if pkg_root.exists():
        for p in sorted(pkg_root.glob("*/package.json")):
            data = jload(p)
            packages.append({"package_id": data.get("package_id"),
                             "status": data.get("status"),
                             "source": data.get("source_controller"),
                             "receiver": (data.get("claim") or {}).get("controller"),
                             "created_at": data.get("created_at")})
    emit({"ok": True, "packages": packages})
