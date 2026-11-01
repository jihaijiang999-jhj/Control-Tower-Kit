"""Envelopes, merge queue, review binding and review gate."""
from __future__ import annotations

from pathlib import Path
from tower_common import (
    TASK_ID_RE, check_package_id, check_task_id, emit, fail, git, git_ok,
    is_safe_id, jdump, jload, now, rel, resolve_input_within, resolve_repository,
)
from tower_ledger import append_ledger, append_supervision_ledger, task_dir
from tower_ledger_replay import (
    CHECKBACK_STATUSES, ENVELOPE_REOPEN_STATUSES, ENVELOPE_TERMINAL_STATUSES,
    ledger_events_naming, ledger_has_queue_add, ledger_payloads_by_task,
    verify_ledger_file,
)
from tower_task import (
    _latest_by, _optional_task_record, load_record, save_record, update_board,
)
from tower_campaign import position_review_lines, with_position
from tower_dispatch import _dispatch_base_sha
from tower_delivery import check_evidence


def load_supervision(root: Path) -> dict:
    path = root / "supervision" / "CURRENT_STATE.json"
    if not path.exists():
        fail([f"supervision state missing: {rel(root, path)}"])
    return jload(path)


def load_queue(root: Path) -> dict:
    path = root / "supervision" / "MERGE_QUEUE.json"
    if path.exists():
        return jload(path)
    return {"schema": "tower/merge-queue@1", "entries": []}


def save_queue(root: Path, queue: dict) -> None:
    queue["updated_at"] = now()
    jdump(root / "supervision" / "MERGE_QUEUE.json", queue)


def add_merge_ledger(root: Path, entry: dict) -> None:
    path = root / "supervision" / "registries" / "merge-ledger.json"
    if path.exists():
        ledger = jload(path)
    else:
        ledger = {"schema": "tower/merge-ledger@1", "entries": []}
    ledger.setdefault("entries", []).append(entry)
    jdump(path, ledger)


def envelope_has_baselines(env: dict) -> bool:
    """True for a new-style envelope that declares both test-count baselines.

    Both counts must be real integers >= 1 (``bool`` excluded).  The same
    predicate gates the new-style ledger checks in :func:`envelope_checks` and
    the legacy-only pre-merge chain check in ``merge-check`` (PILOT-039), so
    the two decisions cannot drift apart.
    """
    tests_baseline = env.get("tests_baseline")
    tower_tests_baseline = env.get("tower_tests_baseline")
    return (isinstance(tests_baseline, int) and not isinstance(tests_baseline, bool)
            and tests_baseline >= 1
            and isinstance(tower_tests_baseline, int)
            and not isinstance(tower_tests_baseline, bool)
            and tower_tests_baseline >= 1)


def review_mismatches(root: Path, task: str, review: dict, head: str) -> list[str]:
    """Field-level staleness between one ``REVIEW.json`` and the envelope.

    ``base`` is only compared when the record still carries a
    ``dispatch.base_sha``; a legacy record has nothing to compare against, and
    an absent field is ``None`` (never an accidental match).
    """
    base = _dispatch_base_sha(_optional_task_record(root, task) or {})
    expected = (("schema", review.get("schema"), REVIEW_SCHEMA),
                ("verdict", review.get("verdict"), "PASS"),
                ("head", review.get("head"), head),
                ("base", review.get("base"), base))
    return [f"stale review: {name} {actual!r} != {want!r}"
            for name, actual, want in expected if want is not None and actual != want]


def review_problems(root: Path, env: dict, task: str) -> list[str]:
    """Why this envelope's structured review does not bind it (``[]`` = bound).

    ``REVIEW.json`` is the authority: it must declare the schema, a PASS
    verdict, the envelope's ``implementation_head_sha`` and — when the record
    still carries one — the recorded ``dispatch.base_sha``.  A mismatch is
    reported as *stale*: the review was written for other code and must be
    re-run, never silently accepted.
    """
    path = review_json_path(root, task)
    head = str(env.get("implementation_head_sha") or "")
    try:
        review = jload(path) if path.exists() else None
    except (OSError, ValueError) as exc:
        return [f"REVIEW.json unreadable: {rel(root, path)}: {exc}"]
    if not isinstance(review, dict):
        return [f"stale review: {rel(root, path)} missing or not a JSON object; "
                f"checkback must bind the review to head {head}"]
    return review_mismatches(root, task, review, head)


