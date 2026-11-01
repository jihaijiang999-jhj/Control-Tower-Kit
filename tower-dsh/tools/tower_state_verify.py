"""state-verify: replay both ledgers into drift findings."""
from __future__ import annotations

from pathlib import Path
from tower_common import (
    PACKAGE_ID_RE, PATH_ACCESS_ERRORS, SHA256_HEX_RE, TASK_ID_RE,
    _contained_tower_path, _norm_tower_rel, _read_json_object, emit, is_safe_id,
    sha256_file,
)
from tower_ledger_replay import (
    ledger_payloads_by_task, replay_envelope_statuses, replay_task_statuses,
    verify_ledger_file,
)
from tower_authority import _authority_state_drift
from tower_dispatch import _dispatch_base_sha_drift
from tower_delivery import (
    COMPLETION_ADDED, COMPLETION_ENTRY_FIELDS, _completion_field_differences,
    completion_events,
)


def _evidence_entry_drift(root: Path, task_id: str,
                          evidence: list) -> tuple[list[dict], int]:
    """Verify one record's evidence list; return (drift, entries hashed).

    Only entries whose path is contained, exists and is a regular file count
    as checked.  Malformed, escaping or missing entries are drift and are not
    counted.  A single readable file can yield both ``evidence_hash_mismatch``
    and ``evidence_bytes_mismatch``.
    """
    drift: list[dict] = []
    checked = 0
    for entry in evidence:
        if not isinstance(entry, dict):
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid entry"})
            continue
        raw = entry.get("path")
        if not isinstance(raw, str) or not raw:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        resolved, display, path_error = _contained_tower_path(root, raw)
        recorded_sha = entry.get("sha256")
        if path_error == "invalid":
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        if not isinstance(recorded_sha, str) or not SHA256_HEX_RE.fullmatch(recorded_sha):
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": display,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid sha256"})
            continue
        if path_error == "escape" or resolved is None:
            # The raw recorded path is kept verbatim; nothing outside the
            # tower root is ever hashed, stat'ed or read.
            drift.append({"kind": "evidence_path_escape", "target": task_id,
                          "path": raw,
                          "expected": "evidence path inside tower root",
                          "actual": raw})
            continue
        try:
            is_file = resolved.is_file()
        except PATH_ACCESS_ERRORS:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        if not is_file:
            try:
                exists = resolved.exists()
            except PATH_ACCESS_ERRORS:
                exists = False
            drift.append({"kind": "evidence_missing", "target": task_id,
                          "path": display,
                          "expected": "existing regular file",
                          "actual": "not a regular file" if exists
                                    else "missing"})
            continue
        try:
            actual_sha = sha256_file(resolved)
            size = resolved.stat().st_size
        except FileNotFoundError:
            drift.append({"kind": "evidence_missing", "target": task_id,
                          "path": display,
                          "expected": "existing regular file",
                          "actual": "missing"})
            continue
        except PATH_ACCESS_ERRORS:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": display,
                          "expected": "readable regular file",
                          "actual": "unreadable file"})
            continue
        checked += 1
        if recorded_sha.lower() != actual_sha:
            drift.append({"kind": "evidence_hash_mismatch", "target": task_id,
                          "path": display, "expected": recorded_sha,
                          "actual": actual_sha})
        recorded_bytes = entry.get("bytes")
        if (isinstance(recorded_bytes, int)
                and not isinstance(recorded_bytes, bool)
                and recorded_bytes != size):
            drift.append({"kind": "evidence_bytes_mismatch", "target": task_id,
                          "path": display, "expected": recorded_bytes,
                          "actual": size})
    return drift, checked


