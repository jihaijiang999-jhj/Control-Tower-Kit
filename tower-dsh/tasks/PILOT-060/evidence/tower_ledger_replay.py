"""Ledger verification and event replay into lifecycle state."""
from __future__ import annotations

from pathlib import Path
from tower_common import _read_json_object, emit, rel
from tower_ledger import (
    GENESIS_PREV_HASH, LEDGER_FILES, event_hash, ledger_rows, legacy_anchor,
    parse_ledger_row,
)


def ledger_payloads_by_task(root: Path, event_type: str) -> dict[str, list[dict]]:
    """Payloads of ``event_type`` events in the primary ledger, keyed by task.

    PILOT-043 reads the same projection twice (``COMPLETION_ADDED`` for the
    deliver/completion audit and ``DISPATCH`` for the ``base_sha`` audit), so
    the grouping lives in one read-only helper.
    """
    grouped: dict[str, list[dict]] = {}
    for event in ledger_events_in_seq_order(root, "primary"):
        if event.get("type") != event_type:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        task = payload.get("task")
        if isinstance(task, str) and task:
            grouped.setdefault(task, []).append(payload)
    return grouped


CHECKBACK_STATUSES = ("delivered", "reviewed", "rework", "accepted")


def verify_ledger_file(root: Path, name: str) -> dict:
    """Validate one ledger file: presence, JSON, seq, hashes and prev links.

    A missing ledger is a *failed* verification, not an empty one: the old
    code parsed it as zero rows and reported no errors, so every caller read
    "the file is not there" as "the chain is intact".  An existing empty file
    is still a valid empty chain.  Any read error (a directory in place of the
    file, an ACL denial, ...) becomes one ``ledger unreadable`` error instead
    of a traceback, so the CLI can always emit exactly one JSON payload.
    """
    path = root / "ledger" / LEDGER_FILES[name]
    result = {
        "path": rel(root, path),
        "exists": False,
        "events": 0,
        "legacy_unhashed": 0,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append(f"ledger missing: {rel(root, path)}")
        return result
    result["exists"] = True
    try:
        rows = ledger_rows(path)
    except OSError as exc:
        result["errors"].append(
            f"ledger unreadable: {rel(root, path)}: {exc}")
        return result
    expected_seq = 1
    expected_prev = GENESIS_PREV_HASH
    chain_started = False
    for row_no, raw in enumerate(rows, 1):
        event = parse_ledger_row(raw)
        if event is None:
            result["errors"].append(f"row {row_no}: not a valid JSON object")
            expected_prev = legacy_anchor(raw)
            expected_seq += 1
            continue
        result["events"] += 1
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            result["errors"].append(f"row {row_no}: seq missing or not an integer")
        elif seq != expected_seq:
            result["errors"].append(
                f"row {row_no}: seq {seq} != expected {expected_seq}")
        expected_seq += 1
        if "hash" in event:
            chain_started = True
            if event.get("prev_hash") != expected_prev:
                result["errors"].append(
                    f"row {row_no}: prev_hash {event.get('prev_hash')!r} != expected {expected_prev!r}")
            if event.get("hash") != event_hash(event):
                result["errors"].append(f"row {row_no}: hash mismatch (event tampered)")
            recorded = event.get("hash")
            expected_prev = recorded if isinstance(recorded, str) and recorded \
                else legacy_anchor(raw)
        else:
            if chain_started:
                result["errors"].append(
                    f"row {row_no}: unhashed event after the hash chain started")
            else:
                result["legacy_unhashed"] += 1
            expected_prev = legacy_anchor(raw)
    return result


def ledger_precondition_breaks(root: Path) -> list[tuple[str, str]]:
    """``(ledger name, first error)`` for every ledger that fails verification.

    PILOT-039 v2: ``merge`` and the legacy ``merge-check`` precondition verify
    *both* ledgers unconditionally.  A missing ledger is a failure, not "no
    chain to verify": PILOT-036 already established that absence is not
    integrity, and skipping it let deleting ``ledger/supervision.jsonl`` turn a
    legacy envelope into a MERGED merge whose ledger was then recreated.  An
    existing ledger is verified in full -- a forged row can keep
    ``seq``/``prev_hash`` legal and still be caught by the hash.
    """
    breaks: list[tuple[str, str]] = []
    for name in ("primary", "supervision"):
        report = verify_ledger_file(root, name)
        if report["errors"]:
            breaks.append((name, report["errors"][0]))
    return breaks


def ledger_break_phrase(name: str, first: str) -> str:
    """``<name> ledger chain missing/broken: <first error>`` for gate text."""
    kind = "missing" if first.startswith("ledger missing:") else "broken"
    return f"{name} ledger chain {kind}: {first}"


EMPTY_SUPERVISION_LEDGER = ("supervision ledger is empty but envelope/queue "
                            "history exists")


def supervision_artifacts(root: Path) -> list[str]:
    """Supervision artifacts that imply history the ledger should back.

    PILOT-040: envelope files, merge-queue entries and merge-ledger entries are
    the three files a tower writes as it merges.  They are only legitimate when
    ``ledger/supervision.jsonl`` records how they got there.  Read-only, and
    unreadable artifacts are skipped here: ``state-verify`` already reports
    them (`queue_unreadable` / `merge-ledger` drift) and this guard must not
    pretend an unparseable file is history.
    """
    artifacts: list[str] = []
    envelope_dir = root / "supervision" / "envelopes"
    if envelope_dir.is_dir():
        for child in sorted(envelope_dir.iterdir()):
            if child.is_file() and child.suffix == ".json":
                artifacts.append(rel(root, child))
    queue_path = root / "supervision" / "MERGE_QUEUE.json"
    _, queue = _read_json_object(queue_path)
    if isinstance(queue, dict):
        entries = queue.get("entries")
        if isinstance(entries, list) and entries:
            artifacts.append(f"{rel(root, queue_path)} entries={len(entries)}")
    merge_ledger_path = (root / "supervision" / "registries"
                         / "merge-ledger.json")
    _, merge_ledger = _read_json_object(merge_ledger_path)
    if isinstance(merge_ledger, dict):
        entries = merge_ledger.get("entries")
        if isinstance(entries, list) and entries:
            artifacts.append(f"{rel(root, merge_ledger_path)} "
                             f"entries={len(entries)}")
    return artifacts


def supervision_ledger_event_count(root: Path) -> int | None:
    """Parseable events in ``ledger/supervision.jsonl``; ``None`` if unreadable.

    A whitespace-only file counts as zero events (it is an empty chain), while
    a row that is not a JSON object is not an event either.  ``None`` means the
    file itself cannot be read; that is a chain failure handled by 039, not an
    empty ledger, so the 040 guard must decline to judge it.
    """
    path = root / "ledger" / LEDGER_FILES["supervision"]
    if not path.is_file():
        return None
    try:
        rows = ledger_rows(path)
    except OSError:
        return None
    return sum(1 for raw in rows if parse_ledger_row(raw) is not None)


def cmd_verify_ledger(root: Path, args) -> None:
    names = ["primary", "supervision"] if args.ledger == "all" else [args.ledger]
    files = {}
    errors = []
    for name in names:
        report = verify_ledger_file(root, name)
        files[name] = report
        errors.extend(f"{name}: {err}" for err in report["errors"])
    emit({"ok": not errors, "files": files, "errors": errors},
         0 if not errors else 2)


TASK_LIFECYCLE_STATUS = {
    "TASK_NEW": "ready",
    "DISPATCH": "dispatched",
    "DELIVER": "delivered",
    "ACCEPT": "accepted",
    "CLOSEOUT": "closed",
}


ENVELOPE_LIFECYCLE_STATUS = {
    "ENVELOPE_NEW": "DRAFT",
    "QUEUE_ADD": "WAITING",
    "MERGE": "MERGED",
    "POST_MERGE_VERIFIED": "POST_MERGE_VERIFIED",
}


ENVELOPE_CORRECTION_EVENTS = {"MERGE_BLOCKED", "POST_MERGE_FAILED"}


ENVELOPE_MERGING_STATUS = "MERGING"


ENVELOPE_REOPEN_STATUSES = frozenset({"WAITING", "CORRECTION_REQUIRED",
                                      "MERGED", "POST_MERGE_VERIFIED"})


ENVELOPE_MERGEABLE_STATUSES = frozenset({"WAITING", "CORRECTION_REQUIRED"})


ENVELOPE_TERMINAL_STATUSES = frozenset({"MERGED", "POST_MERGE_VERIFIED"})


TASK_TRANSITIONS = {
    "TASK_NEW": frozenset({None, "ready", "dispatched", "delivered",
                           "reviewed", "rework"}),
    # PILOT-055 (owner choice A): a second DISPATCH replaces the executor of a
    # card that is already ``dispatched``.  The real ledger re-dispatched
    # PILOT-055 from its placeholder executor to the real one, which is a
    # replacement, not a new lifecycle step.  Only ``dispatched`` joins the
    # table: a ``delivered``/``reviewed``/``closed`` card still cannot be
    # re-dispatched, so the table is not a blanket ``any -> dispatched``.
    "DISPATCH": frozenset({"ready", "rework", "dispatched"}),
    "DELIVER": frozenset({"dispatched", "delivered", "rework"}),
    # PILOT-058 adds ``accepted``: a re-envelope can move the reviewed head, so
    # a re-review of an accepted card is legal (and re-opens it to ``reviewed``).
    "CHECKBACK": frozenset(CHECKBACK_STATUSES),
    "ACCEPT": frozenset({"reviewed"}),
    "CLOSEOUT": frozenset({"accepted"}),
}


ENVELOPE_TRANSITIONS = {
    "ENVELOPE_NEW": frozenset({None, "DRAFT", "WAITING",
                               "CORRECTION_REQUIRED"}),
    "QUEUE_ADD": frozenset({"DRAFT"}),
    # PILOT-060: a merge that already wrote ``MERGE_START`` and then failed
    # (056: dirty working tree before any ledger write) retries from the
    # internal ``MERGING`` state.  Only the retry joins the table: the merge
    # has not settled anything yet, so ``DRAFT`` / ``MERGED`` /
    # ``POST_MERGE_VERIFIED`` still cannot start a merge.
    "MERGE_START": frozenset({"WAITING", "CORRECTION_REQUIRED",
                              ENVELOPE_MERGING_STATUS}),
    "MERGE": frozenset({ENVELOPE_MERGING_STATUS}),
    "POST_MERGE_VERIFIED": frozenset({"MERGED", "CORRECTION_REQUIRED"}),
    "MERGE_BLOCKED": frozenset({"WAITING", ENVELOPE_MERGING_STATUS,
                                "CORRECTION_REQUIRED"}),
    "POST_MERGE_FAILED": frozenset({"MERGED", "CORRECTION_REQUIRED"}),
}


def ledger_events_in_seq_order(root: Path, name: str) -> list[dict]:
    """Parsed ledger events sorted by ``seq`` (file order breaks ties).

    Rows that are not JSON objects are skipped here; ``verify_ledger_file``
    reports them, and ``state-verify`` refuses to replay a broken ledger.
    """
    rows = []
    for index, raw in enumerate(ledger_rows(root / "ledger" / LEDGER_FILES[name])):
        event = parse_ledger_row(raw)
        if event is None:
            continue
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            rows.append(((0, seq, index), event))
        else:
            rows.append(((1, 0, index), event))
    return [event for _, event in sorted(rows, key=lambda pair: pair[0])]


def ledger_events_naming(root: Path, name: str, event_type: str,
                         envelope_id) -> list[dict]:
    """Payloads of ``event_type`` events in ``ledger/<name>.jsonl`` naming it.

    Read-only.  A caller that needs more than existence (the ``ENVELOPE_NEW``
    binding check) can inspect the payloads; :func:`ledger_has_event` is the
    boolean wrapper.  Rows that are not JSON objects are ignored, exactly like
    :func:`ledger_has_event`.
    """
    payloads = []
    for event in ledger_events_in_seq_order(root, name):
        if event.get("type") != event_type:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("envelope") == envelope_id:
            payloads.append(payload)
    return payloads


def ledger_has_event(root: Path, name: str, event_type: str,
                     envelope_id) -> bool:
    """True iff one ``event_type`` event in ``ledger/<name>.jsonl`` names it.

    Read-only.  Rows that are not JSON objects are ignored by
    :func:`ledger_events_in_seq_order`; ``state-verify`` still refuses to replay
    a ledger whose chain is broken.
    """
    return bool(ledger_events_naming(root, name, event_type, envelope_id))


def ledger_has_queue_add(root: Path, envelope_id) -> bool:
    """True iff one ``QUEUE_ADD`` event in ``ledger/supervision.jsonl`` names it.

    Read-only.  Rows that are not JSON objects are ignored by
    :func:`ledger_events_in_seq_order`; ``state-verify`` still refuses to replay
    a ledger whose chain is broken.
    """
    return ledger_has_event(root, "supervision", "QUEUE_ADD", envelope_id)


def _sorted_states(states) -> list:
    """Sort allowed from-states for a drift row: ``None`` first, then names."""
    return sorted(states, key=lambda state: (state is not None, state or ""))


def _illegal_transition(target: str, event_type: str, allowed,
                        actual: str | None) -> dict:
    """One drift row for an event whose source state is outside the table."""
    return {"kind": "illegal_transition", "target": target,
            "event": event_type, "expected": _sorted_states(allowed),
            "actual": actual}


def replay_task_statuses(root: Path,
                         transitions: list[dict] | None = None) -> dict[str, str]:
    """Fold ``ledger/primary.jsonl`` by task into the expected status.

    When ``transitions`` is a list, append one ``illegal_transition`` row for
    every lifecycle event whose source state is outside :data:`TASK_TRANSITIONS`
    (``TASK_NEW`` creates a card from ``None`` and rebuilds only unfinished
    cards, never one that is already ``accepted``/``closed``).  The fold itself
    is untouched: an illegal event is still replayed last-writer-wins, so the
    final-state map and every existing drift stay exactly as before; the caller
    reports the extra rows.  Unknown event types are ignored and never produce
    a transition.
    """
    states: dict[str, str] = {}
    for event in ledger_events_in_seq_order(root, "primary"):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        task = payload.get("task")
        if not isinstance(task, str) or not task:
            continue
        event_type = event.get("type")
        if event_type == "CHECKBACK":
            next_state = "reviewed" if payload.get("verdict") == "PASS" else "rework"
        elif event_type in TASK_LIFECYCLE_STATUS:
            next_state = TASK_LIFECYCLE_STATUS[event_type]
        else:
            # Unknown / non-lifecycle event: ignored, exactly as before.
            continue
        if transitions is not None:
            allowed = TASK_TRANSITIONS.get(event_type)
            previous = states.get(task)
            if allowed is not None and previous not in allowed:
                transitions.append(
                    _illegal_transition(task, event_type, allowed, previous))
        states[task] = next_state
    return states


def _fold_envelope_state(states: dict[str, str], internal: dict[str, str],
                         envelope: str, event_type: str, next_state: str) -> None:
    """Fold one envelope lifecycle event without resetting a live envelope.

    ``states`` is the folded status, ``internal`` the last event's state used
    for the transition table (``MERGE_START`` pins ``MERGING`` without settling
    the status).  A re-envelope ``ENVELOPE_NEW`` on an envelope that already
    reached a status in :data:`ENVELOPE_REOPEN_STATUSES` only re-records its
    head: the folded status and the transition source stay where they were, so
    a corrected envelope still replays to ``CORRECTION_REQUIRED``.  A brand-new
    envelope (no previous status) still folds to ``DRAFT``.
    """
    if (event_type == "ENVELOPE_NEW"
            and states.get(envelope) in ENVELOPE_REOPEN_STATUSES):
        return
    internal[envelope] = next_state
    if event_type != "MERGE_START":
        states[envelope] = next_state


def replay_envelope_statuses(root: Path,
                             transitions: list[dict] | None = None) -> dict[str, str]:
    """Fold ``ledger/supervision.jsonl`` by envelope into expected status.

    ``MERGE_START`` moves an internal-only state to ``MERGING`` (it still
    leaves the folded status unchanged), so a following ``MERGE`` is checked
    against the merge that actually started.  When ``transitions`` is a list,
    append one ``illegal_transition`` row for every lifecycle event whose
    source state is outside :data:`ENVELOPE_TRANSITIONS`; the fold and every
    existing drift keep their previous values.  Unknown events are ignored.
    """
    states: dict[str, str] = {}
    internal: dict[str, str] = {}
    for event in ledger_events_in_seq_order(root, "supervision"):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        envelope = payload.get("envelope")
        if not isinstance(envelope, str) or not envelope:
            continue
        event_type = event.get("type")
        if event_type == "MERGE_START":
            next_state = ENVELOPE_MERGING_STATUS
        elif event_type in ENVELOPE_LIFECYCLE_STATUS:
            next_state = ENVELOPE_LIFECYCLE_STATUS[event_type]
        elif event_type in ENVELOPE_CORRECTION_EVENTS:
            next_state = "CORRECTION_REQUIRED"
        else:
            # Unknown / non-lifecycle event: ignored, exactly as before.
            continue
        if transitions is not None:
            allowed = ENVELOPE_TRANSITIONS.get(event_type)
            previous = internal.get(envelope)
            if allowed is not None and previous not in allowed:
                transitions.append(
                    _illegal_transition(envelope, event_type, allowed, previous))
        _fold_envelope_state(states, internal, envelope, event_type, next_state)
    return states
