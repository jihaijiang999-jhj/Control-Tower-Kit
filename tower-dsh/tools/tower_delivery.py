"""Delivery scope, evidence and completion backing."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from tower_common import (
    _norm_tower_rel, _read_json_object, allowed_repo_path, check_task_id,
    command_failure, emit, ensure_within, fail, git, git_ok, now, rel,
    repo_relative, resolve_input_within, sha256_file, status_path,
)
from tower_ledger import (
    LEDGER_FILES, _append_ledger_event_locked, append_ledger, ledger_lock,
    task_dir,
)
from tower_ledger_replay import ledger_events_in_seq_order, ledger_payloads_by_task
from tower_task import load_record, save_record, update_board
from tower_authority import _state_owner_name, authority_repo
from tower_shape import (
    DELIVER_SHAPE_SKIPPED, SHAPE_BASELINE_REL, load_shape_baseline,
    shape_debt_errors, shape_py_files, shape_scan,
)
from tower_dispatch import _dispatch_base_sha, deliver_dispatch_base_sha


def check_evidence(root: Path, record: dict) -> list[str]:
    errors: list[str] = []
    evidence = record.get("evidence") or []
    if not evidence:
        errors.append("no evidence recorded")
    for e in evidence:
        raw = e.get("path") or ""
        if not raw:
            errors.append(f"evidence missing: {e.get('path')}")
            continue
        # Evidence paths are recorded relative to the tower root.  Confining
        # them keeps a forged record from hashing an arbitrary host file while
        # still accepting in-root paths such as pilot/worktrees/...
        path = ensure_within(root, root / raw, label="evidence")
        if not path.exists():
            errors.append(f"evidence missing: {raw}")
            continue
        actual = sha256_file(path)
        if actual != e.get("sha256"):
            errors.append(f"evidence hash mismatch: {raw}")
    return errors


DELIVER_SCOPE_SKIPPED = "skipped (no git repo)"


COMPLETION_ADDED = "COMPLETION_ADDED"


COMPLETION_TASK_STATUSES = ("ready", "dispatched", "delivered", "rework")


COMPLETION_ENTRY_FIELDS = ("path", "by", "reason", "decision")


def completion_events(root: Path, task_id: str) -> list[dict]:
    """Payloads of the ``COMPLETION_ADDED`` events naming ``task_id``.

    Read-only.  Rows that are not JSON objects are ignored by
    :func:`ledger_events_in_seq_order`; a broken ledger is reported by
    ``state-verify`` / ``verify-ledger`` instead.
    """
    payloads: list[dict] = []
    for event in ledger_events_in_seq_order(root, "primary"):
        if event.get("type") != COMPLETION_ADDED:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("task") == task_id:
            payloads.append(payload)
    return payloads


def _completion_at_second(value):
    """An ISO timestamp truncated to whole seconds, else the raw string."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
            microsecond=0)
    except ValueError:
        return text


def _completion_field_differences(entry: dict, payload: dict,
                                  owner: str | None = None) -> list[str]:
    """Fields where a record completion entry disagrees with its event payload.

    ``path`` was already compared after :func:`_norm_tower_rel` normalisation
    by the caller, so only the textual/identity fields and ``at`` (same second)
    are compared here.  An empty half is a difference too: the delivery gate
    must reject a completion whose authority cannot be read back.
    """
    diffs: list[str] = []
    for field in COMPLETION_ENTRY_FIELDS + ("at",):
        value = entry.get(field)
        event_value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            diffs.append(f"record {field} is empty")
        elif not isinstance(event_value, str) or not event_value.strip():
            diffs.append(f"ledger {field} is empty")
        elif field == "at":
            if _completion_at_second(value) != _completion_at_second(event_value):
                diffs.append("at")
        elif field != "path" and value != event_value:
            diffs.append(field)
    if owner is not None and payload.get("by") != owner:
        diffs.append(f"by {payload.get('by')!r} is not owner {owner!r}")
    return diffs


