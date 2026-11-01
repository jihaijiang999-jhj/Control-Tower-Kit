"""Post-merge verification, status/handoff lifecycle, acceptance."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from tower_common import (
    check_package_id, emit, fail, git, jdump, jload, now, rel, resolve_repository,
    working_tree_state,
)
from tower_ledger import (
    append_ledger, append_supervision_ledger, close_task_id, ledger_rows,
    parse_ledger_row, task_dir,
)
from tower_task import (
    ACCEPTANCE_ID_RE, ACCEPTANCE_JSON, ACCEPTANCE_KINDS, ACCEPTANCE_LEGACY_MAX,
    ACCEPTANCE_SCHEMA, ACCEPTANCE_STATUSES, acceptance_json_path,
    acceptance_md_path, load_board, load_record, save_record, update_board,
    write_acceptance,
)
from tower_command import campaign_relpaths
from tower_authority import authority_drift
from tower_authority_cmd import authority_state_check
from tower_campaign import campaign_check_report, with_position
from tower_delivery import check_evidence
from tower_envelope import load_queue, load_supervision, save_queue
from tower_merge import write_task_merge_record
from tower_arch import ARCH_GATES_REL
from tower_arch_check import arch_check_payload


def cmd_accept(root: Path, args) -> None:
    """Owner accept (PILOT-059 adds the A/M gate; see ``accept_card``)."""
    accept_card(root, args)


def cmd_close(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") != "accepted":
        fail([f"task status {rec.get('status')} cannot close"])
    tdir = task_dir(root, args.task)
    errors: list[str] = []
    if not (tdir / "TASK.md").exists():
        errors.append("TASK.md missing; cannot close a task without its task card")
    errors += check_evidence(root, rec)
    if errors:
        fail(errors)
    closeout = tdir / "CLOSEOUT.md"
    merge_ref = f"tasks/{rec['id']}/MERGE.md"
    next_text = ("merge/handoff decision (owner gate) — see "
                 f"supervision/MERGE_QUEUE.json and {merge_ref}")
    lines = [f"# {rec['id']} — Closeout", "", f"- Status: `closed`",
             f"- Executor: `{rec.get('executor')}`",
             f"- Reviewer: `{(rec.get('review') or {}).get('reviewer')}`",
             f"- Decision: `{rec.get('decision', {}).get('id')}`",
             "- Merge: see supervision/MERGE_QUEUE.json and "
             f"{merge_ref} (owner gate)", "",
             "## Evidence", ""]
    lines += [f"- `{e['path']}` `{e['sha256']}`" for e in rec.get("evidence", [])]
    lines += ["", "## Next", "", next_text]
    closeout.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec["status"] = "closed"
    rec["closeout"] = {"path": rel(root, closeout), "at": now()}
    rec["next"] = next_text
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "CLOSEOUT", "primary", {"task": args.task, "closeout": rel(root, closeout)})
    close_task_id(root, rec)
    emit(with_position(root, {"ok": True, "task": args.task, "status": rec["status"],
          "closeout": rel(root, closeout)}))


def acceptance_item_errors(items) -> list[str]:
    """Structural errors for an acceptance item list; empty means valid."""
    if not isinstance(items, list):
        return ["acceptance items must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"acceptance item {index} must be an object")
            continue
        item_id = str(item.get("id") or "")
        if not ACCEPTANCE_ID_RE.match(item_id) or ".." in item_id:
            errors.append(f"acceptance item {index} has invalid id: {item_id!r}")
        elif item_id in seen:
            errors.append(f"acceptance id duplicated: {item_id}")
        seen.add(item_id)
        if item.get("kind") not in ACCEPTANCE_KINDS:
            errors.append(f"acceptance {item_id} kind must be auto | manual")
        if item.get("status") not in ACCEPTANCE_STATUSES:
            errors.append(f"acceptance {item_id} status must be pending | passed | failed")
        if not isinstance(item.get("note", ""), str):
            errors.append(f"acceptance {item_id} note must be a string")
    return errors


def load_acceptance(root: Path, tid: str) -> list[dict] | None:
    """Read one card's acceptance list; ``None`` when the file is absent."""
    path = acceptance_json_path(root, tid)
    if not path.exists():
        return None
    try:
        data = jload(path)
    except (OSError, ValueError) as exc:
        fail([f"{ACCEPTANCE_JSON} unreadable: {exc}"])
    if not isinstance(data, dict) or data.get("schema") != ACCEPTANCE_SCHEMA:
        fail([f"{ACCEPTANCE_JSON} schema must be {ACCEPTANCE_SCHEMA}"])
    items = data.get("items")
    errors = acceptance_item_errors(items)
    if errors:
        fail(errors)
    return items