def review_binding_check(root: Path, env: dict, task: str) -> tuple[bool, str]:
    """The ``review bound to head`` check: is a structured review in force?

    Cards checked back before PILOT-058 have a ``CHECKBACK`` ledger event with
    no ``head`` field; those keep the old review gate (record verdict only) and
    are reported as legacy instead of being retro-fitted.  Every checkback from
    this version on writes the head into that event, so the card is bound and
    :func:`review_problems` decides.
    """
    if not is_safe_id(task, TASK_ID_RE):
        return True, "legacy: no task record to bind a review to"
    try:
        payloads = ledger_payloads_by_task(root, "CHECKBACK").get(task, [])
    except OSError:
        # An unreadable primary ledger is already a failing gate of its own
        # (``ledger chain intact`` / ``verify-ledger``); never a second error or
        # a traceback here.
        return True, "legacy: CHECKBACK ledger unreadable"
    if not any("head" in payload for payload in payloads):
        review_path = task_dir(root, task) / "REVIEW.json"
        try:
            number = int(task.rsplit("-", 1)[1]) if task.startswith("PILOT-") else 0
        except (IndexError, ValueError):
            number = 0
        if review_path.exists() or number >= 58:
            return False, ("structured CHECKBACK required for PILOT-058+ cards "
                           "(missing head binding)")
        return True, "legacy: no structured CHECKBACK event (pre-058 review)"
    problems = review_problems(root, env, task)
    return not problems, "; ".join(problems) or "ok"