def _completion_backing_entry_errors(entry: dict, path: str | None,
                                     path_error: str | None,
                                     event_paths: dict[str, list[dict]],
                                     owner: str | None) -> list[str]:
    """Errors for one diff-hit record entry against its ledger events."""
    if path_error:
        return [f"completion record does not match ledger event: {path_error}"]
    if not owner:
        return ["completion owner unknown: primary/CURRENT_STATE.json has no "
                "owner.name"]
    payloads = event_paths.get(path or "")
    if not payloads:
        return [f"completion not backed by {COMPLETION_ADDED}: {path}"]
    diffs: list[str] = []
    for payload in payloads:
        diffs = _completion_field_differences(entry, payload, owner)
        if not diffs:
            return []
    return [f"completion record does not match ledger event: {path} "
            f"({'; '.join(diffs)})"]


def _completion_event_paths(root: Path,
                            task_id: str) -> dict[str, list[dict]]:
    """``COMPLETION_ADDED`` payloads for one task, normalised-path keyed."""
    event_paths: dict[str, list[dict]] = {}
    for payload in ledger_payloads_by_task(root, COMPLETION_ADDED).get(task_id, []):
        path, error = _norm_tower_rel(root, payload.get("path"))
        if not error:
            event_paths.setdefault(path, []).append(payload)
    return event_paths


def _completion_entries_by_target(root: Path, rec: dict, used: list[str],
                                  worktree_rel: str,
                                  tower_rel: str) -> dict[str, list[dict]]:
    """Record completion entries keyed by the worktree path the diff uses."""
    entries_by_target: dict[str, list[dict]] = {}
    for entry in rec.get("completions") or []:
        if not isinstance(entry, dict):
            continue
        path, error = _norm_tower_rel(root, entry.get("path"))
        if error:
            continue
        target = allowed_repo_path(path, worktree_rel, tower_rel)
        if target in used:
            entries_by_target.setdefault(target, []).append(entry)
    return entries_by_target


def completion_backing_errors(root: Path, rec: dict,
                              used: list[str]) -> list[str]:
    """PILOT-043: every completion the diff actually hit must be backed.

    A ``record.completions`` entry alone grants nothing: for each mapped path
    in ``used`` (the worktree-relative completions the deliver diff touched)
    the primary ledger must hold a matching ``COMPLETION_ADDED`` for the same
    task+path, its ``by`` must be the registered owner, ``path``/``by``/
    ``reason``/``decision`` must be non-empty, and every field must agree with
    the record entry (``at`` at whole-second precision).  Read-only; any error
    is returned before ``deliver`` writes evidence or a DELIVER event.
    """
    if not used:
        return []
    worktree_rel = str(rec.get("worktree") or "").strip()
    repo = authority_repo(root)
    tower_rel = (repo_relative(repo, root) or "") if repo is not None else ""
    _, state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    owner = _state_owner_name(state) if isinstance(state, dict) else None
    event_paths = _completion_event_paths(root, str(rec.get("id") or ""))
    entries_by_target = _completion_entries_by_target(
        root, rec, used, worktree_rel, tower_rel)
    errors: list[str] = []
    for target in used:
        entries = entries_by_target.get(target)
        if not entries:
            errors.append(f"completion not backed by {COMPLETION_ADDED}: {target}")
            continue
        for entry in entries:
            path, error = _norm_tower_rel(root, entry.get("path"))
            errors += _completion_backing_entry_errors(
                entry, path, error, event_paths, owner)
    return errors


def completion_paths(rec: dict) -> list[str]:
    """Well-formed ``record.completions`` paths, in recorded order."""
    values: list[str] = []
    completions = rec.get("completions")
    for entry in completions if isinstance(completions, list) else []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path.strip():
            values.append(path)
    return values