def acceptance_legacy_ok(rec: dict) -> bool:
    """True for cards that predate PILOT-059 (no list, never retrofitted).

    A numeric id up to ``ACCEPTANCE_LEGACY_MAX`` is legacy by construction.
    Everything newer must carry ``ACCEPTANCE.json``; a missing or malformed
    ``created_at`` is not an exemption.
    """
    match = re.search(r"(\d+)$", str(rec.get("id") or ""))
    return bool(match and int(match.group(1)) <= ACCEPTANCE_LEGACY_MAX)


def acceptance_gate_errors(root: Path, rec: dict, args) -> list[str]:
    """The A/M gate: auto all passed, nothing failed, manual pending by flag."""
    tid = str(rec.get("id") or getattr(args, "task", ""))
    items = load_acceptance(root, tid)
    if items is None:
        if acceptance_legacy_ok(rec):
            return []
        return [f"task {tid} has no {ACCEPTANCE_JSON}; only cards up to "
                f"PILOT-{ACCEPTANCE_LEGACY_MAX:03d} may omit it"]
    allowed = bool(getattr(args, "allow_manual_pending", False))
    errors: list[str] = []
    for item in items:
        label = f"acceptance {item['id']}"
        if item["status"] == "failed":
            errors.append(f"{label} is failed")
        elif item["kind"] == "auto" and item["status"] != "passed":
            errors.append(f"{label} is auto {item['status']}; auto items must be passed")
        elif item["status"] == "pending":
            if not allowed:
                errors.append(f"{label} is manual pending; "
                              "pass --allow-manual-pending")
            elif not str(item.get("note") or "").strip():
                errors.append(f"{label} is manual pending without a note")
    return errors


def cmd_acceptance_add(root: Path, args) -> None:
    """Add or update one acceptance item, keeping JSON and Markdown in sync."""
    rec = load_record(root, args.task)
    item_id = str(args.id or "").strip()
    if not ACCEPTANCE_ID_RE.match(item_id) or ".." in item_id:
        fail([f"invalid acceptance id: {item_id!r}"])
    items = load_acceptance(root, rec["id"]) or []
    existing = next((item for item in items if item["id"] == item_id), None)
    if existing is not None and existing.get("kind") != args.kind:
        fail([f"acceptance {item_id} kind is {existing.get('kind')}; "
              "kind cannot change"])
    if existing is not None and not args.replace:
        fail([f"acceptance id already exists: {item_id}; "
              "pass --replace to update it"])
    note = str(args.note or "")
    if existing is None:
        items.append({"id": item_id, "kind": args.kind,
                      "status": args.status, "note": note})
    else:
        existing["status"] = args.status
        existing["note"] = note
    write_acceptance(root, rec["id"], items)
    emit({"ok": True, "task": rec["id"], "id": item_id, "kind": args.kind,
          "status": args.status, "replaced": existing is not None,
          "acceptance_json": rel(root, acceptance_json_path(root, rec["id"])),
          "acceptance_md": rel(root, acceptance_md_path(root, rec["id"]))})


