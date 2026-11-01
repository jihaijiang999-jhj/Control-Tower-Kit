"""Authority state/policy: fields, drift and requirements."""
from __future__ import annotations

from pathlib import Path
from tower_common import (
    PATH_ACCESS_ERRORS, _read_json_object, git, repo_relative, status_path,
    tool_owned_paths,
)
from tower_ledger_replay import ledger_events_in_seq_order


AUTHORITY_STATE_DIRS = ("primary", "supervision", "ledger", "handoffs", "shared",
                        "tasks", "pilot", "state")


def authority_repo(root: Path) -> Path | None:
    """Return the git top-level that contains ``root``, or None.

    None means "not inside a git repository" (or the tower root resolved
    outside the reported top-level), in which case authority drift cannot be
    computed at all.
    """
    cp = git(root, "rev-parse", "--show-toplevel")
    if cp.returncode != 0:
        return None
    top = cp.stdout.strip()
    if not top:
        return None
    repo = Path(top)
    if repo_relative(repo, root) is None:
        return None
    return repo


def authority_drift(root: Path) -> list[str] | None:
    """Uncommitted authority-state paths, relative to the repository root.

    Returns ``None`` when the tower root is not inside a git repository, so a
    caller can distinguish "unknown" from "clean" (``[]``).  Tool-owned output
    directories (``supervision/reviews``, ``supervision/outbox``) are excluded
    because post-merge writes them itself.
    """
    repo = authority_repo(root)
    if repo is None:
        return None
    root_rel = repo_relative(repo, root) or ""
    base = "" if root_rel in ("", ".") else root_rel + "/"
    # Every authority directory is a pathspec, whether or not it still exists:
    # a pathspec also matches tracked paths that were deleted from the working
    # tree, so removing e.g. ``handoffs/`` wholesale is still reported.  A
    # missing directory with nothing tracked under it simply matches nothing.
    watched = [base + name for name in AUTHORITY_STATE_DIRS]
    # ``--untracked-files=all`` keeps a brand-new package directory from
    # collapsing into a single ``handoffs/<id>/`` entry, so the reported list
    # (and the commit hint built from it) names every file.  ``quotepath`` is
    # disabled so non-ASCII paths come back literally and the reported path
    # (and the hint built from it) is actually usable.
    cp = git(repo, "-c", "core.quotepath=false", "status", "--porcelain",
             "--untracked-files=all", "--", *watched)
    if cp.returncode != 0:
        return None
    owned = tool_owned_paths(root, repo)
    drift: list[str] = []
    for line in cp.stdout.splitlines():
        if not line.strip():
            continue
        path = status_path(line)
        if not path:
            continue
        if any(path == prefix or path.startswith(prefix + "/") for prefix in owned):
            continue
        drift.append(path)
    return drift


def authority_commit_hint(root: Path, drift: list[str]) -> str:
    """Shell-ready ``git add``/``git commit`` hint, or "" when nothing drifts."""
    repo = authority_repo(root)
    if not drift or repo is None:
        return ""
    paths = " ".join(f'"{p}"' if " " in p else p for p in drift)
    message = f"handoff: record activated authority state ({len(drift)} file(s))"
    repo_posix = repo.as_posix()
    return (f'git -C "{repo_posix}" add -- {paths} && '
            f'git -C "{repo_posix}" commit -m "{message}"')


AUTHORITY_STATE_SCHEMA = "tower/authority-state@1"


AUTHORITY_STATE_FILE = "state/AUTHORITY.json"


AUTHORITY_SET_EVENT = "AUTHORITY_SET"


AUTHORITY_POLICY_SCHEMA = "tower/authority-policy@1"


AUTHORITY_POLICY_FILE = "shared/AUTHORITY_POLICY.json"


AUTHORITY_REQUIRED_EVENT = "AUTHORITY_REQUIRED"


AUTHORITY_STATE_FIELDS = ("owner", "primary_id", "supervision_id",
                          "merge_authority", "revision", "set_by", "decision",
                          "set_at", "note")


