"""Authority commands and the authority state gate."""
from __future__ import annotations

from pathlib import Path
from tower_common import _read_json_object, emit, fail, jdump, now, rel
from tower_ledger import LEDGER_FILES, LedgerLockTimeout, append_ledger, authority_lock
from tower_ledger_replay import (
    EMPTY_SUPERVISION_LEDGER, supervision_artifacts,
    supervision_ledger_event_count, verify_ledger_file,
)
from tower_authority import (
    AUTHORITY_ABSENT, AUTHORITY_POLICY_FIELDS, AUTHORITY_POLICY_FILE,
    AUTHORITY_REQUIRED_EVENT, AUTHORITY_SET_EVENT, AUTHORITY_STATE_FIELDS,
    AUTHORITY_STATE_FILE, AUTHORITY_STATE_SCHEMA, _authority_field_errors,
    _authority_mismatch_detail, _authority_policy_payload,
    _authority_policy_value_ok, _state_nested_id, _state_owner_name,
    authority_display, authority_payload_fields, authority_policy_fields,
    authority_policy_mismatch, authority_requirement, authority_requirement_errors,
    authority_state_fields, last_authority_event, next_authority_revision,
)


def authority_state_check(root: Path) -> dict:
    """Read-only audit of ``state/AUTHORITY.json`` against the ledger.

    ``status`` is ``"legacy"`` only when neither the file nor an
    ``AUTHORITY_SET`` event exists *and* the tower never required authority,
    which keeps old towers working.  Every other combination is
    ``"configured"`` and must pass every check: strict field types,
    ``tower_id`` bound to the primary state, every field of the file equal to
    the last event payload (optional ``note`` included), and an intact primary
    ledger chain for the event.

    PILOT-038 adds the requirement dimension.  ``required`` is true when
    ``shared/AUTHORITY_POLICY.json`` sets ``require_authority=true`` or the
    ledger carries an ``AUTHORITY_REQUIRED`` event.  A required tower whose
    authority state is missing is ``"required_unconfigured"`` (never legacy),
    and a required tower must have both halves of the marker: policy without
    event is ``authority policy unbacked``, event without policy is
    ``authority policy missing``.  A broken file or ledger becomes a failed
    check, never an exception.  ``errors`` carries one flat line per failed
    check so ``merge`` can fail closed with them.
    """
    checks: list[dict] = []
    errors: list[str] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    file_state, state = _read_json_object(root / AUTHORITY_STATE_FILE)
    event_present, payload_obj = last_authority_event(root)
    payload = payload_obj if isinstance(payload_obj, dict) else {}
    requirement = authority_requirement(root)
    required = requirement["required"]

    # The marker is checked first: a required tower can never fall through to
    # the legacy branch below, so deleting both halves cannot downgrade it.
    # PILOT-039: a *present* policy file is checked too, even when it does not
    # parse into a requirement -- a malformed marker is fail-closed, never a
    # silent downgrade to optional/legacy.
    requirement_ok = True
    policy_present = requirement["policy_state"] != "missing"
    if required or policy_present:
        pairing = authority_requirement_errors(root, requirement)
        for error in pairing:
            requirement_ok = False
            add("authority requirement", False, error)
        if required and (file_state == "missing" or not event_present):
            missing = ("state/AUTHORITY.json" if file_state == "missing"
                       else "the AUTHORITY_SET ledger event")
            add("authority required", False,
                f"authority required but not configured: {missing} is missing "
                f"({AUTHORITY_POLICY_FILE} requires authority)")
            return {"status": "required_unconfigured", "checks": checks,
                    "errors": errors, "merge_authority": None,
                    "required": True}
        if (not required and policy_present and file_state == "missing"
                and not event_present):
            # A malformed policy with nothing configured behind it: the
            # requirement error above is the whole story, so the 037
            # "state file present"/"backed by ledger" pair would only duplicate
            # it under a misleading name.
            return {"status": "configured", "checks": checks,
                    "errors": errors, "merge_authority": None,
                    "required": False}

    # Legacy: the tower predates authority state and never required it.  Not
    # configured, not broken, and deliberately no ledger-chain check (old
    # towers must keep verifying).
    if (not required and not policy_present and file_state == "missing"
            and not event_present):
        add("authority state", True,
            "legacy: no state/AUTHORITY.json and no AUTHORITY_SET event")
        return {"status": "legacy", "checks": checks, "errors": errors,
                "merge_authority": None, "required": False}

    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    _, supervision_state = _read_json_object(
        root / "supervision" / "CURRENT_STATE.json")
    primary_state = primary_state if isinstance(primary_state, dict) else {}
    supervision_state = (supervision_state
                         if isinstance(supervision_state, dict) else {})
    owner = _state_owner_name(primary_state)
    primary_id = _state_nested_id(primary_state, "primary", "id")
    supervisor_id = _state_nested_id(supervision_state, "supervisor", "id")
    primary_tower_id = primary_state.get("tower_id", AUTHORITY_ABSENT)

    # The event is the authority, so its ledger chain must be intact before its
    # payload can be trusted.  This runs for every configured state, whatever
    # the envelope style, so a forged AUTHORITY_SET row cannot ride a legacy
    # envelope through the merge gate.
    if event_present:
        report = verify_ledger_file(root, "primary")
        if report["errors"]:
            add("primary ledger chain intact", False,
                f"primary ledger chain broken: {report['errors'][0]}")
        else:
            add("primary ledger chain intact", True, "ok")

    if file_state == "missing":
        add("authority state file present", False,
            "ledger/primary.jsonl has an AUTHORITY_SET event but "
            "state/AUTHORITY.json is missing")
    elif file_state == "unreadable":
        add("authority state file readable", False,
            "state/AUTHORITY.json is not a parseable JSON object")
    else:
        add("authority state file readable", True, AUTHORITY_STATE_FILE)
        add("authority schema is tower/authority-state@1",
            state.get("schema") == AUTHORITY_STATE_SCHEMA,
            f"schema {state.get('schema')!r}")

    if not event_present:
        add("authority state backed by ledger", False,
            "state/AUTHORITY.json exists but ledger/primary.jsonl has no "
            "AUTHORITY_SET event")
    elif not isinstance(payload_obj, dict):
        add("authority state backed by ledger", False,
            "the last AUTHORITY_SET carries no object payload")
    else:
        add("authority state backed by ledger", True,
            f"AUTHORITY_SET revision {payload.get('revision')}")

    if file_state == "ok":
        fields = authority_state_fields(state)
        type_errors = _authority_field_errors(fields, "file")
        add("authority field types", not type_errors,
            "; ".join(type_errors) or "ok")
        tower_errors: list[str] = []
        tower_id = state.get("tower_id", AUTHORITY_ABSENT)
        if not isinstance(tower_id, str) or not tower_id:
            tower_errors.append("file tower_id must be a non-empty string")
        if not isinstance(primary_tower_id, str) or not primary_tower_id:
            tower_errors.append(
                "primary/CURRENT_STATE.json tower_id must be a non-empty string")
        if not tower_errors and tower_id != primary_tower_id:
            tower_errors.append(
                f"file {tower_id!r} vs primary state {primary_tower_id!r}")
        add("authority tower_id matches primary state", not tower_errors,
            "; ".join(tower_errors) or "ok")
        add("authority owner matches primary state",
            fields["owner"] == owner,
            f"file {authority_display(fields['owner'])!r} vs primary state "
            f"{owner!r}")
        add("authority primary.id matches primary state",
            fields["primary_id"] == primary_id,
            f"file {authority_display(fields['primary_id'])!r} vs primary "
            f"state {primary_id!r}")
        add("authority supervision.id matches supervision state",
            fields["supervision_id"] == supervisor_id,
            f"file {authority_display(fields['supervision_id'])!r} vs "
            f"supervision state {supervisor_id!r}")
        add("merge authority differs from primary",
            fields["merge_authority"] != primary_id,
            f"merge authority {authority_display(fields['merge_authority'])!r} "
            f"vs primary {primary_id!r}")
        if not event_present or not isinstance(payload_obj, dict):
            add("authority file matches last AUTHORITY_SET", False,
                "no usable AUTHORITY_SET event to compare against")
        else:
            payload_fields = authority_payload_fields(payload)
            ledger_type_errors = _authority_field_errors(payload_fields,
                                                         "ledger")
            add("authority ledger payload types", not ledger_type_errors,
                "; ".join(ledger_type_errors) or "ok")
            mismatched = [field for field in AUTHORITY_STATE_FIELDS
                          if fields[field] != payload_fields[field]]
            add("authority file matches last AUTHORITY_SET",
                not mismatched,
                "ok" if not mismatched else
                "mismatch: " + _authority_mismatch_detail(
                    fields, payload_fields, mismatched))
        pinned = authority_display(fields["merge_authority"])
    else:
        pinned = authority_display(
            payload.get("merge_authority", AUTHORITY_ABSENT))

    # A required tower that reached this point has both halves of the marker
    # and a configured authority state: pin that in the verdict explicitly.
    if required and requirement_ok:
        add("authority requirement pinned", True,
            f"authority requirement pinned: {AUTHORITY_POLICY_FILE} + "
            f"{AUTHORITY_REQUIRED_EVENT} event")

    return {"status": "configured", "checks": checks, "errors": errors,
            "merge_authority": pinned, "required": required}


