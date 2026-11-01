"""Campaign checks, roadmap/position and campaign docs."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from tower_common import TASK_BOARD_REL, TASK_ID_RE, emit, is_safe_id, jload
from tower_task import _optional_task_record, read_task_records
from tower_command import (
    COMMAND_CAMPAIGNS_REL, COMMAND_IN_FLIGHT, COMMAND_REVIEW_WINDOW_DAYS,
    COMMAND_SCHEMAS, COMMAND_STRATEGY_REL, COMMAND_TERMINAL, CommandDocError,
    budget_card_limit, budget_window_warnings, campaign_relpaths,
    command_card_exists, command_date, command_doc_meta, command_finding,
    scalar_items, spec_only_warnings, task_force_ids,
)


POSITION_SCHEMA = "tower/position@1"


POSITION_STATUSES = ("done", "active", "blocked", "planned", "skipped")


POSITION_GLYPHS = {"done": "✅", "active": "▶", "blocked": "⛔",
                   "planned": " ", "skipped": "·"}


POSITION_SOURCES = (TASK_BOARD_REL, "tasks")


def strategy_goals(meta: dict) -> list[dict]:
    """Well-formed ``goals`` entries (each one must carry an id)."""
    raw = meta.get("goals")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("id")]


def campaign_wip_limit(meta: dict) -> int | None:
    """``wip_limit`` as a non-negative int, or None when missing/invalid.

    The YAML subset keeps every scalar as text, so a bare ``1`` arrives as
    ``"1"``; only decimal digits are accepted here.
    """
    raw = meta.get("wip_limit")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else None


def command_warnings(root: Path, campaigns: list[dict], today: date) -> list[dict]:
    """Every warning family the report renders: W2 dates/budget plus W3."""
    warnings = review_warnings(root, campaigns, today)
    warnings += budget_window_warnings(campaigns, today)
    return warnings + spec_only_warnings(root, campaigns) + roadmap_gap_warnings(root, campaigns)


def duplicate_id_errors(ids: list[str], code: str, target: str,
                        label: str) -> list[dict]:
    """One finding per repeated id in ``ids``."""
    seen: set[str] = set()
    errors: list[dict] = []
    for value in ids:
        if value in seen:
            errors.append(command_finding(code, target, f"duplicate {label} id: {value}"))
        seen.add(value)
    return errors


def load_campaign_docs(root: Path) -> tuple[list[dict], list[dict]]:
    """Every campaign document, plus the ones that failed to parse."""
    docs: list[dict] = []
    errors: list[dict] = []
    for relpath in campaign_relpaths(root):
        try:
            meta = command_doc_meta(root, relpath, COMMAND_SCHEMAS["campaign"])
        except CommandDocError as exc:
            errors.append(command_finding("E1", relpath, str(exc)))
            continue
        docs.append({**meta, "_path": relpath})
    return docs, errors


def check_strategy_doc(root: Path) -> tuple[dict | None, list[dict]]:
    """E1: STRATEGY.md exists, parses, and declares at least one goal."""
    if not (root / COMMAND_STRATEGY_REL).is_file():
        return None, [command_finding("E1", COMMAND_STRATEGY_REL,
                                      "strategy document missing")]
    try:
        meta = command_doc_meta(root, COMMAND_STRATEGY_REL, COMMAND_SCHEMAS["strategy"])
    except CommandDocError as exc:
        return None, [command_finding("E1", COMMAND_STRATEGY_REL, str(exc))]
    if not strategy_goals(meta):
        return None, [command_finding("E1", COMMAND_STRATEGY_REL,
                                      "strategy declares no goals")]
    return meta, []


def goal_link_errors(campaigns: list[dict], goal_ids: list[str]) -> list[dict]:
    """E2: each campaign goal must be one of the strategy goal ids."""
    errors: list[dict] = []
    for doc in campaigns:
        if doc.get("goal") in goal_ids:
            continue
        target = str(doc.get("id") or doc["_path"])
        errors.append(command_finding("E2", target,
                                      f"goal {doc.get('goal')!r} is not a strategy goal"))
    return errors


def review_by_errors(strategy: dict, campaigns: list[dict], today: date) -> list[dict]:
    """E3: the strategy and every active campaign are inside ``review_by``."""
    errors: list[dict] = []
    deadlines = [(COMMAND_STRATEGY_REL, strategy.get("review_by"))]
    deadlines += [(str(doc.get("id") or doc["_path"]), doc.get("review_by"))
                  for doc in campaigns if doc.get("status") == "active"]
    for target, raw in deadlines:
        deadline = command_date(raw)
        if deadline is None:
            errors.append(command_finding(
                "E3", target, f"review_by missing or invalid: {raw!r}"))
        elif deadline < today:
            errors.append(command_finding(
                "E3", target, f"review_by {deadline.isoformat()} is past due"))
    return errors


def in_flight_ids(root: Path, task_ids: list[str]) -> list[str]:
    """Of ``task_ids``, those whose record status is in flight."""
    found: list[str] = []
    for task_id in task_ids:
        record = _optional_task_record(root, task_id)
        if record and record.get("status") in COMMAND_IN_FLIGHT:
            found.append(task_id)
    return found


def wip_errors(root: Path, campaigns: list[dict]) -> tuple[list[dict], dict]:
    """E4 plus the WIP summary rendered by ``campaign-check``."""
    errors: list[dict] = []
    summary: dict = {"in_flight": 0, "limit": 0, "campaigns": {}}
    for doc in campaigns:
        if doc.get("status") != "active":
            continue
        name = str(doc.get("id") or doc["_path"])
        ids = in_flight_ids(root, task_force_ids(doc))
        limit = campaign_wip_limit(doc)
        if limit is None:
            errors.append(command_finding("E4", name, "wip_limit missing or invalid"))
            limit = 0
        summary["in_flight"] += len(ids)
        summary["limit"] += limit
        summary["campaigns"][name] = len(ids)
        if len(ids) > limit:
            errors.append(command_finding(
                "E4", name, f"in-flight {len(ids)} exceeds wip_limit {limit}: "
                            f"{', '.join(ids) or '-'}"))
    return errors, summary


def task_force_errors(root: Path, campaigns: list[dict]) -> list[dict]:
    """E5: a campaign may only force cards that exist in the tower."""
    errors: list[dict] = []
    for doc in campaigns:
        for task_id in task_force_ids(doc):
            if command_card_exists(root, task_id):
                continue
            errors.append(command_finding(
                "E5", str(doc.get("id") or doc["_path"]),
                f"task_forces references an unknown card: {task_id}"))
    return errors


def board_rows(root: Path) -> tuple[list[dict], list[dict]]:
    """Board task objects, plus the E7 findings explaining a malformed shape.

    A missing board is still an empty board (``load_board``'s legacy default);
    a board that *exists* but is not ``{"tasks": [<object>, ...]}`` reports E7
    instead of raising ``AttributeError`` deeper in the report.
    """
    path = root / TASK_BOARD_REL
    if not path.is_file():
        return [], []
    try:
        board = jload(path)
    except (OSError, ValueError):
        return [], [command_finding("E7", TASK_BOARD_REL,
                                    "board is unreadable or not JSON")]
    if not isinstance(board, dict):
        return [], [command_finding("E7", TASK_BOARD_REL,
                                    f"board must be a JSON object, got "
                                    f"{type(board).__name__}")]
    tasks = board.get("tasks")
    if not isinstance(tasks, list):
        return [], [command_finding("E7", TASK_BOARD_REL,
                                    "tasks must be a JSON list")]
    bad = [index for index, item in enumerate(tasks) if not isinstance(item, dict)]
    errors = [command_finding("E7", TASK_BOARD_REL,
                              f"tasks[{index}] must be a JSON object")
              for index in bad]
    return [item for item in tasks if isinstance(item, dict) and item.get("id")], errors


def board_shape_errors(root: Path) -> list[dict]:
    """E7: the board is a JSON object whose ``tasks`` are JSON objects."""
    return board_rows(root)[1]


def legacy_card_ids(meta: dict) -> list[str]:
    """Card ids a campaign records as legacy history (never membership)."""
    return scalar_items(meta.get("legacy_cards"))


def campaign_coverage_ids(root: Path, campaigns: list[dict]) -> set[str]:
    """W1 coverage: task_forces ∪ legacy_cards ∪ current ∪ dispatch.campaign.

    ``legacy_cards`` bookkeeps cards closed before the campaign existed; it is
    not retroactive membership.  ``current`` is the card the campaign is doing
    right now, so it belongs to the campaign by definition -- once it merges it
    reaches the board without a ``dispatch.campaign`` of its own, and it must
    not turn into an orphan.  A dispatch covers a card only when it names a
    campaign the tower still has, so a stale id cannot silence the warning.
    """
    covered = {task_id for doc in campaigns
               for task_id in task_force_ids(doc) + legacy_card_ids(doc)}
    currents = {str(doc.get("current") or "").strip() for doc in campaigns}
    covered |= {task_id for task_id in currents if task_id}
    known = {str(doc.get("id")) for doc in campaigns if doc.get("id")}
    for entry in board_rows(root)[0]:
        record = _optional_task_record(root, str(entry["id"])) or {}
        dispatch = record.get("dispatch")
        chosen = dispatch.get("campaign") if isinstance(dispatch, dict) else None
        if isinstance(chosen, str) and chosen in known:
            covered.add(str(entry["id"]))
    return covered


def board_orphan_warnings(root: Path, campaigns: list[dict]) -> list[dict]:
    """W1: board cards no campaign covers (task_forces ∪ legacy ∪ dispatch)."""
    referenced = campaign_coverage_ids(root, campaigns)
    return [command_finding("W1", str(entry["id"]),
                            f"board card not referenced by any campaign: {entry['id']}")
            for entry in board_rows(root)[0] if entry["id"] not in referenced]


def open_task_force_ids(root: Path, meta: dict) -> list[str]:
    """The campaign's forced cards that are not closed yet (open WIP)."""
    open_ids: list[str] = []
    for task_id in task_force_ids(meta):
        record = _optional_task_record(root, task_id)
        if record is None or record.get("status") != "closed":
            open_ids.append(task_id)
    return open_ids


def review_warnings(root: Path, campaigns: list[dict], today: date) -> list[dict]:
    """W2: ``review_by`` within a week, or more open forced cards than budget."""
    warnings: list[dict] = []
    horizon = today + timedelta(days=COMMAND_REVIEW_WINDOW_DAYS)
    for doc in campaigns:
        if doc.get("status") in COMMAND_TERMINAL:
            continue
        target = str(doc.get("id") or doc["_path"])
        deadline = command_date(doc.get("review_by"))
        if deadline is not None and today <= deadline <= horizon:
            warnings.append(command_finding(
                "W2", target, f"review_by {deadline.isoformat()} is within 7 days"))
        budget = budget_card_limit(doc.get("budget"))
        if budget is not None and len(open_task_force_ids(root, doc)) > budget:
            warnings.append(command_finding(
                "W2", target, f"open task_forces exceed the budget of {budget} cards"))
    return warnings


def campaign_check_report(root: Path, strict: bool) -> dict:
    """The ``campaign-check`` payload; reads only, never writes a file."""
    today = date.today()
    strategy, errors = check_strategy_doc(root)
    campaigns, campaign_errors = load_campaign_docs(root)
    errors += campaign_errors
    goal_ids = [str(goal["id"]) for goal in strategy_goals(strategy or {})]
    if strategy is not None:
        errors += duplicate_id_errors(goal_ids, "E6", COMMAND_STRATEGY_REL, "goal")
        errors += goal_link_errors(campaigns, goal_ids)
        errors += review_by_errors(strategy, campaigns, today)
    errors += duplicate_id_errors(
        [str(doc.get("id") or doc["_path"]) for doc in campaigns],
        "E6", COMMAND_CAMPAIGNS_REL, "campaign")
    wip, wip_summary = wip_errors(root, campaigns)
    errors += wip + campaign_roadmap_errors(campaigns)
    errors += task_force_errors(root, campaigns) + board_shape_errors(root)
    warnings = board_orphan_warnings(root, campaigns) if strategy else []
    warnings += command_warnings(root, campaigns, today)
    if strict:
        errors += warnings
        warnings = []
    return {"ok": not errors, "strict": strict,
            "strategy": (strategy or {}).get("id"), "goals": goal_ids,
            "campaigns": len(campaigns),
            "campaign_ids": [str(doc.get("id") or doc["_path"]) for doc in campaigns],
            "wip": wip_summary, "errors": errors, "warnings": warnings}


def cmd_campaign_check(root: Path, args) -> None:
    """Judge strategy/campaign links, WIP and review dates (read-only)."""
    payload = campaign_check_report(root, args.strict)
    emit(payload, 0 if payload["ok"] else 2)


def load_strategy_quiet(root: Path) -> dict | None:
    """The strategy mapping, or None when it is missing or unparseable."""
    try:
        return command_doc_meta(root, COMMAND_STRATEGY_REL, COMMAND_SCHEMAS["strategy"])
    except CommandDocError:
        return None


def active_campaign(campaigns: list[dict]) -> dict | None:
    """The first campaign whose status is ``active``."""
    for doc in campaigns:
        if doc.get("status") == "active":
            return doc
    return None


def campaign_progress(root: Path, doc: dict) -> tuple[int, int]:
    """``(closed, total)`` over the campaign's ``task_forces``."""
    ids = task_force_ids(doc)
    closed = 0
    for task_id in ids:
        record = _optional_task_record(root, task_id)
        if record and record.get("status") == "closed":
            closed += 1
    return closed, len(ids)


def record_is_blocked(record: dict) -> bool:
    """Rework, or a failed last review, counts as blocked."""
    if record.get("status") == "rework":
        return True
    return (record.get("review") or {}).get("verdict") == "FAIL"


class PositionUnavailable(RuntimeError):
    """No active campaign, or its roadmap/current cannot define a position."""


def roadmap_ids(meta: dict) -> list[str]:
    """The campaign's roadmap ids exactly as written (no validation)."""
    return scalar_items(meta.get("roadmap"))


def roadmap_problem(meta: dict, *, required: bool) -> str | None:
    """Why a campaign roadmap/current pair is unusable, or None when it is fine.

    ``required`` also flags a missing ``roadmap`` key (``where`` demands one);
    ``campaign-check`` stays lenient so pre-047 campaigns remain valid.
    """
    if "roadmap" not in meta:
        return "roadmap missing" if required else None
    ids = roadmap_ids(meta)
    if not ids:
        return "roadmap is empty"
    seen: set[str] = set()
    for task_id in ids:
        if not is_safe_id(task_id, TASK_ID_RE):
            return f"roadmap id is not a task id: {task_id!r}"
        if task_id in seen:
            return f"duplicate roadmap id: {task_id}"
        seen.add(task_id)
    current = str(meta.get("current") or "").strip()
    if current not in ids:
        return f"current {current!r} is not in roadmap"
    return None


def campaign_roadmap_errors(campaigns: list[dict]) -> list[dict]:
    """E8: a declared roadmap must be a unique task-id list containing current."""
    return [command_finding("E8", str(doc.get("id") or doc["_path"]), problem)
            for doc in campaigns
            if (problem := roadmap_problem(doc, required=False))]


def roadmap_gap_warnings(root: Path, campaigns: list[dict]) -> list[dict]:
    """W4: a roadmap node with neither ``tasks/<id>/`` nor a pilot spec yet."""
    warnings: list[dict] = []
    for doc in campaigns:
        target = str(doc.get("id") or doc["_path"])
        for task_id in roadmap_ids(doc):
            if not command_card_exists(root, task_id):
                warnings.append(command_finding(
                    "W4", target, f"roadmap node not created yet: {task_id}"))
    return warnings


def position_status(record: dict | None, task_id: str, current: str) -> str:
    """Map one roadmap node's record onto the fixed position enum."""
    if record is None:
        return "active" if task_id == current else "planned"
    if record.get("status") == "closed":
        return "done"
    if record_is_blocked(record):
        return "blocked"
    if record.get("status") in COMMAND_IN_FLIGHT:
        return "active"
    return "planned"


def position_nodes(root: Path, roadmap: list[str], current: str) -> list[dict]:
    """``[{"id", "status"}]`` in roadmap order."""
    nodes: list[dict] = []
    for task_id in roadmap:
        record = _optional_task_record(root, task_id)
        nodes.append({"id": task_id,
                      "status": position_status(record, task_id, current)})
    return nodes


def position_index(nodes: list[dict]) -> int:
    """The completed-step index: how many roadmap nodes are already ``done``.

    The campaign's ``位置 x/y`` is the same progress figure as ``brief``'s
    ``closed/total`` (2/6 once PILOT-045/046 close), and reaches ``total`` once
    every roadmap node is done.
    """
    return sum(1 for node in nodes if node["status"] == "done")


def position_next(nodes: list[dict], current: str) -> str | None:
    """``current`` while unfinished, else the first planned node; None if done."""
    node = next((item for item in nodes if item["id"] == current), None)
    if node is not None and node["status"] != "done":
        return current
    return next((item["id"] for item in nodes if item["status"] == "planned"), None)


def position_context(root: Path) -> tuple[dict, dict]:
    """Build ``(payload, campaign)``; raise PositionUnavailable when undefined."""
    campaigns, _ = load_campaign_docs(root)
    doc = active_campaign(campaigns)
    if doc is None:
        raise PositionUnavailable("E9 no active campaign")
    problem = roadmap_problem(doc, required=True)
    if problem:
        raise PositionUnavailable(f"E8 position invalid: {problem}")
    roadmap = roadmap_ids(doc)
    current = str(doc.get("current") or "").strip()
    nodes = position_nodes(root, roadmap, current)
    records = read_task_records(root)
    limit = campaign_wip_limit(doc)
    position = {
        "schema": POSITION_SCHEMA,
        "campaign": str(doc.get("id") or doc["_path"]),
        "goal": doc.get("goal"),
        "index": position_index(nodes),
        "total": len(roadmap),
        "current": current,
        "next": position_next(nodes, current),
        "nodes": nodes,
        "wip": {"in_flight": sum(1 for record in records
                                 if record.get("status") in COMMAND_IN_FLIGHT),
                "limit": limit if limit is not None else 0},
        "blocked": [node["id"] for node in nodes if node["status"] == "blocked"],
        "stop_conditions": scalar_items(doc.get("stop_conditions")),
        "sources": [doc["_path"], *POSITION_SOURCES],
    }
    return position, doc


def position_payload(root: Path) -> dict:
    """The ``tower/position@1`` payload alone."""
    return position_context(root)[0]


def position_for(root: Path) -> dict | None:
    """The position payload when this tower can compute one, else None."""
    try:
        return position_payload(root)
    except PositionUnavailable:
        return None


def with_position(root: Path, payload: dict) -> dict:
    """Add the position object to a command payload when the tower has one."""
    position = position_for(root)
    if position is None:
        return payload
    return {**payload, "position": position}


def campaign_map_progress(root: Path, doc: dict) -> tuple[int, int]:
    """``(closed, total)`` over the roadmap when valid, else over task_forces."""
    ids = roadmap_ids(doc)
    if not ids or roadmap_problem(doc, required=True):
        return campaign_progress(root, doc)
    nodes = position_nodes(root, ids, str(doc.get("current") or "").strip())
    return sum(1 for node in nodes if node["status"] == "done"), len(nodes)


def campaign_heading(root: Path, doc: dict) -> str:
    """``<campaign id> <H1 name>`` for the human view's first line."""
    name = str(doc.get("id") or doc["_path"])
    try:
        text = (root / doc["_path"]).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return name
    for line in text.splitlines():
        if line.startswith("# "):
            heading = line[2:].strip()
            parts = heading.split("—", 1)
            return f"{name} {parts[1].strip() if len(parts) > 1 else heading}"
    return name


def position_fig_value(root: Path) -> str:
    """The snapshot ``x/y`` position value, or ``-`` when none is defined."""
    try:
        position = position_payload(root)
    except PositionUnavailable:
        return "-"
    return f"{position['index']}/{position['total']}"


def position_review_lines(root: Path, task_id: str) -> list[str]:
    """The ``## Position`` block appended to REVIEW.md when one exists."""
    position = position_for(root)
    if position is None:
        return []
    return ["", "## Position", "",
            f"- 位置：{position['index']}/{position['total']}",
            f"- 下一站：{position['next'] or '—'}",
            f"- 本次复查：{task_id}"]