AUTHORITY_TEXT_FIELDS = ("owner", "primary_id", "supervision_id",
                         "merge_authority", "set_by", "decision", "set_at")


AUTHORITY_ABSENT = object()


AUTHORITY_POLICY_FIELDS = ("tower_id", "require_authority", "set_by",
                           "decision", "set_at")


def _state_nested_id(state: dict, key: str, nested: str):
    """``state[key][nested]`` or None, tolerating a non-object value."""
    value = state.get(key)
    return value.get(nested) if isinstance(value, dict) else None


def _state_owner_name(state: dict):
    """``state.owner.name`` or None, tolerating a non-object value."""
    owner = state.get("owner")
    return owner.get("name") if isinstance(owner, dict) else None


def authority_state_fields(state: dict) -> dict:
    """Flatten ``state/AUTHORITY.json`` into the ledger payload field names.

    Absent keys become ``AUTHORITY_ABSENT`` so the comparison distinguishes
    "missing" from "present with a null/invalid value".
    """
    primary = state.get("primary")
    supervision = state.get("supervision")
    return {
        "owner": state.get("owner", AUTHORITY_ABSENT),
        "primary_id": (primary.get("id", AUTHORITY_ABSENT)
                       if isinstance(primary, dict) else AUTHORITY_ABSENT),
        "supervision_id": (supervision.get("id", AUTHORITY_ABSENT)
                           if isinstance(supervision, dict) else AUTHORITY_ABSENT),
        "merge_authority": state.get("merge_authority", AUTHORITY_ABSENT),
        "revision": state.get("revision", AUTHORITY_ABSENT),
        "set_by": state.get("set_by", AUTHORITY_ABSENT),
        "decision": state.get("decision", AUTHORITY_ABSENT),
        "set_at": state.get("set_at", AUTHORITY_ABSENT),
        "note": state.get("note", AUTHORITY_ABSENT),
    }


def authority_payload_fields(payload: dict) -> dict:
    """Flat ``AUTHORITY_SET`` payload fields, same absent sentinel."""
    return {field: payload.get(field, AUTHORITY_ABSENT)
            for field in AUTHORITY_STATE_FIELDS}


def authority_display(value):
    """JSON-safe rendering: an absent field is ``None``."""
    return None if value is AUTHORITY_ABSENT else value


def _authority_field_errors(fields: dict, label: str) -> list[str]:
    """Type rules for one side (file or ledger payload).

    ``bool`` is not an ``int`` here: ``True == 1`` in Python, which is exactly
    how ``revision: true`` used to slip through an equality-only comparison.
    """
    errors: list[str] = []
    for field in AUTHORITY_TEXT_FIELDS:
        value = fields[field]
        if not isinstance(value, str) or not value:
            errors.append(f"{label} {field} must be a non-empty string")
    revision = fields["revision"]
    if type(revision) is not int or revision < 1:
        errors.append(f"{label} revision must be an int >= 1")
    note = fields["note"]
    if note is not AUTHORITY_ABSENT and (not isinstance(note, str) or not note):
        errors.append(f"{label} note must be a non-empty string when present")
    return errors


def _authority_mismatch_detail(fields: dict, payload: dict,
                               mismatched: list[str]) -> str:
    """One line naming every mismatching field and both values."""
    return ", ".join(
        f"{field} {authority_display(fields[field])!r} != "
        f"{authority_display(payload[field])!r}" for field in mismatched)


def last_authority_event(root: Path) -> tuple[bool, dict | None]:
    """``(event_present, payload)`` for the last ``AUTHORITY_SET`` event.

    The event payload -- not the file -- is the authority.  A ledger that
    cannot be read is reported as "no event" here: ``verify-ledger`` and
    ``state-verify`` own that failure, and every caller of this helper is
    read-only.  This helper never raises.
    """
    try:
        events = [event for event in ledger_events_in_seq_order(root, "primary")
                  if event.get("type") == AUTHORITY_SET_EVENT]
    except PATH_ACCESS_ERRORS:
        return False, None
    if not events:
        return False, None
    payload = events[-1].get("payload")
    return True, payload if isinstance(payload, dict) else None