def cmd_authority_check(root: Path, args) -> None:
    result = authority_state_check(root)
    ok = not result["errors"]
    emit({"ok": ok, "status": result["status"],
          "requirement": "required" if result["required"] else "optional",
          "required": result["required"],
          "checks": result["checks"]},
         0 if ok else 2)


def cmd_authority_set(root: Path, args) -> None:
    """Register the merge authority: one file write plus one ledger event.

    Every identity check runs before any write, so a caller that is not the
    registered owner, or that names something other than the registered
    supervisor, leaves the tower untouched.  Re-running is the repair path for
    a half-write: whichever half is missing is rebuilt with a fresh revision.

    PILOT-039: the entire read-revision/validate/write-file/append-event
    section runs under ``state/.authority.lock``, so concurrent writers cannot
    reuse a revision or race the atomic ``.tmp`` replacement.  The authority
    lock is always taken before the ledger lock (inside ``append_ledger``).
    """
    with authority_lock(root):
        authority_set_locked(root, args)


def authority_set_locked(root: Path, args) -> None:
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    _, supervision_state = _read_json_object(
        root / "supervision" / "CURRENT_STATE.json")
    primary_state = primary_state if isinstance(primary_state, dict) else {}
    supervision_state = (supervision_state
                         if isinstance(supervision_state, dict) else {})
    owner = _state_owner_name(primary_state)
    primary_id = _state_nested_id(primary_state, "primary", "id")
    supervisor_id = _state_nested_id(supervision_state, "supervisor", "id")

    errors: list[str] = []
    if not owner:
        errors.append("primary/CURRENT_STATE.json has no owner.name")
    elif args.by != owner:
        errors.append(f"only the registered owner may set authority: "
                      f"--by {args.by!r} != owner {owner!r}")
    if not supervisor_id:
        errors.append("supervision/CURRENT_STATE.json has no supervisor.id")
    elif args.supervisor != supervisor_id:
        errors.append(f"--supervisor {args.supervisor!r} is not the "
                      f"registered supervisor {supervisor_id!r}")
    if args.supervisor == primary_id:
        errors.append(f"--supervisor {args.supervisor!r} must differ from "
                      f"primary.id {primary_id!r}")
    if not isinstance(args.decision, str) or not args.decision.strip():
        errors.append("--decision must be a non-empty string")
    if not isinstance(primary_state.get("tower_id"), str) or not \
            primary_state.get("tower_id"):
        errors.append("primary/CURRENT_STATE.json has no tower_id")
    if errors:
        fail(errors)

    revision = next_authority_revision(root)
    set_at = now()
    note = args.note or None
    state = {
        "schema": AUTHORITY_STATE_SCHEMA,
        "tower_id": primary_state.get("tower_id"),
        "owner": owner,
        "primary": {"id": primary_id},
        "supervision": {"id": supervisor_id},
        "merge_authority": args.supervisor,
        "revision": revision,
        "set_by": args.by,
        "decision": args.decision,
        "set_at": set_at,
    }
    payload = {
        "owner": owner,
        "primary_id": primary_id,
        "supervision_id": supervisor_id,
        "merge_authority": args.supervisor,
        "revision": revision,
        "set_by": args.by,
        "decision": args.decision,
        "set_at": set_at,
    }
    if note:
        state["note"] = note
        payload["note"] = note
    # File first, event second: the event is the authority, so a crash between
    # the two leaves "file without event" (unbacked), never a silent
    # configured state.  Re-running authority-set repairs either half.  A write
    # failure (state/AUTHORITY.json is a directory, the tree is not writable,
    # ...) must not append the event: that would make the write failure
    # authoritative.  It exits 2 with one JSON payload instead of a traceback.
    target = root / AUTHORITY_STATE_FILE
    try:
        jdump(target, state)
    except OSError as exc:
        residue = target.with_name(target.name + ".tmp")
        try:
            if residue.is_file():
                residue.unlink()
        except OSError:
            pass
        fail([f"cannot write {AUTHORITY_STATE_FILE}: {exc}"])
    # The state file is written but is NOT the authority: the event is.  A
    # ledger that cannot be appended to (``ledger/primary.jsonl`` is a
    # directory, a lock that never frees, ...) must exit 2 with one JSON
    # payload, never a traceback, and must leave the half-write visible as
    # ``authority_missing``/``unbacked`` so merge stays fail closed.  Re-running
    # authority-set repairs it once the ledger is writable again.
    try:
        append_ledger(root, AUTHORITY_SET_EVENT, "primary", payload)
    except (OSError, LedgerLockTimeout) as exc:
        fail([f"cannot append {AUTHORITY_SET_EVENT} to ledger/primary.jsonl: "
              f"{exc}",
              f"{AUTHORITY_STATE_FILE} was written but is unbacked; re-run "
              "authority-set once the ledger is writable"])
    emit({"ok": True, "path": AUTHORITY_STATE_FILE, "revision": revision,
          "merge_authority": args.supervisor})