def _spec_drift(root: Path, task_id: str, record: dict) -> list[dict]:
    """Verify a record's frozen spec, but only when it claims both fields."""
    spec_path = record.get("spec_path")
    spec_sha = record.get("spec_sha256")
    if not isinstance(spec_path, str) or not spec_path:
        return []
    if not isinstance(spec_sha, str) or not spec_sha:
        return []
    resolved, display, path_error = _contained_tower_path(root, spec_path)
    if path_error == "invalid":
        return [{"kind": "spec_unreadable", "target": task_id, "path": None,
                 "expected": "well-formed spec path",
                 "actual": "invalid path"}]
    if path_error == "escape" or resolved is None:
        return [{"kind": "spec_path_escape", "target": task_id,
                 "path": spec_path,
                 "expected": "spec path inside tower root",
                 "actual": spec_path}]
    try:
        is_file = resolved.is_file()
    except PATH_ACCESS_ERRORS:
        return [{"kind": "spec_unreadable", "target": task_id, "path": None,
                 "expected": "well-formed spec path",
                 "actual": "invalid path"}]
    if not is_file:
        try:
            exists = resolved.exists()
        except PATH_ACCESS_ERRORS:
            exists = False
        return [{"kind": "spec_missing", "target": task_id, "path": display,
                 "expected": "existing regular file",
                 "actual": "not a regular file" if exists else "missing"}]
    try:
        actual_sha = sha256_file(resolved)
    except FileNotFoundError:
        return [{"kind": "spec_missing", "target": task_id, "path": display,
                 "expected": "existing regular file", "actual": "missing"}]
    except PATH_ACCESS_ERRORS:
        return [{"kind": "spec_unreadable", "target": task_id, "path": display,
                 "expected": "readable regular file",
                 "actual": "unreadable file"}]
    if spec_sha.lower() != actual_sha:
        return [{"kind": "spec_hash_mismatch", "target": task_id,
                 "path": display, "expected": spec_sha, "actual": actual_sha}]
    return []


def _completion_mismatch_drift(root: Path, task_id: str, record: dict,
                               events: list[dict]) -> list[dict]:
    """PILOT-043: record entries that disagree with their backing event.

    Only entries whose path has a backing event are compared here; a missing
    event stays ``completion_unbacked`` (PILOT-042's :func:`_completion_drift`),
    so one forged pair is not reported twice.
    """
    by_path: dict[str, dict] = {}
    for payload in events:
        path, error = _norm_tower_rel(root, payload.get("path"))
        if not error:
            by_path.setdefault(path, payload)
    rows: list[dict] = []
    completions = record.get("completions")
    for entry in completions if isinstance(completions, list) else []:
        if not isinstance(entry, dict):
            continue
        path, error = _norm_tower_rel(root, entry.get("path"))
        payload = by_path.get(path) if not error else None
        if payload is None:
            continue
        diffs = _completion_field_differences(entry, payload)
        if not diffs:
            continue
        fields = COMPLETION_ENTRY_FIELDS + ("at",)
        rows.append({
            "kind": "completion_mismatch", "target": task_id, "path": path,
            "expected": {field: payload.get(field) for field in fields},
            "actual": {field: entry.get(field) for field in fields},
            "differences": diffs,
        })
    return rows