def last_authority_required_event(root: Path) -> tuple[bool, dict | None]:
    """``(event_present, payload)`` for the last ``AUTHORITY_REQUIRED`` event.

    The policy file must mirror this payload exactly (PILOT-039).  Like
    :func:`last_authority_event` this is read-only and never raises: an
    unreadable ledger is "no event" here, and ``verify-ledger``/``state-verify``
    own ledger corruption.
    """
    try:
        events = [event for event in ledger_events_in_seq_order(root, "primary")
                  if event.get("type") == AUTHORITY_REQUIRED_EVENT]
    except PATH_ACCESS_ERRORS:
        return False, None
    if not events:
        return False, None
    payload = events[-1].get("payload")
    return True, payload if isinstance(payload, dict) else None


def authority_policy_fields(policy) -> dict:
    """The five compared policy fields, with the absent-vs-null sentinel.

    A non-object (or ``None``) contributes every field as absent, so a policy
    or event payload that is not an object can never compare equal to one that
    is.  ``authority_display`` renders the sentinel as ``null`` for JSON.
    """
    source = policy if isinstance(policy, dict) else {}
    return {field: source.get(field, AUTHORITY_ABSENT)
            for field in AUTHORITY_POLICY_FIELDS}


def _authority_policy_value_ok(field: str, value) -> bool:
    """Per-field type rule for the policy/event comparison.

    ``require_authority`` must be the boolean ``True``: ``"true"``, ``1`` and
    ``null`` are truthy look-alikes and are rejected here, not coerced.  Every
    other field must be a non-empty string.
    """
    if field == "require_authority":
        return value is True
    return isinstance(value, str) and bool(value)


def authority_policy_mismatch(root: Path, requirement: dict) -> dict | None:
    """Field-level comparison of the policy file with the last event payload.

    Returns ``None`` when there is no pair to compare (event absent or policy
    not required: those are ``policy_unbacked``/``policy_missing``) or when the
    halves agree.  Otherwise returns ``fields`` (every differing field, in the
    canonical order), plus ``expected`` (event payload side) and ``actual``
    (policy file side) dictionaries, so callers can emit one row or one error
    line naming all of them.  ``tower_id`` additionally binds to the primary
    state, because the policy's tower identity is what the requirement is
    anchored to.
    """
    if not (requirement["policy_required"] and requirement["event_present"]):
        return None
    policy_fields = authority_policy_fields(requirement.get("policy"))
    event_fields = authority_policy_fields(requirement.get("event_payload"))
    mismatched: list[str] = []
    for field in AUTHORITY_POLICY_FIELDS:
        if not _authority_policy_value_ok(field, policy_fields[field]) or \
                not _authority_policy_value_ok(field, event_fields[field]):
            mismatched.append(field)
        elif policy_fields[field] != event_fields[field]:
            mismatched.append(field)
    # ``tower_id`` is also bound to the primary state.  When both halves agree
    # with each other but not with the primary state, the primary state is the
    # expectation; the row/line still names exactly one field.
    primary_tower_id = AUTHORITY_ABSENT
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    if isinstance(primary_state, dict):
        primary_tower_id = primary_state.get("tower_id", AUTHORITY_ABSENT)
    if (isinstance(primary_tower_id, str) and primary_tower_id
            and policy_fields["tower_id"] != primary_tower_id
            and "tower_id" not in mismatched):
        mismatched.append("tower_id")
    if not mismatched:
        return None
    expected = {field: authority_display(event_fields[field])
                for field in AUTHORITY_POLICY_FIELDS}
    actual = {field: authority_display(policy_fields[field])
              for field in AUTHORITY_POLICY_FIELDS}
    if ("tower_id" in mismatched
            and isinstance(primary_tower_id, str) and primary_tower_id
            and expected["tower_id"] == actual["tower_id"]):
        expected["tower_id"] = primary_tower_id
    return {"fields": mismatched, "expected": expected, "actual": actual}