def cmd_authority_require(root: Path, args) -> None:
    """Persist "this tower requires an authority state" (PILOT-038).

    The marker has two halves and both are required: the git-tracked
    ``shared/AUTHORITY_POLICY.json`` and one ``AUTHORITY_REQUIRED`` ledger
    event whose payload is isomorphic to that file.  Every identity check runs
    before any write, so a caller that is not the registered owner leaves the
    tower untouched.  A tower that already has both halves is idempotent:
    exit 0, ``already=true``, and no new event.  A tower with exactly one half
    is repaired (``repaired=true``) by writing only the missing side; a tower
    whose halves disagree is repaired from the authoritative event payload
    (``repaired=true``, ``already=false``), so a rewritten audit field cannot
    leave the requirement permanently broken.  The requested ``--decision`` is
    only used when neither half exists yet: an existing half is replayed
    verbatim, because the ledger event is the authority.

    A ledger append failure exits 2 with a single JSON payload and no
    traceback.  The policy file may already be written, which surfaces as
    "policy unbacked" -- exactly the fail-closed state we want: the requirement
    is visible but cannot be satisfied until the event exists.

    PILOT-039: the whole read-policy/validate/write-file/append-event section
    runs under ``state/.authority.lock`` (taken before the ledger lock), so a
    concurrent require cannot interleave the policy half with the event half.
    """
    with authority_lock(root):
        authority_require_locked(root, args)