def _completion_drift(root: Path, task_id: str, record: dict,
                      events: list[dict]) -> list[dict]:
    """PILOT-042: audit ``record.completions`` against COMPLETION_ADDED events.

    A completion is only trustworthy when both halves exist and name the same
    path:

    * record path without an event -> ``completion_unbacked`` (``target`` is
      the task, ``expected`` is the path);
    * event path without a record entry -> ``completion_missing``;
    * an entry or event whose ``path``/``by``/``reason``/``decision`` is not a
      non-empty string, or whose path is absolute / contains ``..`` / escapes
      the tower root -> ``completion_invalid``.

    A task without completions (legacy record) yields no row at all, so old
    towers verify exactly as before.  Read-only: only string normalisation and
    the already-parsed ledger payloads are used.
    """
    drift: list[dict] = []
    completions = record.get("completions")
    if completions is None:
        completions = []
    if not isinstance(completions, list):
        drift.append({"kind": "completion_invalid", "target": task_id,
                      "path": None, "expected": "list of completion entries",
                      "actual": "not a list"})
        completions = []

    event_paths: set[str] = set()
    for payload in events:
        raw_path = payload.get("path")
        normalized, error = _norm_tower_rel(root, raw_path)
        if error:
            drift.append({"kind": "completion_invalid", "target": task_id,
                          "path": raw_path if isinstance(raw_path, str) else None,
                          "expected": "well-formed COMPLETION_ADDED path",
                          "actual": error})
            continue
        event_paths.add(normalized)

    record_paths: set[str] = set()
    for entry in completions:
        if not isinstance(entry, dict):
            drift.append({"kind": "completion_invalid", "target": task_id,
                          "path": None,
                          "expected": "well-formed completion entry",
                          "actual": "invalid entry"})
            continue
        raw_path = entry.get("path")
        normalized, error = _norm_tower_rel(root, raw_path)
        display = normalized if normalized is not None else (
            raw_path if isinstance(raw_path, str) else None)
        path_field_ok = isinstance(raw_path, str) and bool(raw_path.strip())
        invalid = False
        for field in COMPLETION_ENTRY_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                drift.append({"kind": "completion_invalid", "target": task_id,
                              "path": display,
                              "expected": f"non-empty string {field}",
                              "actual": None if value is None else value})
                invalid = True
        if path_field_ok and error:
            drift.append({"kind": "completion_invalid", "target": task_id,
                          "path": display,
                          "expected": "tower-root-relative path inside the tower",
                          "actual": error})
            invalid = True
        if not invalid:
            record_paths.add(normalized)
    for path in sorted(record_paths - event_paths):
        drift.append({"kind": "completion_unbacked", "target": task_id,
                      "path": path, "expected": path,
                      "actual": "no COMPLETION_ADDED event"})
    for path in sorted(event_paths - record_paths):
        drift.append({"kind": "completion_missing", "target": task_id,
                      "path": path, "expected": "record.completions entry",
                      "actual": "missing"})
    return drift


def _skipped_completion_drift(root: Path, task_id: str,
                              events: list[dict]) -> list[dict]:
    """PILOT-043: audit completions of a ``no_lifecycle_events`` task.

    A record whose replay is skipped is still a record someone could have
    written by hand.  When it claims completions, both halves are audited
    exactly like a replayed task; a legacy record without completions yields
    no row and no extra skip, so old towers verify as before.
    """
    if not is_safe_id(task_id, TASK_ID_RE):
        return []
    _, record = _read_json_object(root / "tasks" / task_id / "record.json")
    if record is None:
        return []
    completions = record.get("completions")
    if not isinstance(completions, list) or not completions:
        return []
    return (_completion_drift(root, task_id, record, events)
            + _completion_mismatch_drift(root, task_id, record, events))


def _record_layer_drift(root: Path, task_id: str, record: dict,
                        completion_events: list[dict],
                        dispatch_events: list[dict]) -> list[dict]:
    """PILOT-043: field and base_sha audits for one replayed task record."""
    return (_completion_mismatch_drift(root, task_id, record, completion_events)
            + _dispatch_base_sha_drift(task_id, record, dispatch_events))


