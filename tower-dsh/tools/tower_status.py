"""Status history, brief and derived index/rollup/archive."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from tower_common import check_task_id, emit, fail, jload, rel, sha256_file
from tower_task import _optional_task_record, read_task_records
from tower_command import (
    COMMAND_BRIEF_MAX_LINES, COMMAND_IN_FLIGHT, command_date, scalar_items,
    task_force_ids,
)
from tower_campaign import (
    active_campaign, campaign_map_progress, campaign_progress, campaign_wip_limit,
    load_campaign_docs, load_strategy_quiet, position_fig_value, record_is_blocked,
    strategy_goals,
)


STATUS_DIR_REL = "status"


STATUS_INDEX_REL = "status/index.json"


STATUS_WEEKLY_REL = "status/weekly"


STATUS_ARCHIVE_REL = "status/archive"


STATUS_INDEX_SCHEMA = "tower/status-index@1"


STATUS_EVENTS = ("dispatched", "delivered", "reviewed", "accepted", "closed", "note")


STATUS_ENTRY_RE = re.compile(r"^## (\d{2}:\d{2}) · (\S+) · ([a-z]+)$")


STATUS_CAMPAIGN_RE = re.compile(r"^(\S+)(?:\s+\(([^()]*)\))?$")


def brief_record_lines(rows: list[dict]) -> list[str]:
    """``- id · status · next`` for each card."""
    return [f"- {record.get('id')} · {record.get('status')} · "
            f"{record.get('next') or ''}".rstrip() for record in rows]


def brief_cap(lines: list[str], limit: int) -> list[str]:
    """At most ``limit`` lines, with an overflow marker instead of silence."""
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"- …另有 {len(lines) - limit} 条"]


def brief_strategy_lines(strategy: dict | None) -> list[str]:
    """One-line strategy answer: the first goal, else the title."""
    if strategy is None:
        return ["- STRATEGY.md 缺失或无法解析"]
    goals = strategy_goals(strategy)
    if goals:
        goal = goals[0]
        return [f"- {goal.get('id')}：{goal.get('text') or goal.get('metric') or '（无 text）'}"]
    return [f"- {strategy.get('title') or strategy.get('id') or '（无 goals）'}"]


def brief_campaign_lines(root: Path, doc: dict | None) -> list[str]:
    """Active campaign identity plus closed/total progress."""
    if doc is None:
        return ["- （无 active campaign）"]
    closed, total = campaign_map_progress(root, doc)
    return [f"- {doc.get('id')}：{doc.get('objective') or '（无 objective）'}",
            f"- 进度：{closed}/{total} closed"]


def brief_wip_lines(records: list[dict]) -> list[str]:
    """Every in-flight card with its status, capped so brief stays one page."""
    rows = [record for record in records if record.get("status") in COMMAND_IN_FLIGHT]
    return brief_cap(brief_record_lines(rows), 8) if rows else ["- （空）"]


def brief_blocked_lines(records: list[dict]) -> list[str]:
    """Blocked / rework cards, one line each, capped at six."""
    rows = [record for record in records if record_is_blocked(record)]
    return brief_cap(brief_record_lines(rows), 6) if rows else ["- （无）"]


def brief_next_lines(root: Path, doc: dict | None) -> list[str]:
    """The first three not-yet-closed cards of the active campaign."""
    if doc is None:
        return ["- （无 active campaign）"]
    pending: list[str] = []
    for task_id in task_force_ids(doc):
        record = _optional_task_record(root, task_id)
        if record is None or record.get("status") != "closed":
            pending.append(task_id)
    if not pending:
        return ["- （本战役 task_forces 已全部 closed）"]
    return [f"- {task_id}" for task_id in pending[:3]]


def read_current_state(root: Path) -> dict:
    """CURRENT_STATE.json or ``{}``; brief never fails on a missing state file."""
    try:
        return jload(root / "primary" / "CURRENT_STATE.json")
    except (OSError, ValueError):
        return {}


def brief_pending_lines(root: Path, doc: dict | None) -> list[str]:
    """Open decisions: campaign stop conditions and tower-level blockers."""
    lines: list[str] = []
    if doc is not None:
        lines += [f"- 停止条件：{item}" for item in scalar_items(doc.get("stop_conditions"))]
    state = read_current_state(root)
    lines += [f"- 塔级阻塞：{item}" for item in scalar_items(state.get("blockers"))]
    if state.get("next_action"):
        lines.append(f"- next_action：{state['next_action']}")
    return brief_cap(lines, 6) if lines else ["- （无）"]


def brief_constraint_lines(strategy: dict | None, doc: dict | None) -> list[str]:
    """Strategy non-goals plus the campaign's stop conditions, capped at eight."""
    lines = [f"- 非目标：{item}"
             for item in scalar_items((strategy or {}).get("non_goals"))]
    lines += [f"- 停止条件：{item}"
              for item in scalar_items((doc or {}).get("stop_conditions"))]
    return brief_cap(lines, 8) if lines else ["- （无）"]