def deliver_scope(root: Path, rec: dict) -> tuple[list[str], list[str], str | None, list[str]]:
    """Check the task worktree diff against the deliver allow-list.

    Returns ``(errors, scope_files, skipped_reason, completions_used)``:

    * ``skipped_reason`` is set only when the tower root is outside any git
      repository (fixtures / legacy towers), where a diff cannot be computed.
    * Every git failure is an *error* instead (fail closed): a worktree that
      cannot be inspected must not be delivered silently.
    * ``scope_files`` holds the changed paths as reported by the worktree
      repository (already relative to its root) when the check ran.
    * ``completions_used`` is the subset of the mapped ``record.completions``
      paths that the diff actually touched.

    The worktree must be the root of a linked worktree of the authority
    repository: a ``rev-parse`` success alone is not enough, because a nested
    checkout (a plain subdirectory of another repository) or a rewired
    ``.git`` still answers with *some* repository and can produce an empty
    diff.  Rename detection is disabled when collecting the diff: a rename of
    an out-of-scope file into an allowed path must show both the deleted and
    the added path, otherwise only the allowed target would be inspected.

    PILOT-042 extends the gate in two ways:

    * ``record.completions`` (owner-signed entries recorded by
      ``completion-add``) joins the allow-list through the same
      :func:`allowed_repo_path` mapping as ``allowed_paths``.  It never widens
      any other gate.
    * When ``record.dispatch.base_sha`` is recorded, the diff is taken from
      that anchored commit after proving it is an ancestor of HEAD.  Rewriting
      the local ``main`` ref therefore cannot empty the diff.  A legacy record
      without ``base_sha`` keeps the PILOT-041 ``merge-base main HEAD``
      baseline.

    The check runs before any evidence is copied, so a rejected delivery
    writes nothing.
    """
    repo = authority_repo(root)
    if repo is None:
        return [], [], DELIVER_SCOPE_SKIPPED, []
    worktree_rel = str(rec.get("worktree") or "").strip()
    if not worktree_rel:
        return ["worktree missing: (empty); scope check cannot run"], [], None, []
    worktree = ensure_within(root, root / worktree_rel, label="worktree")
    try:
        toplevel = git_ok(worktree, "rev-parse", "--show-toplevel")
    except RuntimeError as exc:
        return [f"worktree is not a git repository: {worktree_rel} ({exc})"], [], None, []
    if Path(toplevel).resolve() != worktree.resolve():
        return [f"worktree is not the repository root: {worktree_rel} "
                f"(toplevel: {toplevel})"], [], None, []
    try:
        repo_git_dir = Path(git_ok(repo, "rev-parse", "--absolute-git-dir")).resolve()
        worktree_git_dir = Path(
            git_ok(worktree, "rev-parse", "--absolute-git-dir")).resolve()
    except RuntimeError as exc:
        return [f"scope repository identity unavailable: {exc}"], [], None, []
    if (worktree_git_dir == repo_git_dir
            or repo_git_dir not in worktree_git_dir.parents):
        return [f"worktree is not a worktree of the tower repository: "
                f"{worktree_rel} (git dir: {worktree_git_dir.as_posix()})"], [], None, []
    base_sha = _dispatch_base_sha(rec)
    if base_sha is not None:
        # Fail closed on ANY non-zero status: a bad/unreadable object is as
        # untrustworthy as a commit that is not an ancestor of HEAD.
        ancestor = git(worktree, "merge-base", "--is-ancestor", base_sha, "HEAD")
        if ancestor.returncode != 0:
            return [f"scope baseline is not an ancestor of HEAD: {base_sha} "
                    f"({command_failure(ancestor)})"], [], None, []
        diff_range = f"{base_sha}..HEAD"
    else:
        try:
            merge_base = git_ok(worktree, "merge-base", "main", "HEAD")
        except RuntimeError as exc:
            return [f"scope baseline unavailable: merge-base main HEAD failed in "
                    f"{worktree_rel} ({exc})"], [], None, []
        diff_range = f"{merge_base}..HEAD"
    diff = git(worktree, "diff", "--name-only", "--no-renames", diff_range)
    if diff.returncode != 0:
        return [f"scope diff failed: git diff --no-renames {diff_range} "
                f"({command_failure(diff)})"], [], None, []
    changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    status = git(worktree, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        return [f"scope status failed: git status ({command_failure(status)})"], [], None, []
    # Untracked files are deliberately not inspected (``scratch/`` is allowed);
    # tracked-but-uncommitted changes are, because they would ship outside the
    # reviewed diff.
    errors = [f"uncommitted tracked change: {status_path(line)}"
              for line in status.stdout.splitlines() if line.strip()]
    tower_rel = repo_relative(repo, root) or ""
    allowed = {
        mapped for mapped in
        (allowed_repo_path(entry, worktree_rel, tower_rel)
         for entry in (rec.get("allowed_paths") or []))
        if mapped
    }
    # PILOT-042: owner-signed completions join the allow-list, mapped exactly
    # like allowed_paths so worktree paths and elsewhere-in-tower paths both
    # resolve to the worktree-relative spelling the diff uses.
    completion_allowed = {
        mapped for mapped in
        (allowed_repo_path(entry, worktree_rel, tower_rel)
         for entry in completion_paths(rec))
        if mapped
    }
    completions_used = sorted(path for path in changed
                              if path in completion_allowed)
    for path in changed:
        if path not in allowed and path not in completion_allowed:
            errors.append(f"out of scope change: {path} (not in allowed_paths)")
    return errors, changed, None, completions_used


def deliver_shape_gate(root: Path, rec: dict) -> tuple[list[str], str | None]:
    """Run the tower root's shape baseline over the worktree's tower copy.

    Returns ``(errors, skipped)``.  ``skipped`` is :data:`DELIVER_SHAPE_SKIPPED`
    only when the worktree has no ``tools/*.py`` (nothing to scan) or when it is
    a pre-shape tower (no ``state/`` directory on either side).  Otherwise the
    baseline is the **tower root's** copy and the worktree must carry it
    byte-for-byte, so a task cannot silence the gate by editing or deleting its
    own baseline.  Every error is returned before evidence is copied.
    """
    repo = authority_repo(root)
    worktree_rel = str(rec.get("worktree") or "").strip()
    if repo is None or not worktree_rel:
        return [], DELIVER_SHAPE_SKIPPED
    tower_rel = repo_relative(repo, root) or ""
    shape_root = root / worktree_rel
    if tower_rel:
        shape_root = shape_root / tower_rel
    if not shape_py_files(shape_root):
        return [], DELIVER_SHAPE_SKIPPED
    tower_baseline = root / SHAPE_BASELINE_REL
    worktree_baseline = shape_root / SHAPE_BASELINE_REL
    if not (root / "state").is_dir() and not (shape_root / "state").is_dir():
        return [], DELIVER_SHAPE_SKIPPED
    errors = shape_baseline_guard(tower_baseline, worktree_baseline)
    if errors:
        return errors, None
    current = shape_scan(shape_root)
    return shape_debt_errors(current, load_shape_baseline(tower_baseline)), None


def shape_baseline_guard(tower_baseline: Path, worktree_baseline: Path) -> list[str]:
    """The deliver baseline is the tower root's copy, byte-for-byte.

    A task may not silence the ratchet by editing or deleting its own baseline:
    the baseline is frozen on main, and changing it needs its own
    baseline-refresh card.
    """
    if not tower_baseline.is_file():
        return [f"shape baseline missing: {SHAPE_BASELINE_REL} in the tower root; "
                "a baseline refresh needs its own card"]
    if not worktree_baseline.is_file():
        return [f"shape baseline missing in worktree: {SHAPE_BASELINE_REL}; "
                "it must match the tower root (baseline refresh needs its own card)"]
    if worktree_baseline.read_bytes() != tower_baseline.read_bytes():
        return [f"shape baseline modified in worktree: {SHAPE_BASELINE_REL}; "
                "it must match the tower root byte-for-byte (baseline refresh "
                "needs its own card)"]
    return []


def collect_delivery_evidence(root: Path, task_id: str, rec: dict,
                              values: list[str]) -> None:
    """Copy each evidence file into ``tasks/<id>/evidence`` and renumber ids."""
    evdir = task_dir(root, task_id) / "evidence"
    evdir.mkdir(parents=True, exist_ok=True)
    existing = {e.get("path") for e in rec.get("evidence", [])}
    for value in values:
        src = resolve_input_within(root, value, "evidence")
        if not src.exists() or not src.is_file():
            fail([f"evidence not found: {value}"])
        dest = evdir / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        digest = sha256_file(dest)
        relpath = rel(root, dest)
        if relpath in existing:
            rec["evidence"] = [e for e in rec["evidence"] if e.get("path") != relpath]
        rec.setdefault("evidence", []).append({
            "path": relpath, "sha256": digest, "bytes": dest.stat().st_size, "at": now(),
        })
        existing.add(relpath)
    # A re-delivery replaces the entry for the same path before appending, so
    # the list length does not grow.  Numbering after the loop (rather than
    # from the current length while appending) keeps ids contiguous, unique
    # and in list order; it also repairs records written by the old scheme.
    for index, entry in enumerate(rec.get("evidence", []), start=1):
        entry["id"] = f"E-{index:03d}"


def write_delivery_md(root: Path, task_id: str, rec: dict) -> None:
    """Render ``DELIVERY.md`` from the record's evidence list."""
    lines = [f"# {rec['id']} — Delivery", "", f"- Status: `delivered`",
             f"- Executor: `{rec.get('executor')}`",
             f"- Worktree: `{rec.get('worktree')}`", "",
             "## Evidence", "", "| ID | Path | SHA-256 | Bytes |", "|---|---|---|---|"]
    for e in rec["evidence"]:
        lines.append(f"| {e['id']} | `{e['path']}` | `{e['sha256']}` | {e['bytes']} |")
    (task_dir(root, task_id) / "DELIVERY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def delivery_gate_fields(scope_skipped, scope_files, scope_completions,
                         shape_skipped) -> dict:
    """Scope/shape gate status block appended to a delivery result."""
    scope_checked = scope_skipped is None
    shape_checked = shape_skipped is None
    return {
        "scope_check": "checked" if scope_checked else scope_skipped,
        "scope_checked": scope_checked,
        "scope_files": scope_files if scope_checked else [],
        "scope_completions": scope_completions if scope_checked else [],
        "shape_check": "checked" if shape_checked else shape_skipped,
        "shape_checked": shape_checked,
    }


def cmd_deliver(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in ("dispatched", "delivered", "rework"):
        fail([f"task status {rec.get('status')} cannot deliver"])
    # PILOT-041: gate the worktree diff against allowed_paths *before* any
    # evidence is copied, so a rejected delivery leaves the record and the
    # evidence directory untouched.  PILOT-042 lets recorded completions join
    # that allow-list and reports the ones the diff actually used.
    # PILOT-043 R1: the DISPATCH ledger event, not the mutable record, fixes the
    # diff base.  A record value changed to HEAD (and later restored) cannot
    # empty the diff; a disagreement aborts before the diff is computed.
    event_base_sha = deliver_dispatch_base_sha(root, rec)
    if event_base_sha is not None and isinstance(rec.get("dispatch"), dict):
        rec["dispatch"]["base_sha"] = event_base_sha
    scope_errors, scope_files, scope_skipped, scope_completions = deliver_scope(root, rec)
    if scope_errors:
        fail(scope_errors)
    # PILOT-043: the record half is not authority.  Each completion the diff
    # actually used must be backed by a matching COMPLETION_ADDED event, signed
    # by the owner, before a single evidence byte or DELIVER event is written.
    completion_errors = completion_backing_errors(root, rec, scope_completions)
    if completion_errors:
        fail(completion_errors)
    # PILOT-044: the same no-writes-before-the-gate rule now covers shape -- the
    # worktree's own ratchet runs before the first evidence copy.
    shape_errors, shape_skipped = deliver_shape_gate(root, rec)
    if shape_errors:
        fail(shape_errors, shape_check="failed", shape_checked=True)
    collect_delivery_evidence(root, args.task, rec, args.evidence)
    rec["status"] = "delivered"
    rec["delivered_at"] = now()
    rec["next"] = "等待独立 reviewer"
    save_record(root, rec)
    update_board(root, rec)
    write_delivery_md(root, args.task, rec)
    append_ledger(root, "DELIVER", "executor" if rec.get("executor") else "primary",
                  {"task": args.task, "evidence": len(rec["evidence"])})
    result = {"ok": True, "task": args.task, "status": rec["status"],
              "evidence": len(rec["evidence"])}
    result.update(delivery_gate_fields(scope_skipped, scope_files,
                                       scope_completions, shape_skipped))
    emit(result)


def cmd_completion_add(root: Path, args) -> None:
    """Record one owner-signed completion (record half + ledger half).

    A completion authorises one tower-root-relative path for a task whose
    frozen spec did not list it.  It is written twice, like every other
    control-plane fact: ``record.completions`` (the working copy) and one
    ``COMPLETION_ADDED`` event in ``ledger/primary.jsonl`` (the authority).
    Delivery folds the completions into its allow-list; no other gate reads
    them.

    Every validation runs before the first write, so a non-owner caller, an
    empty reason/decision or a rejected path leaves the tower byte-identical.
    The read-decide-write section then runs under the ledger lock, which makes
    the pair idempotent: both halves present is ``already=true`` with no
    duplicate event, and re-running repairs exactly the missing half with
    ``repaired=true`` (the event half is authoritative, so "event only" must
    not append a second event).
    """
    tid = check_task_id(args.task)
    rec = load_record(root, tid)
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    primary_state = primary_state if isinstance(primary_state, dict) else {}
    owner = _state_owner_name(primary_state)
    errors: list[str] = []
    if not owner:
        errors.append("primary/CURRENT_STATE.json has no owner.name")
    elif args.by != owner:
        errors.append(f"only the registered owner may record a completion: "
                      f"--by {args.by!r} != owner {owner!r}")
    reason = args.reason.strip() if isinstance(args.reason, str) else ""
    if not reason:
        errors.append("--reason must be a non-empty string")
    decision = args.decision.strip() if isinstance(args.decision, str) else ""
    if not decision:
        errors.append("--decision must be a non-empty string")
    path, path_error = _norm_tower_rel(root, args.path)
    if path_error:
        errors.append(path_error)
    if rec.get("status") not in COMPLETION_TASK_STATUSES:
        errors.append(f"task status {rec.get('status')} cannot record a "
                      f"completion (allowed: "
                      f"{', '.join(COMPLETION_TASK_STATUSES)})")
    if errors:
        fail(errors)
    assert path is not None
    at = now()
    entry = {"task": tid, "path": path, "by": owner, "reason": reason,
             "decision": decision, "at": at}
    with ledger_lock(root):
        # Re-read inside the critical section: the status may have changed and
        # the other half may exist already.
        current = load_record(root, tid)
        if current.get("status") not in COMPLETION_TASK_STATUSES:
            fail([f"task status {current.get('status')} cannot record a "
                  f"completion (allowed: "
                  f"{', '.join(COMPLETION_TASK_STATUSES)})"])
        completions = current.get("completions")
        completions = completions if isinstance(completions, list) else []
        record_entries = [item for item in completions if isinstance(item, dict)]
        existing_entry = next(
            (item for item in record_entries if item.get("path") == path), None)
        events = completion_events(root, tid)
        existing_event = next(
            (payload for payload in events if payload.get("path") == path), None)
        if existing_event is not None and existing_entry is not None:
            emit({"ok": True, "task": tid, "path": path, "already": True,
                  "repaired": False, "event": COMPLETION_ADDED,
                  "events": len(events), "completions": len(completions),
                  "entry": existing_entry}, 0)
        if existing_event is not None:
            # Event without record: rebuild the record half from the event so
            # the two stay isomorphic; the event count must not change.
            payload = existing_event
            repaired = {
                "task": tid, "path": path, "by": payload.get("by"),
                "reason": payload.get("reason"),
                "decision": payload.get("decision"), "at": payload.get("at"),
            }
            completions.append(repaired)
            current["completions"] = completions
            save_record(root, current)
            emit({"ok": True, "task": tid, "path": path, "already": False,
                  "repaired": True, "event": COMPLETION_ADDED,
                  "events": len(events), "completions": len(completions),
                  "entry": repaired}, 0)
        if existing_entry is not None:
            # Record without event: the record is not the authority, so append
            # the backing event from the recorded entry (record unchanged).
            def _text(key: str, fallback: str) -> str:
                value = existing_entry.get(key)
                return value.strip() if isinstance(value, str) and value.strip() \
                    else fallback
            payload = {
                "task": tid, "path": path,
                "by": _text("by", owner),
                "reason": _text("reason", reason),
                "decision": _text("decision", decision),
                "at": _text("at", at),
            }
            _append_ledger_event_locked(
                root, LEDGER_FILES["primary"], COMPLETION_ADDED, "primary", payload)
            emit({"ok": True, "task": tid, "path": path, "already": False,
                  "repaired": True, "event": COMPLETION_ADDED,
                  "events": len(events) + 1, "completions": len(completions),
                  "entry": existing_entry}, 0)
        _append_ledger_event_locked(
            root, LEDGER_FILES["primary"], COMPLETION_ADDED, "primary", entry)
        completions.append(entry)
        current["completions"] = completions
        save_record(root, current)
        emit({"ok": True, "task": tid, "path": path, "already": False,
              "repaired": False, "event": COMPLETION_ADDED,
              "events": len(events) + 1, "completions": len(completions),
              "entry": entry}, 0)