def envelope_checks(root: Path, env: dict, expected_id=None) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # The envelope file's id is not authoritative on its own: a copy of a
    # merged envelope saved under another name would otherwise inherit its
    # history.  The CLI callers also compare the id before running any check
    # (so a mismatch cannot leak a partial verdict); this check exists so
    # ``envelope_checks`` is self-contained when called directly with an
    # expected id.  Callers that do not know the requested id skip it.
    if expected_id is not None:
        declared = env.get("envelope_id")
        add("envelope identity matches request", declared == expected_id,
            f"file={declared!r} request={expected_id!r}")
    repo = resolve_repository(root, env.get("repository"))
    add("repository exists", repo.exists(), str(repo))
    # A new-style envelope (both count baselines declared) must have reached
    # the merge queue through ``queue-add``.  A hand-edited
    # ``MERGE_QUEUE.json`` leaves no ``QUEUE_ADD`` event, so the queue entry
    # would otherwise be accepted purely on the strength of the file.
    # Envelopes predating the baseline requirement keep the old behaviour.
    if envelope_has_baselines(env):
        # Both ledger files must verify end-to-end: a forged row can name the
        # envelope and still be detected here as a broken hash chain.
        chain_errors: list[str] = []
        reports: dict[str, dict] = {}
        for ledger_name in ("primary", "supervision"):
            report = verify_ledger_file(root, ledger_name)
            reports[ledger_name] = report
            chain_errors.extend(
                f"{ledger_name}: {error}"
                for error in report["errors"])
        add("ledger chain intact", not chain_errors,
            chain_errors[0] if chain_errors else "ok")
        # The two lifecycle checks below read ``ledger/supervision.jsonl``; when
        # that file is missing or unreadable they cannot tell "no event" from
        # "no ledger" and would report a misleading ``ENVELOPE_NEW event
        # missing``.  The chain check above already fails the envelope and
        # blocks the merge, so they are skipped in exactly that one case; a
        # readable ledger with a broken chain still runs them.
        supervision = reports["supervision"]
        supervision_available = supervision["exists"] and not any(
            error.startswith("ledger unreadable:")
            for error in supervision["errors"])
        if supervision_available:
            # ``ENVELOPE_NEW`` is the only event that brings an envelope into
            # existence.  Requiring it (not just ``QUEUE_ADD``) stops a
            # hand-written envelope from being queued by appending a single
            # valid queue event.  The event must also bind the envelope's
            # task and head: an event that names the id but a different
            # task/head does not belong to this envelope.
            created = ledger_events_naming(
                root, "supervision", "ENVELOPE_NEW", env.get("envelope_id"))
            if not created:
                add("envelope_new recorded", False, "ENVELOPE_NEW event missing")
            else:
                envelope_task = env.get("task")
                envelope_head = env.get("envelope_head_sha")
                bound = next(
                    (payload for payload in created
                     if payload.get("task") == envelope_task
                     and payload.get("head") == envelope_head), None)
                if bound is not None:
                    add("envelope_new recorded", True,
                        "ENVELOPE_NEW event present")
                else:
                    payload = created[0]
                    mismatch: list[str] = []
                    if payload.get("task") != envelope_task:
                        mismatch.append(
                            f"task {payload.get('task')} != {envelope_task}")
                    if payload.get("head") != envelope_head:
                        mismatch.append(
                            f"head {payload.get('head')} != {envelope_head}")
                    add("envelope_new recorded", False,
                        "ENVELOPE_NEW event present but binding mismatch: "
                        + "; ".join(mismatch))
            backed = ledger_has_queue_add(root, env.get("envelope_id"))
            add("queue entry backed by ledger", backed,
                f"QUEUE_ADD event {'present' if backed else 'missing'}")
    if not repo.exists():
        return checks
    branch = env.get("branch", "")
    base = env.get("base", "main")
    a = env.get("implementation_head_sha", "")
    b = env.get("envelope_head_sha", "")
    envelope_path = env.get("envelope_path", "")
    try:
        head = git_ok(repo, "rev-parse", branch)
        add("branch head == envelope head", head == b, f"{head} vs {b}")
        parent = git_ok(repo, "rev-parse", f"{b}^")
        add("envelope parent == implementation head", parent == a, f"{parent} vs {a}")
        changed = git_ok(repo, "diff", "--name-only", f"{a}..{b}").splitlines()
        add("envelope commit only changes envelope path",
            changed == [envelope_path], f"{changed} vs [{envelope_path}]")
        ancestor = git(repo, "merge-base", "--is-ancestor", base, a).returncode == 0
        add(f"base {base} is ancestor of implementation", ancestor, f"{base}..{a}")
    except Exception as exc:
        add("git checks", False, str(exc))
    # Never call load_record() here: it emits a JSON object and raises
    # SystemExit, which would print one payload from inside the check list and
    # a second one from the caller.  A missing/invalid record is one failed
    # check instead, so merge-check always emits exactly one JSON object.
    task = str(env.get("task") or "")
    rec = _optional_task_record(root, task)
    if rec is None:
        add("task record", False, f"task record missing: {task or '(empty)'}")
    else:
        add("task record", True, task)
        add("task accepted/closed", rec.get("status") in ("accepted", "closed"),
            str(rec.get("status")))
        review = rec.get("review") or {}
        add("review PASS", review.get("verdict") == "PASS", str(review.get("verdict")))
        add("reviewer != executor", review.get("reviewer") != rec.get("executor"),
            f"{review.get('reviewer')} vs {rec.get('executor')}")
        add(REVIEW_CHECK, *review_binding_check(root, env, task))
        ev_errors = check_evidence(root, rec)
        add("evidence hashes valid", not ev_errors, "; ".join(ev_errors) or "ok")
    return checks


STRUCTURE_QUESTIONS = (
    "新抽象是否有 ≥2 个使用点？",
    "有无死代码/永久开关？",
    "有无 ≥15 行重复？",
    "测试是否只镜像实现？",
    "新增 TODO 是否有卡号？",
)


STRUCTURE_PENDING = "未提供（044 起建议填写，暂不阻塞）"


def structure_review_lines(structure: str) -> list[str]:
    """The fixed ``## Structure review（五问）`` block (PILOT-044)."""
    lines = ["", "## Structure review（五问）", ""]
    lines += [f"{index}. {question}"
              for index, question in enumerate(STRUCTURE_QUESTIONS, start=1)]
    lines += ["", f"reviewer 回答：{structure or STRUCTURE_PENDING}"]
    return lines


