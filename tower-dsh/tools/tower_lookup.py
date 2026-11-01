"""Position map rendering, where and read-only checks."""
from __future__ import annotations

from pathlib import Path
from tower_common import emit, emit_sorted, fail, jload, sha256_file
from tower_ledger import append_ledger, spec_registry_errors, task_dir
from tower_task import (
    _optional_task_record, ledger_has_task_event, load_record, resolve_input,
    save_record, spec_gate_errors, validate_spec,
)
from tower_command import command_card_exists
from tower_campaign import (
    POSITION_GLYPHS, PositionUnavailable, campaign_heading, position_context,
)
from tower_dispatch import scheduling_dependency_errors
from tower_delivery import check_evidence


def cmd_check(root: Path, args) -> None:
    rec = load_record(root, args.task)
    phase = args.phase
    errors = []
    if phase == "spec":
        spec_path = rec.get("spec_path")
        if not spec_path:
            errors.append("task card has no spec_path; legacy task cards are no "
                          "longer exempt from the spec gate, rebuild from a spec")
        else:
            full = root / spec_path
            if not full.exists():
                errors.append(f"spec file missing: {spec_path}")
            else:
                if sha256_file(full) != rec.get("spec_sha256"):
                    errors.append("spec file changed since task-new; rebuild the task card instead of editing in place")
                else:
                    errors += validate_spec(jload(full))
        errors += spec_registry_errors(root, rec)
        if not ledger_has_task_event(root, "SPEC_APPROVED", args.task):
            errors.append("SPEC_APPROVED ledger event missing; run spec-approve first")
        if not errors and rec.get("spec_gate") != "PASS":
            rec["spec_gate"] = "PASS"
            save_record(root, rec)
            append_ledger(root, "CHECK", "primary", {"task": args.task, "phase": "spec", "ok": True})
    elif phase == "ready":
        if rec.get("status") != "ready":
            errors.append(f"status is {rec.get('status')}, expected ready")
        if not (task_dir(root, args.task) / "TASK.md").exists():
            errors.append("TASK.md missing")
        if not (root / rec.get("worktree", "")).exists():
            errors.append("worktree missing")
        errors += spec_gate_errors(root, rec) + scheduling_dependency_errors(root, rec)
    elif phase == "dispatch":
        if rec.get("status") != "dispatched":
            errors.append(f"status is {rec.get('status')}, expected dispatched")
        if not rec.get("executor"):
            errors.append("executor missing")
        if not (rec.get("dispatch") or {}).get("at"):
            errors.append("dispatch record missing")
    elif phase == "deliver":
        if rec.get("status") not in ("delivered", "reviewed", "accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected delivered")
        errors += check_evidence(root, rec)
    elif phase == "review":
        if rec.get("status") not in ("reviewed", "accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected reviewed")
        review = rec.get("review") or {}
        if review.get("verdict") != "PASS":
            errors.append("review verdict is not PASS")
        reviewer = (review.get("reviewer") or "").strip()
        if not reviewer:
            errors.append("reviewer missing or empty in review record")
        elif reviewer == (rec.get("executor") or "").strip():
            errors.append("reviewer equals executor")
        errors += check_evidence(root, rec)
    elif phase == "accept":
        if rec.get("status") not in ("accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected accepted")
        if not rec.get("decision"):
            errors.append("decision missing")
        errors += check_evidence(root, rec)
    elif phase == "close":
        if rec.get("status") != "closed":
            errors.append(f"status is {rec.get('status')}, expected closed")
        if not (rec.get("closeout") or {}).get("path"):
            errors.append("closeout missing")
        errors += check_evidence(root, rec)
    if errors:
        emit({"ok": False, "task": args.task, "phase": phase, "errors": errors}, 2)
    emit({"ok": True, "task": args.task, "phase": phase,
          "status": rec.get("status"), "evidence": len(rec.get("evidence") or [])})


def cmd_hash(root: Path, args) -> None:
    path = resolve_input(root, args.path)
    if not path.exists():
        fail([f"path not found: {path}"])
    emit({"ok": True, "path": str(path), "sha256": sha256_file(path),
          "bytes": path.stat().st_size})


def position_spec_title(root: Path, task_id: str) -> str:
    """The pilot spec title for a roadmap node that has no task card yet."""
    try:
        title = jload(root / "pilot" / f"{task_id}.spec.json").get("title")
    except (OSError, ValueError, AttributeError):
        return "（未创建）"
    return str(title or "（未创建）")


def position_delivery(root: Path, task_id: str | None) -> str:
    """What the next card delivers: its title, else an explicit placeholder."""
    if not task_id:
        return "（路线图已全部 done）"
    record = _optional_task_record(root, task_id)
    if record and record.get("title"):
        return str(record["title"])
    try:
        text = (root / "tasks" / task_id / "TASK.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        text = ""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return position_spec_title(root, task_id)


def position_risk(root: Path, position: dict) -> str:
    """Blocked ids first, then roadmap nodes that have no task or spec yet."""
    if position["blocked"]:
        return "阻塞：" + "、".join(position["blocked"])
    gaps = [node["id"] for node in position["nodes"]
            if node["status"] == "planned" and not command_card_exists(root, node["id"])]
    if gaps:
        return "未回填：" + "、".join(gaps)
    return "无"


def position_human_lines(root: Path, position: dict, doc: dict) -> list[str]:
    """The short human view: title, bar, x/y, why/deliver/risk/advice."""
    bar = "".join(f"[{POSITION_GLYPHS[node['status']]}{node['id'][-3:]}]"
                  for node in position["nodes"])
    nxt = position["next"]
    advice = "先处理阻塞（blocked 非空）" if position["blocked"] else "继续（blocked 为空）"
    return [campaign_heading(root, doc), bar,
            f"位置 {position['index']}/{position['total']} · "
            f"下一站 {nxt[-3:] if nxt else '—'}",
            f"为什么：{doc.get('objective') or '（无 objective）'}",
            f"交付：{position_delivery(root, nxt)}",
            f"风险：{position_risk(root, position)}",
            f"建议：{advice}"]


def cmd_where(root: Path, args) -> None:
    """Print the position map: ``--json`` machine view or the human view."""
    try:
        position, doc = position_context(root)
    except PositionUnavailable as exc:
        fail([str(exc)])
    if args.json:
        emit_sorted(position)
    lines = position_human_lines(root, position, doc)
    if args.md:
        lines = ["## 位置", ""] + lines
    print("\n".join(lines))
