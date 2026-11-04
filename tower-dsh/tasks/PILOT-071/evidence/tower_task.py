"""Task cards, ids, specs and the board (owning records)."""
from __future__ import annotations

import re
import spec_lint
from datetime import datetime
from pathlib import Path
from tower_common import (
    COMMAND_ARCHIVE_SUFFIX, TASK_ID_RE, _read_json_object, check_task_id, emit,
    ensure_within, fail, is_safe_id, jdump, jload, now, rel,
    resolve_input_within, sha256_file,
)
from tower_ledger import (
    activate_task_id, append_ledger, task_dir, task_id_entry, task_ids_lock,
    task_ids_save, task_id_view,
)
from tower_ledger_replay import ledger_events_in_seq_order


def task_record_path(root: Path, tid: str) -> Path:
    return task_dir(root, tid) / "record.json"


def load_record(root: Path, tid: str) -> dict:
    path = task_record_path(root, tid)
    if not path.exists():
        fail([f"task record missing: {rel(root, path)}"])
    return jload(path)


def save_record(root: Path, record: dict) -> None:
    record["updated_at"] = now()
    jdump(task_record_path(root, record["id"]), record)


def load_board(root: Path) -> dict:
    path = root / "primary" / "TASK_BOARD.json"
    if path.exists():
        return jload(path)
    return {"schema": "tower/task-board@1", "tower_id": "tower-dsh", "tasks": []}


def save_board(root: Path, board: dict) -> None:
    board["updated_at"] = now()
    jdump(root / "primary" / "TASK_BOARD.json", board)


def update_board(root: Path, record: dict) -> None:
    board = load_board(root)
    entry = {
        "id": record["id"],
        "title": record["title"],
        "status": record["status"],
        "authority": record.get("authority"),
        "executor": record.get("executor"),
        "reviewer": (record.get("review") or {}).get("reviewer"),
        "next": record.get("next", ""),
        "updated_at": record.get("updated_at", now()),
    }
    tasks = [t for t in board.get("tasks", []) if t.get("id") != record["id"]]
    tasks.append(entry)
    board["tasks"] = tasks
    save_board(root, board)