def authority_policy_mismatch_detail(result: dict) -> str:
    """One line naming every differing field with its policy/event values."""
    parts: list[str] = []
    for field in result["fields"]:
        actual = result["actual"][field]
        expected = result["expected"][field]
        if field == "require_authority":
            parts.append(f"require_authority {actual!r} != {expected!r} "
                         "(both sides must be boolean true)")
        else:
            parts.append(f"{field} {actual!r} != {expected!r}")
    return "; ".join(parts)


def authority_policy_invalid(requirement: dict) -> bool:
    """True when a policy file exists but is not a valid requirement marker.

    A malformed policy is fail-closed: it must never degrade the tower to
    "optional"/legacy just because ``require_authority`` failed a type check.
    The only way to not require authority is to have no policy file at all.
    """
    return (requirement["policy_state"] != "missing"
            and not requirement["policy_required"])


def next_authority_revision(root: Path) -> int:
    """One more than the file's or the last event's revision.

    Re-running ``authority-set`` on a half-written tower (one half present)
    therefore continues the sequence instead of resetting it to 1.
    """
    revisions: list[int] = []
    _, state = _read_json_object(root / AUTHORITY_STATE_FILE)
    if isinstance(state, dict):
        value = state.get("revision")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            revisions.append(value)
    _, payload = last_authority_event(root)
    if isinstance(payload, dict):
        value = payload.get("revision")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            revisions.append(value)
    return (max(revisions) if revisions else 0) + 1


def authority_policy_required(policy: dict | None) -> bool:
    """True only for a parsed policy object that literally requires authority.

    ``require_authority: "true"`` or ``1`` must not count: the persisted
    requirement is a boolean fact, and a truthy look-alike could otherwise
    satisfy the policy side of the pairing check.
    """
    return isinstance(policy, dict) and policy.get("require_authority") is True


def authority_required_event(root: Path) -> bool:
    """True iff ``ledger/primary.jsonl`` carries an ``AUTHORITY_REQUIRED`` row.

    Read-only and exception-free: an unreadable ledger is reported as "no
    event" here, exactly like :func:`last_authority_event`.  ``verify-ledger``
    and ``state-verify`` own ledger corruption; every caller of this helper is
    read-only and must not traceback on it.
    """
    try:
        return any(event.get("type") == AUTHORITY_REQUIRED_EVENT
                   for event in ledger_events_in_seq_order(root, "primary"))
    except PATH_ACCESS_ERRORS:
        return False


def authority_requirement(root: Path) -> dict:
    """Read-only view of the persisted authority requirement (PILOT-038).

    ``required`` is true when either half of the marker exists: the policy file
    sets ``require_authority=true`` or the ledger carries an
    ``AUTHORITY_REQUIRED`` event.  A tower with neither half is not required
    and keeps the 037 legacy behaviour.  ``policy_state`` distinguishes
    missing/unreadable from a parsed object.
    """
    policy_state, policy = _read_json_object(root / AUTHORITY_POLICY_FILE)
    policy_required = authority_policy_required(policy)
    event_present = authority_required_event(root)
    _, event_payload = last_authority_required_event(root)
    return {
        "policy_state": policy_state,
        "policy": policy,
        "policy_required": policy_required,
        "event_present": event_present,
        "event_payload": event_payload,
        "required": policy_required or event_present,
    }


def _authority_policy_payload(primary_state: dict, by: str, decision: str,
                              set_at: str) -> dict:
    """The policy file body, also used verbatim as the event payload.

    Both sides are deliberately isomorphic: the policy file and the
    ``AUTHORITY_REQUIRED`` event carry exactly the same keys, so the persisted
    requirement can be reconstructed from either half.
    """
    return {
        "schema": AUTHORITY_POLICY_SCHEMA,
        "tower_id": primary_state.get("tower_id"),
        "require_authority": True,
        "set_by": by,
        "decision": decision,
        "set_at": set_at,
    }