def state_verify_drift(root: Path) -> dict:
    """Compare replayed state with records, board, queue and envelopes.

    Every entity with replayed lifecycle events is checked: a missing or
    unreadable record/envelope file is drift (``record_missing`` /
    ``record_unreadable`` / ``envelope_missing`` / ``envelope_unreadable``),
    never silently skipped.  ``TASK_BOARD.json`` and ``MERGE_QUEUE.json``
    that are missing or unusable yield exactly one file-level
    ``board_unreadable`` / ``queue_unreadable`` entry and suppress the
    per-entity comparison for that file.  Board status is compared against
    the replayed status, not against ``record.status``.

    While folding, each lifecycle event is also checked against its legal
    source states and an out-of-table event yields one ``illegal_transition``
    entry (``event``, ``expected`` allowed from-states, ``actual`` observed
    from-state).  The final-state maps, counts and every other drift are
    unchanged by that check.

    A task without lifecycle events, a replayed task absent from a readable
    board, and a replayed envelope absent from a readable queue are reported
    in ``skipped``; they are observations, never drift.  Envelopes are
    different: a ``MERGE_QUEUE.json`` entry whose id has no replayed lifecycle
    event is ``queue_unbacked`` and an envelope file whose id has no replayed
    lifecycle event is ``envelope_unbacked``.  Both files can be written by
    hand without touching the ledger, so neither is silently skipped.

    A readable record of a replayed task additionally has its claimed
    ``evidence`` entries and frozen ``spec_path``/``spec_sha256`` verified
    against the bytes on disk.  ``evidence_checked`` counts only the evidence
    entries whose bytes were actually hashed.

    PILOT-042 adds the completion audit: a record's ``completions`` must be
    backed path-for-path by ``COMPLETION_ADDED`` events and every event must
    have its record entry (``completion_unbacked`` / ``completion_missing`` /
    ``completion_invalid``).  A task without completions produces no row.
    """
    transitions: list[dict] = []
    task_states = replay_task_statuses(root, transitions)
    envelope_states = replay_envelope_statuses(root, transitions)
    drift: list[dict] = list(transitions)
    skipped: list[dict] = []
    evidence_checked = 0
    completion_events_by_task = ledger_payloads_by_task(root, COMPLETION_ADDED)
    dispatch_events_by_task = ledger_payloads_by_task(root, "DISPATCH")

    def skip(kind: str, target: str, reason: str) -> None:
        skipped.append({"kind": kind, "target": target, "reason": reason})

    board_state, board = _read_json_object(root / "primary" / "TASK_BOARD.json")
    if board is None:
        drift.append({"kind": "board_unreadable", "target": "TASK_BOARD.json",
                      "expected": "parseable JSON object",
                      "actual": "missing" if board_state == "missing"
                                else "unparseable"})
    board_tasks: dict[str, dict] = {}
    if board is not None:
        entries = board.get("tasks")
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("id"):
                board_tasks[str(entry["id"])] = entry

    queue_state, queue = _read_json_object(
        root / "supervision" / "MERGE_QUEUE.json")
    if queue is None:
        drift.append({"kind": "queue_unreadable", "target": "MERGE_QUEUE.json",
                      "expected": "parseable JSON object",
                      "actual": "missing" if queue_state == "missing"
                                else "unparseable"})
    queue_entries: dict[str, dict] = {}
    if queue is not None:
        entries = queue.get("entries")
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("envelope_id"):
                queue_entries[str(entry["envelope_id"])] = entry

    # Entities with replayed events plus record/envelope files on disk, so an
    # entity that only has a file (no ledger event) is reported as skipped
    # instead of disappearing.
    task_ids = set(task_states)
    tasks_dir = root / "tasks"
    if tasks_dir.is_dir():
        for child in tasks_dir.iterdir():
            if child.is_dir() and (child / "record.json").is_file():
                task_ids.add(child.name)
    for task_id in sorted(set(completion_events_by_task) - task_ids):
        drift.append({"kind": "completion_orphan", "target": task_id,
                      "expected": "existing task record", "actual": "none"})
    envelope_ids = set(envelope_states)
    envelope_file_ids: set[str] = set()
    envelopes_dir = root / "supervision" / "envelopes"
    if envelopes_dir.is_dir():
        for child in envelopes_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                envelope_file_ids.add(child.stem)
                envelope_ids.add(child.stem)

    # A queue entry or envelope file that no replayed lifecycle event backs was
    # written by hand, bypassing the ledger.  Report the queue bypass and the
    # envelope bypass separately: one hand-written pair yields both rows.
    for envelope_id in sorted(set(queue_entries) - set(envelope_states)):
        drift.append({"kind": "queue_unbacked", "target": envelope_id,
                      "expected": "QUEUE_ADD ledger event",
                      "actual": "no lifecycle events"})
    for envelope_id in sorted(envelope_file_ids - set(envelope_states)):
        drift.append({"kind": "envelope_unbacked", "target": envelope_id,
                      "expected": "ENVELOPE_NEW ledger event",
                      "actual": "no lifecycle events"})

    for task_id in sorted(task_ids):
        expected = task_states.get(task_id)
        if expected is None:
            skip("task", task_id, "no_lifecycle_events")
            drift.extend(_skipped_completion_drift(
                root, task_id, completion_events_by_task.get(task_id, [])))
            continue
        state, record = ("missing", None)
        if is_safe_id(task_id, TASK_ID_RE):
            state, record = _read_json_object(
                root / "tasks" / task_id / "record.json")
        if record is None:
            drift.append({
                "kind": "record_missing" if state == "missing"
                        else "record_unreadable",
                "target": task_id, "expected": expected, "actual": None})
        else:
            record_status = record.get("status")
            if record_status != expected:
                drift.append({"kind": "task_status", "target": task_id,
                              "expected": expected, "actual": record_status})
            evidence = record.get("evidence")
            if isinstance(evidence, list):
                entry_drift, checked = _evidence_entry_drift(
                    root, task_id, evidence)
                drift.extend(entry_drift)
                evidence_checked += checked
            drift.extend(_spec_drift(root, task_id, record))
            drift.extend(_completion_drift(
                root, task_id, record,
                completion_events_by_task.get(task_id, [])))
            drift.extend(_record_layer_drift(root, task_id, record,
                                             completion_events_by_task.get(task_id, []),
                                             dispatch_events_by_task.get(task_id, [])))
        if board is None:
            continue
        board_entry = board_tasks.get(task_id)
        if board_entry is None:
            skip("task", task_id, "board_entry_missing")
        elif board_entry.get("status") != expected:
            drift.append({"kind": "board_status", "target": task_id,
                          "expected": expected,
                          "actual": board_entry.get("status")})

    for envelope_id in sorted(envelope_ids):
        expected = envelope_states.get(envelope_id)
        if expected is None:
            # Already reported as queue_unbacked / envelope_unbacked above.
            continue
        if queue is not None:
            queue_entry = queue_entries.get(envelope_id)
            if queue_entry is None:
                skip("envelope", envelope_id, "queue_entry_missing")
            elif queue_entry.get("status") != expected:
                drift.append({"kind": "queue_status", "target": envelope_id,
                              "expected": expected,
                              "actual": queue_entry.get("status")})
        # Unsafe ids are never used as a filename: they are not opened.
        if not is_safe_id(envelope_id, PACKAGE_ID_RE):
            continue
        state, envelope = _read_json_object(
            root / "supervision" / "envelopes" / f"{envelope_id}.json")
        if envelope is None:
            drift.append({
                "kind": "envelope_missing" if state == "missing"
                        else "envelope_unreadable",
                "target": envelope_id, "expected": expected, "actual": None})
        elif envelope.get("status") != expected:
            drift.append({"kind": "envelope_status", "target": envelope_id,
                          "expected": expected,
                          "actual": envelope.get("status")})

    drift.extend(_authority_state_drift(root, skip))

    drift.sort(key=lambda item: (item["kind"], str(item["target"]),
                                 item.get("path") or ""))
    skipped.sort(key=lambda item: (item["kind"], str(item["target"])))
    return {"tasks": len(task_states), "envelopes": len(envelope_states),
            "drift": drift, "skipped": skipped,
            "skipped_count": len(skipped),
            "evidence_checked": evidence_checked}


def cmd_state_verify(root: Path, args) -> None:
    """Read-only: replay both ledgers and report observed drift.

    Exit 0 when every compared file agrees with the replay, 2 when any drift
    is found; a broken ledger short-circuits to 2 with ``ledger_errors``.
    ``skipped`` is informational and never affects ``ok`` or the exit code.
    """
    ledger_errors: list[str] = []
    for name in ("primary", "supervision"):
        report = verify_ledger_file(root, name)
        ledger_errors.extend(f"{name}: {err}" for err in report["errors"])
    if ledger_errors:
        emit({"ok": False, "tasks": 0, "envelopes": 0, "drift": [],
              "skipped": [], "skipped_count": 0, "evidence_checked": 0,
              "ledger_errors": ledger_errors}, 2)
    result = state_verify_drift(root)
    payload = {"ok": not result["drift"], "tasks": result["tasks"],
               "envelopes": result["envelopes"], "drift": result["drift"],
               "skipped": result["skipped"],
               "skipped_count": result["skipped_count"],
               "evidence_checked": result["evidence_checked"]}
    emit(payload, 0 if payload["ok"] else 2)