def resolve_input(root: Path, value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    cand = root / p
    return cand if cand.exists() else p.resolve()


def spec_gate_errors(root: Path, rec: dict) -> list[str]:
    """Re-check the spec gate against the live spec file.

    The recorded ``spec_sha256`` is compared with the file on disk every time
    the gate is consulted, so editing a spec after ``task-new`` invalidates a
    previously recorded ``spec_gate: PASS``.  A task card without ``spec_path``
    is no longer exempt: without an unchanged spec file the gate cannot pass.
    """
    errors: list[str] = []
    spec_path = rec.get("spec_path")
    if not spec_path:
        errors.append("task card has no spec_path (legacy task card); spec gate cannot pass")
        return errors
    full = root / spec_path
    if not full.exists():
        errors.append(f"spec file missing: {spec_path}")
        return errors
    recorded = rec.get("spec_sha256")
    actual = sha256_file(full)
    if recorded != actual:
        errors.append(
            "spec file changed since task-new "
            f"(spec_sha256 mismatch: recorded {recorded}, current {actual}); "
            "spec_gate is invalid, rebuild the task card"
        )
        return errors
    if rec.get("spec_gate") != "PASS":
        errors.append("spec gate not passed; run check --phase spec first")
    return errors


DEPENDS_ON_CLOSED = "closed"


def dependency_status_text(value) -> str | None:
    """A non-empty status string, or ``None`` for anything else."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def dependency_target_status(root: Path, dep: str) -> str | None:
    """Status of one dependency target, or ``None`` when no card records it.

    The live ``record.json`` wins over a ``TASK_BOARD.json`` row (the board is a
    working copy, the record is the card).  A bare ``tasks/<id>/`` directory is
    still a target at ``task-new`` time, but it carries no trustworthy status
    yet, so it reports ``unknown`` rather than a fabricated ``ready``.
    """
    if not is_safe_id(dep, TASK_ID_RE):
        return None
    record = _optional_task_record(root, dep)
    if record and record.get("id") == dep:
        status = dependency_status_text(record.get("status"))
        if status:
            return status
    for entry in load_board(root).get("tasks") or []:
        if isinstance(entry, dict) and entry.get("id") == dep:
            return dependency_status_text(entry.get("status")) or "unknown"
    return "unknown" if (root / "tasks" / dep).is_dir() else None


def depends_on_structure_errors(root: Path, spec: dict, tid: str) -> list[str]:
    """Structural gate for ``spec.depends_on`` at ``task-new``; never writes.

    The list itself may be empty (most legacy cards are), but every element
    must be a non-empty string naming a card that already exists in the board
    or under ``tasks/<id>/``.  Closure is *not* required here: a card may be
    created before its dependency closes.
    """
    raw = spec.get("depends_on", [])
    if not isinstance(raw, list):
        return ["depends_on.invalid: depends_on must be a list of task ids"]
    errors: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            errors.append("depends_on.invalid: depends_on items must be non-empty strings")
            continue
        dep = value.strip()
        if dep in seen:
            errors.append(f"depends_on.duplicate: {dep} listed more than once")
            continue
        seen.add(dep)
        if dep == tid:
            errors.append(f"depends_on.self: {dep} cannot depend on itself")
        elif dependency_target_status(root, dep) is None:
            errors.append(f"depends_on.missing: no task card for {dep}")
    return errors


SPEC_SCHEMA = "tower/spec@1"


SPEC2_SCHEMA = "tower/spec@2"


SPEC_SCHEMAS = (SPEC_SCHEMA, SPEC2_SCHEMA)


def validate_spec(spec: dict) -> list[str]:
    """Content checks for a task spec, beyond field presence.

    Returns a list of human-readable errors; empty means the spec is sound.
    """
    errors = []
    if spec.get("schema") not in SPEC_SCHEMAS:
        errors.append(f"spec.schema must be one of {' | '.join(SPEC_SCHEMAS)}")
    acceptance = spec.get("acceptance") or []
    if not all(isinstance(x, str) and x.strip() for x in acceptance):
        errors.append("spec.acceptance items must be non-empty strings")
    forbidden = " ".join(str(x).lower() for x in (spec.get("forbidden") or []))
    if "merge" not in forbidden:
        errors.append("spec.forbidden must include 'merge'")
    if "production" not in forbidden:
        errors.append("spec.forbidden must include 'production access'")
    allowed = spec.get("allowed_paths") or []
    if not all(isinstance(x, str) and x.strip() for x in allowed):
        errors.append("spec.allowed_paths items must be non-empty strings")
    return errors


def task_new_errors(root: Path, spec: dict, tid: str) -> list[str]:
    """Every task-new refusal reason, objective gate included; never writes."""
    errors = []
    if not TASK_ID_RE.match(tid):
        errors.append(f"invalid id: {tid!r} (task id must match {TASK_ID_RE.pattern})")
    for field in ["title", "authority", "scope", "allowed_paths", "forbidden", "acceptance"]:
        if not spec.get(field):
            errors.append(f"spec.{field} required")
    if not errors:
        errors += validate_spec(spec)
    errors += spec_lint.objective_errors(spec)
    errors += depends_on_structure_errors(root, spec, tid)
    worktree = spec.get("worktree")
    if not worktree:
        errors.append("spec.worktree required")
    else:
        worktree_path = ensure_within(root, root / worktree, label="worktree")
        if not worktree_path.exists():
            errors.append(f"worktree missing: {worktree}")
    return errors


def write_task_card(root: Path, tid: str, spec: dict, spec_path: Path) -> dict:
    """Write record.json + TASK.md, update the board and append TASK_NEW."""
    worktree = spec["worktree"]
    tdir = task_dir(root, tid)
    (tdir / "evidence").mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "tower/task@1", "id": tid, "title": spec["title"],
        "status": "ready", "authority": spec["authority"],
        "scope": spec["scope"], "allowed_paths": spec["allowed_paths"],
        "forbidden": spec["forbidden"], "acceptance": spec["acceptance"],
        "depends_on": spec.get("depends_on", []), "worktree": worktree,
        "spec_path": rel(root, spec_path), "spec_sha256": sha256_file(spec_path),
        "spec_gate": None,
        "executor": None, "dispatch": None, "evidence": [], "review": None,
        "decision": None, "closeout": None,
        "created_at": now(), "updated_at": now(),
        "next": "spec 审批：owner 或独立 reviewer 运行 spec-approve，然后 check --phase spec",
    }
    jdump(tdir / "record.json", record)
    lines = [f"# {tid} — {record['title']}", "", f"- Status: `ready`",
             f"- Authority: `{record['authority']}`", f"- Worktree: `{worktree}`", "",
             "## Scope", ""]
    lines += [f"- {x}" for x in record["scope"]]
    lines += ["", "## Allowed paths", ""]
    lines += [f"- `{x}`" for x in record["allowed_paths"]]
    lines += ["", "## Forbidden", ""]
    lines += [f"- {x}" for x in record["forbidden"]]
    lines += ["", "## Acceptance", ""]
    lines += [f"- {x}" for x in record["acceptance"]]
    (tdir / "TASK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_board(root, record)
    append_ledger(root, "TASK_NEW", "primary", {"task": tid, "title": record["title"]})
    return record


def cmd_task_new(root: Path, args) -> None:
    """Create a card (PILOT-059 adds its acceptance list; see ``task_new_card``)."""
    task_new_card(root, args)


def ledger_task_event_payloads(root: Path, event_type: str,
                               task: str) -> list[dict]:
    """Every payload of ``event_type`` for ``task`` in the primary ledger."""
    return [event["payload"]
            for event in ledger_events_in_seq_order(root, "primary")
            if event.get("type") == event_type
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("task") == task]


def ledger_has_task_event(root: Path, event_type: str, task: str) -> bool:
    return bool(ledger_task_event_payloads(root, event_type, task))


SUPERSEDE_SOURCE_STATUSES = ("delivered", "rework")


def last_supersede_event(root: Path, task: str) -> dict | None:
    """The latest ``TASK_SUPERSEDE`` payload for ``task``, or ``None``."""
    payloads = ledger_task_event_payloads(root, "TASK_SUPERSEDE", task)
    return payloads[-1] if payloads else None


def task_id_status(root: Path, task: str) -> str | None:
    """The id registry's status for ``task``, or ``None`` when absent."""
    entry = task_id_view(root).get(task)
    return entry.get("status") if isinstance(entry, dict) else None


def board_task_status(root: Path, task: str) -> str | None:
    """The board row's status for ``task``, or ``None`` when absent."""
    return next((entry.get("status")
                 for entry in load_board(root).get("tasks") or []
                 if isinstance(entry, dict) and entry.get("id") == task), None)


def supersede_request_errors(root: Path, rec: dict, target: str, by: str,
                             reason: str) -> list[str]:
    """Owner/reason/target half of the refusal set; read-only."""
    tid = str(rec.get("id") or "")
    _, state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    owner = state.get("owner") if isinstance(state, dict) else None
    owner = owner.get("name") if isinstance(owner, dict) else None
    errors: list[str] = []
    if not owner:
        errors.append("primary/CURRENT_STATE.json has no owner.name")
    elif by != owner:
        errors.append(f"only the registered owner may supersede a task: "
                      f"--by {by!r} != owner {owner!r}")
    if not reason:
        errors.append("--reason must be a non-empty string")
    if target == tid:
        errors.append(f"task {tid} cannot supersede itself")
    if _optional_task_record(root, target) is None:
        errors.append(f"target card missing: {target}")
    return errors


def supersede_state_errors(root: Path, rec: dict, target: str,
                           event: dict | None) -> list[str]:
    """Source-state half; a partial tombstone is repairable, not refused."""
    tid = str(rec.get("id") or "")
    errors: list[str] = []
    event_target = event.get("superseded_by") if event else None
    if event_target and event_target != target:
        errors.append(f"ledger records {tid} superseded by {event_target!r}, "
                      f"not {target!r}")
    status = rec.get("status")
    if status == "superseded":
        recorded = rec.get("superseded_by") or event_target
        if recorded and recorded != target:
            errors.append(f"task {tid} is already superseded by {recorded}")
    elif status not in SUPERSEDE_SOURCE_STATUSES:
        errors.append(f"task status {status} cannot be superseded "
                      f"(allowed: {', '.join(SUPERSEDE_SOURCE_STATUSES)})")
    complete = (status == "superseded" and event is not None
                and rec.get("superseded_by") == target
                and board_task_status(root, tid) == "superseded"
                and task_id_status(root, tid) == "void")
    if complete:
        errors.append(f"task {tid} is already superseded")
    return errors


def void_task_id(root: Path, record: dict) -> None:
    """Void the card's id so ``task-new`` can never reuse it."""
    tid = str(record["id"])
    with task_ids_lock(root):
        ids = task_id_view(root)
        entry = ids.get(tid) or task_id_entry(root, tid, record, "void")
        entry["status"] = "void"
        entry["updated_at"] = now()
        ids[tid] = entry
        task_ids_save(root, ids, f"task {tid} is superseded but its id "
                                 "registry entry was not voided")


def cmd_task_supersede(root: Path, args) -> None:
    """Owner-only tombstone, idempotent across a half-written crash.

    The primary-ledger event is written first; record/board and the void id
    follow.  A crash between any two writes is repaired by the next retry
    (never a second event); only a fully applied tombstone is refused.
    """
    tid = check_task_id(args.task)
    target = check_task_id(args.by_task, "by-task")
    rec = load_record(root, tid)
    by = (args.by or "").strip()
    reason = (args.reason or "").strip()
    event = last_supersede_event(root, tid)
    errors = (supersede_request_errors(root, rec, target, by, reason)
              + supersede_state_errors(root, rec, target, event))
    if errors:
        fail(errors)
    repairing = event is not None or rec.get("status") == "superseded"
    at = str((event or {}).get("at") or rec.get("superseded_at") or now())
    if event is None:
        append_ledger(root, "TASK_SUPERSEDE", "owner",
                      {"task": tid, "by": by, "reason": reason,
                       "superseded_by": target, "at": at})
    rec["status"] = "superseded"
    rec["superseded_by"] = target
    rec["superseded_at"] = at
    rec["next"] = f"superseded by {target}; no merge, see ledger TASK_SUPERSEDE"
    save_record(root, rec)
    update_board(root, rec)
    if task_id_status(root, tid) != "void":
        void_task_id(root, rec)
    emit({"ok": True, "task": tid, "status": rec["status"],
          "superseded_by": target, "by": by, "repaired": repairing})


def cmd_spec_approve(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if not rec.get("spec_path"):
        fail([f"task {args.task} has no spec_path (legacy task card)"])
    if args.by == rec.get("executor"):
        fail(["spec approver must not be the executor"])
    append_ledger(root, "SPEC_APPROVED", args.by,
                  {"task": args.task, "by": args.by, "note": args.note or ""})
    emit({"ok": True, "task": args.task, "approved_by": args.by,
          "next": f"python tools/towerctl.py check --task {args.task} --phase spec"})


ACCEPTANCE_SCHEMA = "tower/acceptance@1"


ACCEPTANCE_JSON = "ACCEPTANCE.json"


ACCEPTANCE_MD = "ACCEPTANCE.md"


ACCEPTANCE_KINDS = ("auto", "manual")


ACCEPTANCE_STATUSES = ("pending", "passed", "failed")


ACCEPTANCE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


ACCEPTANCE_LEGACY_MAX = 58


ACCEPTANCE_LEGACY_BEFORE = "2026-11-01T00:00:00+08:00"


ACCEPTANCE_DEFAULT_ITEM = {"id": "A-01", "kind": "auto",
                           "status": "pending", "note": ""}


def acceptance_json_path(root: Path, tid: str) -> Path:
    """``tasks/<id>/ACCEPTANCE.json``: the machine-readable acceptance list."""
    return task_dir(root, tid) / ACCEPTANCE_JSON


def acceptance_md_path(root: Path, tid: str) -> Path:
    """``tasks/<id>/ACCEPTANCE.md``: the same list as a reader-facing table."""
    return task_dir(root, tid) / ACCEPTANCE_MD


def acceptance_row(item: dict) -> str:
    """One Markdown table row for an acceptance item (pipes escaped)."""
    note = str(item.get("note") or "").replace("|", "\\|").replace("\n", " ")
    return f"| {item['id']} | {item['kind']} | {item['status']} | {note} |"


def render_acceptance_md(tid: str, items: list[dict]) -> str:
    """Render ``ACCEPTANCE.md``; the table mirrors the JSON item order."""
    lines = [f"# {tid} - Acceptance", "",
             "| ID | kind | status | note |", "| --- | --- | --- | --- |"]
    lines += [acceptance_row(item) for item in items]
    return "\n".join(lines) + "\n"


def write_acceptance(root: Path, tid: str, items: list[dict]) -> None:
    """Write the JSON list and re-render the Markdown table from that same list."""
    jdump(acceptance_json_path(root, tid),
          {"schema": ACCEPTANCE_SCHEMA, "items": items})
    acceptance_md_path(root, tid).write_text(
        render_acceptance_md(tid, items), encoding="utf-8")


def write_default_acceptance(root: Path, tid: str) -> list[dict]:
    """Give a new card its default ``A-01 auto pending`` item (PILOT-059)."""
    items = [dict(ACCEPTANCE_DEFAULT_ITEM)]
    write_acceptance(root, tid, items)
    return items


def task_new_card(root: Path, args) -> None:
    """``task-new`` body plus the PILOT-059 default acceptance files."""
    spec_path = resolve_input_within(root, args.spec, "spec")
    if not spec_path.exists():
        fail([f"spec not found: {spec_path}"])
    try:
        spec = jload(spec_path)
    except (OSError, ValueError) as exc:
        fail([f"spec is not readable JSON: {exc}"])
    if not isinstance(spec, dict):
        fail(["spec must be a JSON object"])
    tid = str(spec.get("id", ""))
    errors = task_new_errors(root, spec, tid)
    if errors:
        fail(errors)
    tdir = task_dir(root, tid)
    if tdir.exists():
        fail([f"task already exists: {tid}"])
    view = task_id_view(root)
    if tid in view and view[tid].get("status") != "reserved":
        fail([f"task id already registered: {tid} "
              f"(status {view[tid].get('status')})"])
    record = write_task_card(root, tid, spec, spec_path)
    write_default_acceptance(root, tid)
    activate_task_id(root, record, view)
    emit({"ok": True, "task": tid,
          "record": rel(root, tdir / "record.json"),
          "task_md": rel(root, tdir / "TASK.md"),
          "acceptance_json": rel(root, acceptance_json_path(root, tid)),
          "acceptance_md": rel(root, acceptance_md_path(root, tid))})


def _latest_by(items: list[dict], field: str) -> dict:
    """Return the item whose ``field`` timestamp is newest (empty if none)."""
    if not items:
        return {}

    def sort_key(item: dict) -> float:
        raw = str(item.get(field) or "")
        try:
            return datetime.fromisoformat(raw).timestamp()
        except Exception:
            return float("-inf")

    return max(items, key=sort_key)


def select_task(board: dict, task_id: str | None = None) -> dict:
    """Pick the task a handoff is about.

    An explicit ``task_id`` wins.  Otherwise a single non-closed task is used;
    with several non-closed tasks the most recently updated one wins, and when
    every task is closed the most recently updated task overall is used.
    """
    tasks = [t for t in (board.get("tasks") or []) if isinstance(t, dict)]
    if task_id:
        return next((t for t in tasks if t.get("id") == task_id), {})
    open_tasks = [t for t in tasks if t.get("status") != "closed"]
    if len(open_tasks) == 1:
        return open_tasks[0]
    if open_tasks:
        return _latest_by(open_tasks, "updated_at")
    return _latest_by(tasks, "updated_at")


def _optional_task_record(root: Path, task_id: str) -> dict | None:
    """Best-effort record load that never emits / exits.

    Used by checks that must report a missing or malformed record as data
    (``envelope_checks``), not as a second JSON payload.
    """
    if not is_safe_id(task_id, TASK_ID_RE):
        return None
    path = task_record_path(root, task_id)
    if not path.exists():
        return None
    try:
        data = jload(path)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _load_optional_record(root: Path, task_id: str) -> dict:
    return _optional_task_record(root, task_id) or {}


def canonical_task_dir(name: str) -> bool:
    """True for a live task directory, false for an archive (``*-VOID``).

    Superseded cards are parked in ``tasks/<ID>-VOID/`` and keep their original
    ``id`` inside the record, so accepting such a directory would list one card
    twice (once closed, once whatever the archive last said).
    """
    return is_safe_id(name, TASK_ID_RE) and not name.endswith(COMMAND_ARCHIVE_SUFFIX)


def read_task_records(root: Path) -> list[dict]:
    """Every live ``tasks/<ID>/record.json`` whose id matches its directory.

    Archive directories and records whose internal ``id`` disagrees with the
    directory name are skipped, so one card can never appear twice.
    """
    records: list[dict] = []
    for path in sorted((root / "tasks").glob("*/record.json")):
        name = path.parent.name
        if not canonical_task_dir(name):
            continue
        record = _optional_task_record(root, name)
        if record and record.get("id") == name:
            records.append(record)
    return records