def brief_markdown(root: Path) -> list[str]:
    """The one-page brief as lines, capped at ``COMMAND_BRIEF_MAX_LINES``."""
    strategy = load_strategy_quiet(root)
    campaigns, _ = load_campaign_docs(root)
    doc = active_campaign(campaigns)
    records = read_task_records(root)
    lines = [f"# BRIEF — {date.today().isoformat()}",
             "## 战略一句话", *brief_strategy_lines(strategy),
             "## 当前战役", *brief_campaign_lines(root, doc),
             "## 在飞（WIP）", *brief_wip_lines(records),
             "## 阻塞 / 返工", *brief_blocked_lines(records),
             "## 下一步 3 件", *brief_next_lines(root, doc),
             "## 待决", *brief_pending_lines(root, doc),
             "## 架构约束", *brief_constraint_lines(strategy, doc)]
    if len(lines) > COMMAND_BRIEF_MAX_LINES:
        return lines[:COMMAND_BRIEF_MAX_LINES - 1] + ["…（已截断）"]
    return lines


def cmd_brief(root: Path, args) -> None:
    """Print the one-page brief; stdout only, no state writes."""
    print("\n".join(brief_markdown(root)))


def status_dir_path(root: Path) -> Path:
    """The ``status/`` directory of the tower."""
    return root / STATUS_DIR_REL


def status_day_file(root: Path, day: date) -> Path:
    """The snapshot file for one calendar day."""
    return status_dir_path(root) / f"{day.isoformat()}.md"


def status_moment(raw: str | None) -> datetime:
    """Local now, or the ISO instant ``--at`` freezes time with in tests."""
    if raw is None:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(raw).strip())
    except ValueError:
        fail([f"--at must be an ISO date-time: {raw!r}"])


def status_figures(root: Path) -> dict:
    """Campaign progress, WIP ratio, blocked count and position for a snapshot."""
    return {**status_base_figures(root), "position": position_fig_value(root)}


def status_base_figures(root: Path) -> dict:
    """The PILOT-046 figures, without the PILOT-047 position value."""
    campaigns, _ = load_campaign_docs(root)
    doc = active_campaign(campaigns)
    records = read_task_records(root)
    in_flight = sum(1 for record in records
                    if record.get("status") in COMMAND_IN_FLIGHT)
    blocked = sum(1 for record in records if record_is_blocked(record))
    if doc is None:
        return {"campaign": "-", "progress": "", "wip": "-", "blocked": blocked}
    closed, total = campaign_progress(root, doc)
    limit = campaign_wip_limit(doc)
    return {"campaign": str(doc.get("id") or doc["_path"]),
            "progress": f"{closed}/{total}",
            "wip": f"{in_flight}/{limit if limit is not None else '-'}",
            "blocked": blocked}


def status_entry_lines(task_id: str, event: str, moment: datetime,
                       figures: dict, note: str | None,
                       tests: int | None) -> list[str]:
    """One fixed-shape snapshot entry, with the position line after ``blocked``."""
    lines = status_entry_base_lines(task_id, event, moment, figures, note, tests)
    return lines[:4] + [f"- position: {figures.get('position', '-')}"] + lines[4:]


def status_entry_base_lines(task_id: str, event: str, moment: datetime,
                            figures: dict, note: str | None,
                            tests: int | None) -> list[str]:
    """The PILOT-046 entry lines (heading, campaign, wip, blocked, tests, note)."""
    campaign = figures["campaign"]
    progress = f" ({figures['progress']})" if figures["progress"] else ""
    lines = [f"## {moment.strftime('%H:%M')} · {task_id} · {event}",
             f"- campaign: {campaign}{progress}",
             f"- wip: {figures['wip']}",
             f"- blocked: {figures['blocked']}"]
    if tests is not None:
        lines.append(f"- tests: {tests}")
    if note:
        lines.append(f"- note: {note}")
    return lines