def authority_requirement_errors(root: Path, requirement: dict) -> list[str]:
    """Pairing errors for a required tower; empty when the halves agree.

    ``authority policy unbacked`` (policy true, no event) and ``authority
    policy missing`` (event, no policy/false policy) are flat strings so
    ``merge`` can fail closed with them and ``state-verify`` can name the
    matching drift kind.

    PILOT-039 adds two fail-closed cases: a policy file that exists but is not
    a valid marker (wrong/absent ``require_authority``, unparseable JSON) can
    never degrade the tower to optional, and when both halves exist every
    shared field must be identical -- a rewritten ``set_by``/``decision``/
    ``set_at``/``tower_id`` is named in one line, exactly like a changed
    ``require_authority`` type.
    """
    errors: list[str] = []
    if requirement["policy_required"] and not requirement["event_present"]:
        errors.append(
            "authority policy unbacked: "
            f"{AUTHORITY_POLICY_FILE} sets require_authority=true but "
            f"ledger/primary.jsonl has no {AUTHORITY_REQUIRED_EVENT} event")
    elif requirement["event_present"] and not requirement["policy_required"]:
        errors.append(
            "authority policy missing: "
            f"ledger/primary.jsonl has an {AUTHORITY_REQUIRED_EVENT} event "
            f"but {AUTHORITY_POLICY_FILE} is missing or does not set "
            "require_authority=true")
    elif authority_policy_invalid(requirement):
        detail = ("is not a parseable JSON object"
                  if requirement["policy_state"] == "unreadable"
                  else "does not set require_authority=true (boolean)")
        errors.append(f"authority policy invalid: {AUTHORITY_POLICY_FILE} "
                      f"{detail}")
    if requirement["policy_required"] and requirement["event_present"]:
        mismatch = authority_policy_mismatch(root, requirement)
        if mismatch is not None:
            errors.append(
                "authority policy does not match last "
                f"{AUTHORITY_REQUIRED_EVENT}: "
                + authority_policy_mismatch_detail(mismatch))
    return errors