def authority_require_locked(root: Path, args) -> None:
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    primary_state = primary_state if isinstance(primary_state, dict) else {}
    owner = _state_owner_name(primary_state)
    tower_id = primary_state.get("tower_id")

    errors: list[str] = []
    if not owner:
        errors.append("primary/CURRENT_STATE.json has no owner.name")
    elif args.by != owner:
        errors.append(f"only the registered owner may require authority: "
                      f"--by {args.by!r} != owner {owner!r}")
    if not isinstance(args.decision, str) or not args.decision.strip():
        errors.append("--decision must be a non-empty string")
    if not isinstance(tower_id, str) or not tower_id:
        errors.append("primary/CURRENT_STATE.json has no tower_id")
    if errors:
        fail(errors)

    requirement = authority_requirement(root)
    policy_required = requirement["policy_required"]
    event_present = requirement["event_present"]
    # PILOT-039: both halves present but not isomorphic is repairable, and must
    # be: the event is the authority, so re-running require rewrites the policy
    # file from the last event payload instead of leaving the tower permanently
    # mismatched (this is also the migration path for the real tower).
    mismatch = (authority_policy_mismatch(root, requirement)
                if policy_required and event_present else None)
    if policy_required and event_present and mismatch is None:
        # PILOT-040: the persisted decision is the authority here, so echo it
        # instead of the requested --decision.  A caller that asked for a
        # different value must see both, or the output would claim the tower
        # pinned a decision it never stored.  Nothing is written: the policy,
        # the event payload and the event count stay exactly as they were.
        persisted = requirement["policy"].get("decision")
        out = {"ok": True, "path": AUTHORITY_POLICY_FILE, "by": args.by,
               "decision": persisted, "required": True, "already": True,
               "repaired": False}
        if persisted != args.decision:
            out["requested_decision"] = args.decision
        emit(out)

    set_at = now()
    if policy_required and mismatch is None:
        # The policy half already mirrors what we want pinned: replay it
        # verbatim so the appended event stays isomorphic to the file.
        policy = dict(requirement["policy"])
    else:
        if policy_required or event_present:
            # Repair from the authoritative half: the last event payload when
            # one exists, otherwise the existing policy file (event missing).
            source = (requirement.get("event_payload") if event_present
                      else requirement.get("policy"))
            if not isinstance(source, dict):
                fail(["authority policy cannot be repaired: the existing "
                      "marker half is not a JSON object; rewrite it with "
                      "authority-require after fixing the ledger"])
            policy = dict(source)
            bad = [field for field in AUTHORITY_POLICY_FIELDS
                   if not _authority_policy_value_ok(
                       field, authority_policy_fields(policy)[field])]
            if bad:
                fail(["authority policy cannot be repaired from the existing "
                      f"half: invalid field(s) {', '.join(bad)}"])
        else:
            policy = _authority_policy_payload(primary_state, args.by,
                                               args.decision, set_at)
        target = root / AUTHORITY_POLICY_FILE
        try:
            jdump(target, policy)
        except OSError as exc:
            residue = target.with_name(target.name + ".tmp")
            try:
                if residue.is_file():
                    residue.unlink()
            except OSError:
                pass
            fail([f"cannot write {AUTHORITY_POLICY_FILE}: {exc}"])

    if not event_present:
        try:
            append_ledger(root, AUTHORITY_REQUIRED_EVENT, "primary",
                          dict(policy))
        except (OSError, LedgerLockTimeout) as exc:
            fail([f"cannot append {AUTHORITY_REQUIRED_EVENT} to "
                  f"ledger/primary.jsonl: {exc}",
                  f"{AUTHORITY_POLICY_FILE} was written but its ledger event "
                  "is missing; re-run authority-require once the ledger is "
                  "writable"])

    # PILOT-040: this branch either repaired a half from the authoritative side
    # or performed the first write.  In both cases ``policy`` is what was
    # actually stored, so its decision is echoed; only a repair can differ from
    # the requested value, and then the request is reported alongside it.
    persisted = policy.get("decision")
    out = {"ok": True, "path": AUTHORITY_POLICY_FILE,
           "by": policy.get("set_by"), "decision": persisted,
           "set_at": policy.get("set_at"), "required": True,
           "already": False, "repaired": True}
    if persisted != args.decision:
        out["requested_decision"] = args.decision
    emit(out)