def accept_card(root: Path, args) -> None:
    """The accept checks, plus the PILOT-059 A/M gate before ACCEPT is written."""
    rec = load_record(root, args.task)
    review = rec.get("review") or {}
    if review.get("verdict") != "PASS":
        fail(["cannot accept without PASS checkback"])
    if rec.get("status") not in ("reviewed", "accepted"):
        fail([f"task status {rec.get('status')} cannot accept"])
    evidence_errors = check_evidence(root, rec)
    if evidence_errors:
        fail(evidence_errors)
    acceptance_errors = acceptance_gate_errors(root, rec, args)
    if acceptance_errors:
        fail(acceptance_errors)
    rec["decision"] = {"id": args.decision, "actor": "owner",
                       "text": args.note or "owner authorized pilot acceptance",
                       "at": now()}
    rec["status"] = "accepted"
    rec["accepted_at"] = now()
    rec["next"] = "closeout"
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "ACCEPT", "primary",
                  {"task": args.task, "decision": args.decision})
    emit({"ok": True, "task": args.task, "status": rec["status"],
          "decision": args.decision})


def cmd_supervision_init(root: Path, args) -> None:
    for d in ["supervision/envelopes", "supervision/reviews", "supervision/outbox/corrections",
              "supervision/registries", "ledger"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    state_path = root / "supervision" / "CURRENT_STATE.json"
    if not state_path.exists():
        jdump(state_path, {
            "schema": "tower/supervision-state@1",
            "tower_id": "tower-dsh",
            "role": "supervision",
            "phase": "PHASE_2_ACTIVE",
            "supervisor": {"id": "sup-phase2-pilot", "session": "phase2-pilot"},
            "next_action": "等待第一个合并信封",
            "updated_at": now(),
        })
    queue_path = root / "supervision" / "MERGE_QUEUE.json"
    if not queue_path.exists():
        jdump(queue_path, {"schema": "tower/merge-queue@1", "entries": [], "updated_at": now()})
    ledger = root / "ledger" / "supervision.jsonl"
    if not ledger.exists():
        ledger.touch()
    append_supervision_ledger(root, "SUPERVISION_INIT", "supervision", {"root": str(root)})
    emit({"ok": True, "state": rel(root, state_path), "queue": rel(root, queue_path),
          "ledger": rel(root, ledger)})


TEST_COUNT_RE = re.compile(r"Ran (\d+) tests?\b")


def parse_test_count(stdout: str | None, stderr: str | None) -> int | None:
    """Last ``Ran N tests`` count in the combined child output, or None."""
    output = f"{stdout or ''}\n{stderr or ''}"
    matches = TEST_COUNT_RE.findall(output)
    if not matches:
        return None
    return int(matches[-1])


def run_test_suite(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a test-suite child process with the tower's pinned env contract.

    Read-only: the child inherits ``os.environ`` with UTF-8 stdio forced and
    bytecode writing disabled so the verified tree stays clean.
    """
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=child_env,
    )


def max_verified_tower_tests(root: Path) -> int | None:
    """Highest tower count ever verified in the supervision ledger.

    Only ``POST_MERGE_VERIFIED`` events carry a verified count.  The ledger is
    append-only and hash-chained, but this reader is deliberately forgiving:
    broken (non-JSON / non-object) rows are skipped, as are counts that are not
    plain non-negative integers (``true`` and ``"10"`` are not counts).  The
    result is the maximum over every valid event, so an older, larger count is
    never masked by a later, smaller one.  ``None`` means the ledger has no
    such event yet (a legacy tower), which keeps the monotonic gate off.
    """
    highest = None
    path = root / "ledger" / "supervision.jsonl"
    for raw_row in ledger_rows(path):
        event = parse_ledger_row(raw_row)
        if event is None or event.get("type") != "POST_MERGE_VERIFIED":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        count = payload.get("tower_tests_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            continue
        if highest is None or count > highest:
            highest = count
    return highest


def valid_baseline(value) -> bool:
    """True for a positive integer count baseline (``bool`` is not a count)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def wiring_checks(root: Path) -> list[dict]:
    """PILOT-050 post-merge gates, added only when their input exists.

    A legacy tower without ``command/campaigns/*.md`` or ``arch/GATES.json``
    keeps the pre-050 check list untouched; a tower that has them cannot reach
    ``POST_MERGE_VERIFIED`` while campaign-check or arch-check is red.
    """
    checks: list[dict] = []
    if campaign_relpaths(root):
        report = campaign_check_report(root, False)
        detail = f"{len(report['errors'])} errors, {len(report['warnings'])} warnings"
        checks.append({"name": "campaign-check", "ok": report["ok"], "detail": detail})
    if (root / ARCH_GATES_REL).is_file():
        report = arch_check_payload(root)
        checks.append({"name": "arch-check", "ok": report["ok"],
                       "detail": f"{len(report['errors'])} findings"})
    return checks


def cmd_post_merge(root: Path, args) -> None:
    envelope_id = check_package_id(args.envelope, "envelope")
    env_path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    status = env.get("status")
    if status == "POST_MERGE_VERIFIED":
        fail([f"envelope {args.envelope} is already POST_MERGE_VERIFIED"])
    if status not in ("MERGED", "CORRECTION_REQUIRED"):
        # CORRECTION_REQUIRED is retryable: a failed post-merge must be able to
        # re-run after the correction instead of deadlocking the envelope.
        fail([
            f"envelope status {status} is not MERGED or CORRECTION_REQUIRED; "
            "post-merge only runs after a successful merge"
        ])
    repo = resolve_repository(root, env.get("repository"))
    base = env.get("base", "main")
    a = env.get("implementation_head_sha")
    envelope_path = env.get("envelope_path")
    tests = run_test_suite(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        repo)
    tests_count = parse_test_count(tests.stdout, tests.stderr)
    baseline = env.get("tests_baseline")
    baseline_ok = valid_baseline(baseline)
    count_label = tests_count if tests_count is not None else "unknown"
    if baseline_ok:
        count_check = {
            "name": "tests count >= baseline",
            "ok": tests_count is not None and tests_count >= baseline,
            "detail": f"ran {count_label}, baseline {baseline}",
        }
    else:
        count_check = {
            "name": "tests count present",
            "ok": tests_count is not None and tests_count >= 1,
            "detail": f"ran {count_label}, baseline not set",
        }
    # Opt-in second count gate for the authoritative tower suite one level down
    # (``tools/tests``).  The root wrapper only asserts its own -- much smaller
    # -- suite, so a legacy envelope without ``tower_tests_baseline`` keeps the
    # old behaviour: the tower suite is neither run nor counted.  The tower
    # root is the cwd because ``tools/run_tests.py`` lives inside it; the
    # runner points TMP/TEMP/TMPDIR at a repo-local sandbox so this gate also
    # works in a restricted sandbox where ``%TEMP%`` ACLs are unusable.
    tower_baseline = env.get("tower_tests_baseline")
    tower_baseline_ok = valid_baseline(tower_baseline)
    # Opt-in monotonic-count gate: compare the declared baseline with the
    # highest count the append-only ledger already verified.  A legacy tower
    # (no verified event yet) has no anchor and keeps the old behaviour.
    anchor = max_verified_tower_tests(root) if tower_baseline_ok else None
    tower_count = None
    tower_check = None
    if tower_baseline_ok:
        runner = root / "tools" / "run_tests.py"
        if runner.is_file():
            tower_argv = [sys.executable, "-B", "tools/run_tests.py"]
        else:
            # A minimal fixture (or a legacy tower root) may vendor only
            # ``tools/tests``.  Fall back to plain discovery there so the gate
            # still measures that suite instead of failing on a missing file;
            # the real tower always ships the runner.
            tower_argv = [sys.executable, "-B", "-m", "unittest", "discover",
                          "-s", "tools/tests", "-v"]
        tower_tests = run_test_suite(tower_argv, root)
        tower_count = parse_test_count(tower_tests.stdout, tower_tests.stderr)
        tower_check = {
            "name": "tower tests count >= baseline",
            "ok": (tower_tests.returncode == 0 and tower_count is not None
                   and tower_count >= tower_baseline),
            "detail": (f"exit {tower_tests.returncode}, "
                       f"ran {tower_count or 'unknown'}, "
                       f"baseline {tower_baseline}"),
        }
    # The clean check runs before the review file is written, and it ignores
    # the state directories towerctl itself owns.  Both parts matter: the tower
    # root may live inside the verified repository, so writing the review first
    # (or counting it as dirt) made every post-merge fail its own gate.
    dirty, tool_owned = working_tree_state(root, repo)
    clean = not dirty
    reviews = root / "supervision" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    review_file = reviews / f"{args.envelope}-post-merge.txt"
    review_file.write_text(
        f"# {args.envelope} post-merge verification\n\n"
        f"- base: {base}\n- implementation: {a}\n- merge_commit: {env.get('merge_commit')}\n"
        f"- result: {args.result}\n- working_tree_clean: {clean}\n"
        f"- tool_owned_paths_ignored: {tool_owned}\n"
        f"- test_exit: {tests.returncode}\n"
        f"- tests_count: {count_label}\n"
        f"- tests_baseline: {baseline if baseline_ok else 'not set'}\n"
        f"- tower_tests_count: "
        f"{tower_count if tower_count is not None else 'unknown'}\n"
        f"- tower_tests_baseline: "
        f"{tower_baseline if tower_baseline_ok else 'not set'}\n\n"
        f"## Test output\n\n"
        f"{tests.stdout}\n{tests.stderr}\n", encoding="utf-8")
    checks = [
        {"name": "post-merge tests pass", "ok": tests.returncode == 0,
         "detail": f"exit {tests.returncode}"},
        count_check,
    ]
    if tower_check is not None:
        checks.append(tower_check)
    if tower_baseline_ok and anchor is not None:
        # A verified count is a floor: a later envelope may raise the declared
        # baseline, or keep it, but never declare it below what already passed.
        checks.append({
            "name": "tower baseline >= last verified",
            "ok": tower_baseline >= anchor,
            "detail": f"baseline {tower_baseline}, last verified {anchor}",
        })
    checks += [
        {"name": "implementation is ancestor of base",
         "ok": git(repo, "merge-base", "--is-ancestor", a, base).returncode == 0,
         "detail": f"{a}..{base}"},
        {"name": "envelope file exists on base",
         "ok": git(repo, "cat-file", "-e", f"{base}:{envelope_path}").returncode == 0,
         "detail": f"{base}:{envelope_path}"},
        {"name": "working tree clean", "ok": clean,
         "detail": (f"dirty={dirty}" if dirty else "clean")
         + (f"; ignored tool-owned: {tool_owned}" if tool_owned else "")},
    ]
    checks += wiring_checks(root)
    ok = args.result == "PASS" and all(c["ok"] for c in checks)
    env["tests_count"] = tests_count
    if tower_baseline_ok:
        # Written on both the verified and the failed path; a legacy envelope
        # that never ran the tower gate keeps the key absent.
        env["tower_tests_count"] = tower_count
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == args.envelope), None)
    if ok:
        env.update({"status": "POST_MERGE_VERIFIED", "post_merge_at": now(),
                    "post_merge_note": args.note or ""})
        jdump(env_path, env)
        if entry is not None:
            entry["status"] = "POST_MERGE_VERIFIED"
            save_queue(root, queue)
        merge_record = write_task_merge_record(root, env, envelope_id, checks)
        append_supervision_ledger(root, "POST_MERGE_VERIFIED", "supervision",
                                  {"envelope": args.envelope,
                                   "tests_count": tests_count,
                                   "tower_tests_count": tower_count,
                                   "checks": checks,
                                   "merge_record": rel(root, merge_record)
                                   if merge_record is not None else ""})
        payload = {"ok": True, "envelope": args.envelope,
                   "status": "POST_MERGE_VERIFIED", "checks": checks,
                   "tests_count": tests_count,
                   "review": rel(root, review_file)}
        if merge_record is not None:
            payload["merge_record"] = rel(root, merge_record)
        emit(with_position(root, payload))
    env["status"] = "CORRECTION_REQUIRED"
    jdump(env_path, env)
    if entry is not None:
        entry["status"] = "CORRECTION_REQUIRED"
        save_queue(root, queue)
    append_supervision_ledger(root, "POST_MERGE_FAILED", "supervision",
                              {"envelope": args.envelope, "result": args.result,
                               "tests_count": tests_count,
                               "tower_tests_count": tower_count,
                               "checks": checks})
    emit(with_position(root, {"ok": False, "envelope": args.envelope,
          "status": "CORRECTION_REQUIRED", "checks": checks,
          "tests_count": tests_count, "review": rel(root, review_file)}), 2)