def status_append(root: Path, day: date, entry: list[str]) -> Path:
    """Append one entry to ``status/<day>.md``, creating the header if needed."""
    path = status_day_file(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not existing:
        existing = f"# STATUS — {day.isoformat()}\n"
    separator = "\n" if existing.endswith("\n") else "\n\n"
    path.write_text(existing + separator + "\n".join(entry) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def status_blocks(text: str) -> list[list[str]]:
    """Split a snapshot file into ``## HH:MM · TASK · event`` blocks."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def status_entry(block: list[str]) -> dict | None:
    """Parse one entry block; None when its heading is not the fixed shape."""
    match = STATUS_ENTRY_RE.match(block[0])
    if match is None:
        return None
    entry = {"time": match.group(1), "task": match.group(2),
             "event": match.group(3)}
    for line in block[1:]:
        if line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            entry[key.strip()] = value.strip()
    return entry


def status_day_entries(path: Path) -> list[dict]:
    """Parsed entries of one snapshot file, in append order."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    return [entry for block in status_blocks(text)
            if (entry := status_entry(block)) is not None]


def status_snapshot_files(root: Path) -> list[Path]:
    """Every dated snapshot, ascending; weekly/, archive/ and README are out."""
    base = status_dir_path(root)
    if not base.is_dir():
        return []
    return sorted(path for path in base.glob("*.md")
                  if path.is_file() and command_date(path.stem) is not None)


def status_campaign_value(raw: str | None) -> tuple[str, str] | None:
    """``C-… (1/2)`` -> ``("C-…", "1/2")``; the ``-`` placeholder is None."""
    match = STATUS_CAMPAIGN_RE.match(str(raw or "").strip())
    if match is None or match.group(1) == "-":
        return None
    return match.group(1), (match.group(2) or "")


def status_index_payload(root: Path) -> dict:
    """The recomputable ``status/index.json`` payload (no timestamps)."""
    days: list[dict] = []
    cards: dict[str, dict] = {}
    campaigns: dict[str, dict] = {}
    for path in status_snapshot_files(root):
        entries = status_day_entries(path)
        days.append({"date": path.stem,
                     "file": path.relative_to(root).as_posix(),
                     "entries": len(entries),
                     "sha256": sha256_file(path)})
        for entry in entries:
            cards[entry["task"]] = {"last_event": entry["event"],
                                    "last_date": path.stem}
            pair = status_campaign_value(entry.get("campaign"))
            if pair is not None:
                campaigns[pair[0]] = {"progress": pair[1]}
    return {"schema": STATUS_INDEX_SCHEMA, "days": days,
            "cards": cards, "campaigns": campaigns}


def status_write_json(target: Path, payload: dict) -> None:
    """Write canonical JSON: sorted keys, UTF-8, one trailing newline."""
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    target.write_text(text + "\n", encoding="utf-8", newline="\n")


def week_bounds(week: str) -> tuple[date, date]:
    """``YYYY-Www`` -> (Monday, Sunday); invalid input exits 2."""
    match = re.match(r"^(\d{4})-W(\d{2})$", str(week or "").strip())
    if match is None:
        fail([f"--week must look like YYYY-Www: {week!r}"])
    try:
        start = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        fail([f"--week is not a valid ISO week: {week!r}"])
    return start, start + timedelta(days=6)


def status_week_entries(root: Path, start: date,
                        end: date) -> list[tuple[date, dict]]:
    """Every parsed entry in ``[start, end]``, day by day, in file order."""
    found: list[tuple[date, dict]] = []
    day = start
    while day <= end:
        for entry in status_day_entries(status_day_file(root, day)):
            found.append((day, entry))
        day += timedelta(days=1)
    return found


def status_blocked_count(entries: list[dict]) -> int:
    """Peak blocked-card count observed in the window (0 when never blocked)."""
    peak = 0
    for entry in entries:
        raw = str(entry.get("blocked") or "0").strip()
        peak = max(peak, int(raw)) if raw.isdigit() else peak
    return peak


def status_wip_span(entries: list[dict]) -> str:
    """``first → last`` WIP value of the week, or one value when unchanged."""
    values = [str(entry.get("wip") or "-") for entry in entries]
    if not values:
        return "-"
    return values[0] if values[0] == values[-1] else f"{values[0]} → {values[-1]}"


def status_campaign_rollup(entries: list[dict]) -> list[str]:
    """Latest progress per campaign id, sorted for byte stability."""
    latest: dict[str, str] = {}
    for entry in entries:
        pair = status_campaign_value(entry.get("campaign"))
        if pair is not None:
            latest[pair[0]] = pair[1]
    return [f"  - {campaign_id} {latest[campaign_id]}"
            for campaign_id in sorted(latest)]


def status_rollup_lines(root: Path, week: str) -> list[str]:
    """The weekly markdown; every value derives from the snapshots only."""
    start, end = week_bounds(week)
    events = status_week_entries(root, start, end)
    rows = [entry for _, entry in events]
    closed = sorted({entry["task"] for entry in rows if entry["event"] == "closed"})
    lines = [f"# WEEKLY — {week}", "",
             f"- 窗口：{start.isoformat()} → {end.isoformat()}",
             f"- 事件数：{len(events)}",
             f"- closed 卡：{'、'.join(closed) if closed else '-'}",
             f"- blocked 计数：{status_blocked_count(rows)}",
             f"- wip 变化：{status_wip_span(rows)}",
             "- campaign 进度：",
             *(status_campaign_rollup(rows) or ["  - -"]),
             "", "## 事件"]
    lines += [f"- {day.isoformat()} {entry['time']} · {entry['task']} · "
              f"{entry['event']}" for day, entry in events] or ["- （本周无快照）"]
    return lines


def status_quarter(day: date) -> str:
    """``YYYY-Qn`` for the calendar quarter of ``day``."""
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def status_archive_line(day: date, entries: list[dict]) -> str:
    """One archive line: date, event count and the day's last event."""
    line = f"- {day.isoformat()} · {len(entries)} 事件"
    if entries:
        last = entries[-1]
        line += f" · last: {last['task']} {last['event']}"
    return line


def status_archive(root: Path, before: date) -> dict:
    """Compress snapshots before ``before`` into one file per quarter.

    The originals stay in place (the status history is append-only); rerunning
    the command rewrites the same archive bytes.
    """
    grouped: dict[str, list[str]] = {}
    for path in status_snapshot_files(root):
        day = command_date(path.stem)
        if day is None or day >= before:
            continue
        grouped.setdefault(status_quarter(day), []).append(
            status_archive_line(day, status_day_entries(path)))
    written: list[str] = []
    for quarter in sorted(grouped):
        target = status_dir_path(root) / "archive" / f"{quarter}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = f"# ARCHIVE — {quarter}\n\n" + "\n".join(grouped[quarter]) + "\n"
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target.relative_to(root).as_posix())
    return {"ok": True, "before": before.isoformat(), "files": written,
            "days": sum(len(lines) for lines in grouped.values())}