def _authority_state_drift(root: Path, skip) -> list[dict]:
    """Drift rows for ``state/AUTHORITY.json`` against the last AUTHORITY_SET.

    Read-only and exception-free: ``_read_json_object`` turns every read
    failure into ``unreadable``.  A tower with neither half *and no persisted
    requirement* is legacy and is reported as one ``skipped`` observation,
    never drift, so an old tower still verifies clean.  Every other
    combination is drift; a required tower never reaches the legacy skip.

    PILOT-038 adds the requirement dimension: a tower that persisted
    ``require_authority`` must have both halves of the marker
    (``authority_policy_missing`` / ``authority_policy_unbacked``) and must
    still have a configured authority state
    (``authority_required_unconfigured``).  The drift row shape is unchanged
    (``kind`` / ``target`` / ``expected`` / ``actual``).

    PILOT-039 adds ``authority_policy_mismatch``: when both halves exist they
    must agree on every shared field, so a rewritten audit field is drift.
    A policy file that exists but is not a valid marker is fail-closed drift
    too (same row kind, the shape rather than the event is the expectation).
    """
    file_state, state = _read_json_object(root / AUTHORITY_STATE_FILE)
    event_present, payload_obj = last_authority_event(root)
    requirement = authority_requirement(root)
    required = requirement["required"]

    rows: list[dict] = []
    if required:
        if requirement["event_present"] and not requirement["policy_required"]:
            rows.append({
                "kind": "authority_policy_missing",
                "target": "AUTHORITY_POLICY",
                "expected": f"{AUTHORITY_POLICY_FILE} with "
                            "require_authority=true",
                "actual": ("missing" if requirement["policy_state"] == "missing"
                           else "require_authority is not true")})
        elif requirement["policy_required"] and not requirement["event_present"]:
            rows.append({
                "kind": "authority_policy_unbacked",
                "target": "AUTHORITY_POLICY",
                "expected": f"{AUTHORITY_REQUIRED_EVENT} ledger event",
                "actual": "policy file only"})
        if file_state == "missing" or not event_present:
            rows.append({
                "kind": "authority_required_unconfigured",
                "target": "AUTHORITY",
                "expected": "state/AUTHORITY.json backed by an AUTHORITY_SET "
                            "event (authority is required)",
                "actual": ("missing" if file_state == "missing"
                           else "no AUTHORITY_SET event")})
            # The requirement rows are the whole story here: adding 037's
            # authority_missing/unbacked rows would only duplicate the same
            # missing half under a legacy-compatible name.
            return rows
        # PILOT-039: both halves exist, so the policy file must repeat the last
        # AUTHORITY_REQUIRED payload field for field (audit fields included).
        mismatch = authority_policy_mismatch(root, requirement)
        if mismatch is not None:
            rows.append({
                "kind": "authority_policy_mismatch",
                "target": "AUTHORITY_POLICY",
                "expected": mismatch["expected"],
                "actual": mismatch["actual"]})

    if not required and authority_policy_invalid(requirement):
        # A present-but-invalid policy is fail-closed drift: it can never turn
        # into the legacy skip below just because require_authority is not
        # literally true.
        fields = authority_policy_fields(requirement["policy"])
        rows.append({
            "kind": "authority_policy_mismatch",
            "target": "AUTHORITY_POLICY",
            "expected": {"require_authority": True},
            "actual": {field: authority_display(fields[field])
                       for field in AUTHORITY_POLICY_FIELDS},
        })
        if file_state == "missing" and not event_present:
            return rows

    if file_state == "missing" and not event_present:
        skip("authority_state", "AUTHORITY", "no_authority_state")
        return rows
    if file_state == "unreadable":
        rows.append({"kind": "authority_unreadable", "target": "AUTHORITY",
                     "expected": "parseable JSON object",
                     "actual": "unparseable"})
        return rows
    if file_state == "missing":
        rows.append({"kind": "authority_missing", "target": "AUTHORITY",
                     "expected": "state/AUTHORITY.json matching the last "
                                 "AUTHORITY_SET event",
                     "actual": "missing"})
        return rows
    if not event_present:
        rows.append({"kind": "authority_unbacked", "target": "AUTHORITY",
                     "expected": "AUTHORITY_SET ledger event",
                     "actual": "file only"})
        return rows
    payload = payload_obj if isinstance(payload_obj, dict) else {}
    file_fields = authority_state_fields(state)
    payload_fields = authority_payload_fields(payload)
    mismatched = [field for field in AUTHORITY_STATE_FIELDS
                  if file_fields[field] != payload_fields[field]]
    type_errors = (_authority_field_errors(file_fields, "file")
                   + _authority_field_errors(payload_fields, "ledger"))
    expected = {field: authority_display(payload_fields[field])
                for field in AUTHORITY_STATE_FIELDS}
    actual = {field: authority_display(file_fields[field])
              for field in AUTHORITY_STATE_FIELDS}
    expected["schema"] = AUTHORITY_STATE_SCHEMA
    actual["schema"] = state.get("schema")
    if actual["schema"] != AUTHORITY_STATE_SCHEMA:
        mismatched.append("schema")
    # ``tower_id`` is not part of the event payload, so it is bound to the
    # primary state instead -- but only when that state is readable, so the
    # audit stays exception-free on partial fixtures.
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    if isinstance(primary_state, dict):
        primary_tower_id = primary_state.get("tower_id", AUTHORITY_ABSENT)
        if isinstance(primary_tower_id, str) and primary_tower_id:
            expected["tower_id"] = primary_tower_id
            actual["tower_id"] = authority_display(
                state.get("tower_id", AUTHORITY_ABSENT))
            if actual["tower_id"] != primary_tower_id:
                mismatched.append("tower_id")
    if mismatched or type_errors:
        rows.append({"kind": "authority_mismatch", "target": "AUTHORITY",
                     "expected": expected, "actual": actual})
    return rows