def ledger_empty_guard(root: Path) -> list[str]:
    """PILOT-040: a 0-event supervision ledger may not shield history.

    036 established that an *existing* empty ledger is a valid empty chain, so
    a fresh tower still merges.  039 made a **missing** ledger fatal.  The
    remaining seam was truncation: ``truncate -s0 ledger/supervision.jsonl``
    keeps the file (039's presence check passes) and a legacy envelope plus its
    hand-written queue row then merged without one supervision event.  That is
    exactly the inconsistency ``state-verify`` already reports as
    ``envelope_unbacked`` / ``queue_unbacked``; the audit saw it, the merge
    gate did not.

    Only non-legacy towers are guarded: a tower with no authority state keeps
    its old (036/039) behaviour.  The guard also needs at least one supervision
    artifact (envelope file, queue entry, merge-ledger entry).  A configured or
    required tower with an empty ledger and *no* such artifact is fresh, has no
    history to be inconsistent with, and passes.  Returns flat error lines;
    callers fail closed on any non-empty list.
    """
    authority = authority_state_check(root)
    if authority["status"] == "legacy":
        return []
    if supervision_ledger_event_count(root) != 0:
        # ``None`` (missing/unreadable) is not this guard's business: 039 makes
        # absence fatal and verify-ledger owns unreadability.
        return []
    artifacts = supervision_artifacts(root)
    if not artifacts:
        return []
    ledger = root / "ledger" / LEDGER_FILES["supervision"]
    return [f"{EMPTY_SUPERVISION_LEDGER}: {rel(root, ledger)} has 0 events "
            f"while {', '.join(artifacts)} exist(s); a truncated supervision "
            "ledger cannot shield envelope/queue history "
            "(state-verify reports envelope_unbacked/queue_unbacked)"]