def write_review_md(root: Path, task_id: str, rec: dict, reviewer: str,
                    verdict: str, note: str, structure: str) -> None:
    """Render ``REVIEW.md``: verdict, note, evidence and the structure block."""
    lines = [f"# {rec['id']} — Independent Checkback", "",
             f"- Reviewer: `{reviewer}`", f"- Verdict: **{verdict}**",
             f"- At: {rec['review']['at']}",
             f"- Head: `{rec['review'].get('head') or ''}`",
             f"- Base: `{rec['review'].get('base') or ''}`", "",
             "## Note", "", note or "(none)", "",
             "## Evidence checked", ""]
    lines += [f"- `{e['path']}` `{e['sha256']}`" for e in rec.get("evidence", [])]
    lines += structure_review_lines(structure) + position_review_lines(root, task_id)
    (task_dir(root, task_id) / "REVIEW.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def checkback_reviewer(rec: dict, raw) -> str:
    """Validate and normalise the reviewer identity (non-empty, not executor)."""
    reviewer = (raw or "").strip()
    if not reviewer:
        fail(["reviewer must be non-empty (whitespace-only is not a reviewer)"])
    if reviewer == (rec.get("executor") or "").strip():
        fail(["reviewer must differ from executor"])
    return reviewer


REVIEW_SCHEMA = "tower/review@1"


REVIEW_CHECK = "review bound to head"


def review_json_path(root: Path, task_id: str) -> Path:
    """``tasks/<id>/REVIEW.json``: the structured review (PILOT-058)."""
    return task_dir(root, task_id) / "REVIEW.json"


def worktree_review_head(root: Path, rec: dict) -> str:
    """The task worktree's ``HEAD``, or ``""`` when it cannot be read.

    A review binds to the code the reviewer actually saw, so the default head
    is read from the worktree, never supplied by the caller.  A card without a
    worktree (fixture or legacy) records an empty head; only a CHECKBACK event
    that carries a head arms the merge-check gate (see
    :func:`review_binding_check`).
    """
    worktree = rec.get("worktree")
    if not isinstance(worktree, str) or not worktree.strip():
        return ""
    path = root / worktree
    try:
        if root.resolve() not in path.resolve().parents:
            return ""
    except OSError:
        return ""
    if not path.exists():
        return ""
    cp = git(path, "rev-parse", "HEAD")
    return cp.stdout.strip() if cp.returncode == 0 else ""


def write_review_json(root: Path, rec: dict, reviewer: str, args) -> dict:
    """Write ``tasks/<id>/REVIEW.json`` for one checkback (PASS or FAIL).

    ``--head`` defaults to the worktree HEAD and ``--base`` to the recorded
    ``dispatch.base_sha``, so the structured review names the exact code and
    baseline the verdict covers.  FAIL is written as well: a failed review is
    evidence, not an absence of one.
    """
    task = str(rec.get("id") or args.task)
    head = (getattr(args, "head", None) or "").strip() or worktree_review_head(root, rec)
    base = ((getattr(args, "base", None) or "").strip()
            or (_dispatch_base_sha(rec) or ""))
    review = {
        "schema": REVIEW_SCHEMA, "task": task, "reviewer": reviewer,
        "verdict": args.verdict, "head": head, "base": base,
        "scope": [str(item) for item in getattr(args, "scope", None) or []],
        "findings": [str(item) for item in getattr(args, "finding", None) or []],
        "note": args.note or "", "at": now(),
    }
    jdump(review_json_path(root, task), review)
    return review


def cmd_checkback(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in CHECKBACK_STATUSES:
        fail([f"task status {rec.get('status')} cannot checkback"])
    reviewer = checkback_reviewer(rec, args.reviewer)
    structure = args.structure or ""
    review = write_review_json(root, rec, reviewer, args)
    review["structure"] = structure
    rec["review"] = review
    rec["status"] = "reviewed" if args.verdict == "PASS" else "rework"
    rec["next"] = "等待 accept" if args.verdict == "PASS" else "返工"
    save_record(root, rec)
    update_board(root, rec)
    write_review_md(root, args.task, rec, reviewer, args.verdict,
                    args.note or "", structure)
    append_ledger(root, "CHECKBACK", "reviewer",
                  {"task": args.task, "reviewer": reviewer,
                   "verdict": args.verdict, "head": review["head"],
                   "base": review["base"]})
    emit(with_position(root, {"ok": True, "task": args.task, "status": rec["status"],
          "verdict": args.verdict, "structure": bool(structure),
          "head": review["head"], "base": review["base"]}))


def select_envelope(queue: dict, envelope_id: str | None = None) -> dict:
    """Pick the merge-queue entry a handoff is about.

    An explicit ``envelope_id`` wins; a single queued entry is used as-is;
    otherwise the entry with the newest ``added_at`` wins.
    """
    entries = [e for e in (queue.get("entries") or []) if isinstance(e, dict)]
    if envelope_id:
        return next((e for e in entries if e.get("envelope_id") == envelope_id), {})
    if len(entries) == 1:
        return entries[0]
    return _latest_by(entries, "added_at")


def envelope_new_status(env_path: Path) -> str:
    """Status ``envelope-new`` writes for a first or repeated envelope record.

    A first envelope starts ``DRAFT``.  Re-enveloping after a failed merge
    keeps ``WAITING``/``CORRECTION_REQUIRED`` so the file, the replay fold and
    the merge gate agree; a terminal envelope cannot be reopened (only a new
    card can), so it is refused before any file or ledger write.
    """
    if not env_path.exists():
        return "DRAFT"
    try:
        existing = jload(env_path)
    except (OSError, ValueError):
        return "DRAFT"
    status = existing.get("status") if isinstance(existing, dict) else None
    if status in ENVELOPE_TERMINAL_STATUSES:
        fail([f"envelope already {status}; a merged envelope cannot be reopened"])
    if status in ENVELOPE_REOPEN_STATUSES:
        return status
    return "DRAFT"


def cmd_envelope_new(root: Path, args) -> None:
    task_id = check_task_id(args.task, "task")
    file = resolve_input_within(root, args.file, "envelope file")
    if not file.exists():
        fail([f"envelope file not found: {file}"])
    env = jload(file)
    env_id = env.get("envelope_id")
    task = env.get("task")
    if not env_id or not task:
        fail(["envelope_id and task are required"])
    env_id = check_package_id(env_id, "envelope")
    task = check_task_id(task, "task")
    if task != task_id:
        fail([f"envelope task {task} != --task {task_id}"])
    # Resolve the status before any git/record work: reopening a merged
    # envelope is a semantic refusal, not a repository-shape failure.
    env_path = root / "supervision" / "envelopes" / f"{env_id}.json"
    status = envelope_new_status(env_path)
    # Both count baselines are mandatory for a *new* envelope.  The post-merge
    # gates treat them as opt-in, so an envelope that simply omitted them used
    # to downgrade its own count checks silently; requiring them here (before
    # any file, ledger or record write) closes that hole.  Legacy envelopes
    # already on disk keep the old opt-in semantics in ``merge-check`` and
    # ``post-merge``.
    if not envelope_has_baselines(env):
        fail(["envelope tests_baseline and tower_tests_baseline must be positive "
              "integers (int >= 1)"])
    rec = load_record(root, task_id)
    if rec.get("status") not in ("accepted", "closed"):
        fail([f"task status {rec.get('status')} cannot submit envelope"])
    if not (rec.get("review") or {}).get("verdict") == "PASS":
        fail(["task has no PASS review"])
    repo = resolve_repository(root, env.get("repository"))
    if not repo.exists():
        fail([f"repository missing: {repo}"])
    branch = env.get("branch")
    base = env.get("base", "main")
    a = env.get("implementation_head_sha")
    envelope_path = env.get("envelope_path")
    if not branch or not a or not envelope_path:
        fail(["branch, implementation_head_sha and envelope_path are required"])
    try:
        b = git_ok(repo, "rev-parse", branch)
        parent = git_ok(repo, "rev-parse", f"{b}^")
        changed = git_ok(repo, "diff", "--name-only", f"{a}..{b}").splitlines()
        ancestor = git(repo, "merge-base", "--is-ancestor", base, a).returncode == 0
    except Exception as exc:
        fail([str(exc)])
    checks = [
        {"name": "envelope parent == implementation", "ok": parent == a,
         "detail": f"{parent} vs {a}"},
        {"name": "envelope commit only changes envelope path", "ok": changed == [envelope_path],
         "detail": f"{changed} vs [{envelope_path}]"},
        {"name": f"base {base} is ancestor of implementation", "ok": ancestor,
         "detail": f"{base}..{a}"},
    ]
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "errors": [c for c in checks if not c["ok"]]}, 2)
    record = dict(env)
    record.update({"envelope_head_sha": b, "status": status, "created_at": now()})
    jdump(env_path, record)
    append_supervision_ledger(root, "ENVELOPE_NEW", "primary",
                              {"envelope": env_id, "task": task, "head": b})
    emit({"ok": True, "envelope": env_id, "head": b, "checks": checks})