def cmd_status_snapshot(root: Path, args) -> None:
    """Append one status snapshot; only ``status/`` is ever written."""
    task_id = check_task_id(args.task)
    moment = status_moment(args.at)
    if args.tests is not None and args.tests < 0:
        fail([f"--tests must be a non-negative int: {args.tests}"])
    entry = status_entry_lines(task_id, args.event, moment,
                               status_figures(root), args.note, args.tests)
    path = status_append(root, moment.date(), entry)
    emit({"ok": True, "command": "status-snapshot", "file": rel(root, path),
          "task": task_id, "event": args.event,
          "at": moment.strftime("%Y-%m-%dT%H:%M")})


def cmd_status_index(root: Path, args) -> None:
    """Rebuild ``status/index.json`` from the snapshots (deterministic)."""
    payload = status_index_payload(root)
    status_write_json(root / STATUS_INDEX_REL, payload)
    emit({"ok": True, "command": "status-index", "file": STATUS_INDEX_REL,
          "days": len(payload["days"]), "cards": len(payload["cards"]),
          "campaigns": len(payload["campaigns"])})


def cmd_status_rollup(root: Path, args) -> None:
    """Write ``status/weekly/<week>.md`` from that week's snapshots."""
    start, end = week_bounds(args.week)
    target = status_dir_path(root) / "weekly" / f"{args.week}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(status_rollup_lines(root, args.week)) + "\n",
                      encoding="utf-8", newline="\n")
    emit({"ok": True, "command": "status-rollup", "file": rel(root, target),
          "week": args.week, "window": [start.isoformat(), end.isoformat()]})


def cmd_status_archive(root: Path, args) -> None:
    """Compress snapshots older than ``--before``; originals are kept."""
    before = command_date(args.before)
    if before is None:
        fail([f"--before must be YYYY-MM-DD: {args.before!r}"])
    emit({"command": "status-archive", **status_archive(root, before)})