def cmd_supervision_status(root: Path, args) -> None:
    state = load_supervision(root)
    queue = load_queue(root)
    envelopes = []
    env_dir = root / "supervision" / "envelopes"
    if env_dir.exists():
        for p in sorted(env_dir.glob("*.json")):
            data = jload(p)
            envelopes.append({"envelope_id": data.get("envelope_id"),
                              "task": data.get("task"), "status": data.get("status"),
                              "merge_commit": data.get("merge_commit")})
    emit({"ok": True, "role": state.get("role"), "phase": state.get("phase"),
          "supervisor": state.get("supervisor"), "queue": queue.get("entries", []),
          "envelopes": envelopes})


def cmd_supervision_phase(root: Path, args) -> None:
    path = root / "supervision" / "CURRENT_STATE.json"
    state = jload(path)
    old = state.get("phase")
    state["phase"] = args.phase
    if args.next:
        state["next_action"] = args.next
    state["updated_at"] = now()
    jdump(path, state)
    append_supervision_ledger(root, "SUPERVISION_PHASE", "supervision",
                              {"from": old, "to": args.phase,
                               "next": state.get("next_action")})
    emit({"ok": True, "phase": args.phase, "next_action": state.get("next_action")})


def cmd_task_next(root: Path, args) -> None:
    rec = load_record(root, args.task)
    rec["next"] = args.next
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "TASK_NEXT", "primary", {"task": args.task, "next": args.next})
    emit({"ok": True, "task": args.task, "next": args.next})


def cmd_phase(root: Path, args) -> None:
    path = root / "primary" / "CURRENT_STATE.json"
    state = jload(path)
    old = state.get("phase")
    state["phase"] = args.phase
    if args.next:
        state["next_action"] = args.next
    state["updated_at"] = now()
    state["revision"] = int(state.get("revision", 0)) + 1
    jdump(path, state)
    append_ledger(root, "PHASE", "primary", {"from": old, "to": args.phase,
                                             "next": state.get("next_action")})
    emit({"ok": True, "phase": args.phase, "next_action": state.get("next_action")})


def cmd_status(root: Path, args) -> None:
    state = jload(root / "primary" / "CURRENT_STATE.json")
    board = load_board(root)
    drift = authority_drift(root)
    authority = authority_state_check(root)
    emit({"ok": True, "tower": state.get("tower_id"), "role": state.get("role"),
          "phase": state.get("phase"), "next_action": state.get("next_action"),
          "tasks": board.get("tasks", []),
          "authority_dirty": drift,
          "authority_dirty_count": None if drift is None else len(drift),
          "authority_state": authority["status"]})