def cmd_queue_add(root: Path, args) -> None:
    envelope_id = check_package_id(args.envelope, "envelope")
    env_path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    queue = load_queue(root)
    # ``envelope-new`` requires both count baselines, but a hand-written
    # ``supervision/envelopes/<id>.json`` never passes through it, so queueing
    # it used to be the bypass: the post-merge gates treat the baselines as
    # opt-in and an omitted field silently skipped its count check.  Enforce
    # the same rule here, before any queue/ledger write, so the invariant holds
    # for every envelope that can reach the merge queue.  Legacy envelopes
    # already in the queue are untouched; only new additions are gated.
    tests_baseline = env.get("tests_baseline")
    tower_tests_baseline = env.get("tower_tests_baseline")
    if not (isinstance(tests_baseline, int) and not isinstance(tests_baseline, bool)
            and tests_baseline >= 1
            and isinstance(tower_tests_baseline, int)
            and not isinstance(tower_tests_baseline, bool)
            and tower_tests_baseline >= 1):
        fail(["envelope tests_baseline and tower_tests_baseline must be positive "
              "integers (int >= 1)"])
    # The queue entry is written before the ledger event, so a crash between
    # the two leaves a WAITING entry with no ``QUEUE_ADD``: a persistent
    # ``queue_unbacked`` that a retry used to refuse as "already queued".
    # After the baseline gate has admitted the envelope, an existing entry is
    # a half-write iff the ledger never recorded its ``QUEUE_ADD``; finish
    # that one write (event only, entry untouched) instead of dead-ending.
    # A ledger-backed entry is a real duplicate and still fails.  The repair
    # never runs for an envelope the baseline gate rejects, above.
    existing = next((e for e in queue.get("entries", [])
                     if e.get("envelope_id") == envelope_id), None)
    if existing is not None:
        if ledger_has_queue_add(root, envelope_id):
            fail([f"envelope already queued: {args.envelope}"])
        append_supervision_ledger(root, "QUEUE_ADD", "primary",
                                  {"envelope": args.envelope,
                                   "task": env.get("task")})
        emit({"ok": True, "envelope": args.envelope, "status": "WAITING",
              "repaired": True})
        return
    queue.setdefault("entries", []).append({
        "envelope_id": envelope_id,
        "task": env.get("task"),
        "branch": env.get("branch"),
        "base": env.get("base", "main"),
        "status": "WAITING",
        "added_at": now(),
    })
    save_queue(root, queue)
    append_supervision_ledger(root, "QUEUE_ADD", "primary",
                              {"envelope": args.envelope, "task": env.get("task")})
    emit({"ok": True, "envelope": args.envelope, "status": "WAITING"})


def envelope_remerge_errors(root: Path, env: dict, envelope_id: str) -> list[str]:
    """Refuse a ``DRAFT`` envelope that a re-envelope reset (the 052 drift).

    ``envelope-new`` writes the first ``ENVELOPE_NEW`` and is also the
    re-envelope path.  A first envelope is legitimately ``DRAFT`` until it
    merges, so the file status alone cannot be the gate: only an envelope whose
    ledger already holds a previous ``ENVELOPE_NEW`` (a re-envelope) must still
    be ``WAITING``/``CORRECTION_REQUIRED``.  An envelope with no re-envelope
    history (hand-written legacy fixtures, one-shot envelopes) keeps the old
    behaviour, and a non-``DRAFT`` status is handled by the caller.
    """
    if env.get("status") != "DRAFT":
        return []
    events = ledger_events_naming(root, "supervision", "ENVELOPE_NEW",
                                  envelope_id)
    if len(events) >= 2:
        return ["envelope status DRAFT after a re-envelope "
                f"(ENVELOPE_NEW x{len(events)}); expected "
                "WAITING/CORRECTION_REQUIRED"]
    return []
