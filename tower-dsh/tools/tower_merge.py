"""Merge check, gh PR path and the merge gate."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from tower_common import (
    MergeBlocked, TASK_ID_RE, check_package_id, command_failure, emit, fail,
    gh_command, git, git_ok, is_safe_id, jdump, jload, now, resolve_repository,
)
from tower_ledger import append_supervision_ledger, task_dir
from tower_ledger_replay import (
    ENVELOPE_MERGEABLE_STATUSES, ENVELOPE_TERMINAL_STATUSES, ledger_break_phrase,
    ledger_precondition_breaks,
)
from tower_authority import AUTHORITY_POLICY_FILE, AUTHORITY_REQUIRED_EVENT
from tower_authority_cmd import authority_state_check, ledger_empty_guard
from tower_envelope import (
    add_merge_ledger, envelope_checks, envelope_has_baselines,
    envelope_remerge_errors, load_queue, load_supervision, save_queue,
)


def cmd_merge_check(root: Path, args) -> None:
    envelope_id = check_package_id(args.envelope, "envelope")
    env_path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    # Exact comparison, with no ``str()`` normalisation: a JSON declaration
    # of ``42`` is not the requested id ``"42"``.  Command-level failures are
    # plain strings (``errors``), not check dictionaries.
    declared = env.get("envelope_id")
    if declared != envelope_id:
        fail([f"envelope identity matches request: file declares "
              f"{declared if declared is not None else '(missing)'!r}, "
              f"request {envelope_id!r}"])
    checks = envelope_checks(root, env, expected_id=envelope_id)
    # Authority state is reported on every merge-check, including the legacy
    # case: a tower without AUTHORITY state must keep passing (old fixtures),
    # but the absence has to be visible in the verdict, not silent.
    # PILOT-038: a required tower reports the requirement as its own check.
    # Required-but-unconfigured and a mismatched marker both surface through
    # ``authority["errors"]``, so they fail this check instead of passing as
    # legacy.
    authority = authority_state_check(root)
    if authority["errors"]:
        checks.append({"name": "merge authority", "ok": False,
                       "detail": "; ".join(authority["errors"])})
    elif authority["status"] == "legacy":
        checks.append({"name": "merge authority", "ok": True,
                       "detail": "legacy: no AUTHORITY_SET"})
    elif authority["required"]:
        checks.append({"name": "merge authority requirement pinned", "ok": True,
                       "detail": f"authority requirement pinned: "
                                 f"{AUTHORITY_POLICY_FILE} + "
                                 f"{AUTHORITY_REQUIRED_EVENT}, merge authority "
                                 f"pinned: {authority['merge_authority']}"})
    else:
        checks.append({"name": "merge authority pinned", "ok": True,
                       "detail": f"merge authority pinned: "
                                 f"{authority['merge_authority']}"})
    # PILOT-039: a legacy envelope has no lifecycle events, so
    # ``envelope_checks`` never verifies the ledgers for it.  Without this
    # independent check a forged ledger row would only be caught by ``merge``.
    # New-style envelopes already carry ``ledger chain intact``; adding the
    # same verification twice would report one broken chain as two synonymous
    # failures, so the check is deliberately legacy-only.
    if not envelope_has_baselines(env):
        breaks = ledger_precondition_breaks(root)
        checks.append({
            "name": "pre-merge ledger chains verified",
            "ok": not breaks,
            "detail": "ok" if not breaks else "; ".join(
                ledger_break_phrase(name, first)
                for name, first in breaks),
        })
    # PILOT-040: the empty-ledger guard is reported only when it fires.  An
    # always-present ok=True item here would change the check list of every
    # existing configured/required fixture (036/037/038/039 assert exact
    # lists), while a fresh empty tower has nothing to report.  When it fires
    # the item names the same condition ``merge`` fails closed on.
    empty_ledger = ledger_empty_guard(root)
    if empty_ledger:
        checks.append({"name": "ledger history present", "ok": False,
                       "detail": "; ".join(empty_ledger)})
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == envelope_id), None)
    checks.append({"name": "queued", "ok": entry is not None,
                   "detail": entry.get("status") if entry else "missing"})
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "envelope": args.envelope,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    emit({"ok": True, "envelope": args.envelope, "checks": checks})


PR_URL_RE = re.compile(r"^https?://\S+/pull/(\d+)$")


def parse_created_pr(stdout: str):
    """Parse the PR identity ``gh pr create`` prints as its last line.

    Real ``gh`` has no ``--json`` flag on ``pr create``; it prints the PR URL
    on stdout.  Returns ``(url, number)`` or ``None`` when the output does not
    look like a pull-request URL.
    """
    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    if not lines:
        return None
    url = lines[-1]
    match = PR_URL_RE.match(url)
    if not match:
        return None
    return url, int(match.group(1))


GH_AUTH_HINT = "run 'gh auth login' to authenticate"


def run_gh(repo: Path, argv: list[str], *, phase: str,
           timeout: float) -> subprocess.CompletedProcess:
    """Run one ``gh`` invocation with ``repo`` as the working directory.

    Every call is bounded by ``--check-timeout`` and every spawn failure is
    turned into a :class:`MergeBlocked`; no traceback may escape a merge.
    """
    try:
        return subprocess.run(
            [*gh_command(), *argv], cwd=str(repo), capture_output=True,
            text=True, encoding="utf-8", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise MergeBlocked(
            phase, "timeout",
            f"gh {argv[0]} {argv[1] if len(argv) > 1 else ''} did not finish "
            f"within {timeout:g}s") from None
    except OSError as exc:
        raise MergeBlocked("gh", "gh-exec", str(exc)) from None


def require_gh_auth(repo: Path, timeout: float) -> None:
    """Fail closed unless ``gh auth status`` reports an authenticated host.

    A merge must never be pinned at ``MERGING`` on a host whose token is
    missing or expired: real ``gh pr create`` would then fail halfway through.
    Every failure mode (non-zero exit, spawn error, timeout) becomes a
    :class:`MergeBlocked` carrying the ``gh auth login`` hint, so no traceback
    escapes and the queue lands in ``CORRECTION_REQUIRED``.
    """
    try:
        cp = run_gh(repo, ["auth", "status"], phase="gh-auth", timeout=timeout)
    except MergeBlocked as exc:
        reason = "timeout" if exc.reason == "timeout" else "gh-exec"
        raise MergeBlocked(
            "gh-auth", reason, f"{exc.detail}; {GH_AUTH_HINT}") from None
    if cp.returncode != 0:
        output = "\n".join(part.strip() for part in
                           (cp.stderr or "", cp.stdout or "") if part.strip())
        detail = f"{output}\n{GH_AUTH_HINT}" if output else GH_AUTH_HINT
        raise MergeBlocked("gh-auth", "not-authenticated", detail)


def require_git(repo: Path, phase: str, *git_args: str) -> subprocess.CompletedProcess:
    """Run one git step of the PR flow, blocking the merge when it fails."""
    cp = git(repo, *git_args)
    if cp.returncode != 0:
        raise MergeBlocked(phase, phase, command_failure(cp))
    return cp


CHECKS_PENDING_EXIT = 8


CHECKS_PENDING_RE = re.compile(r"no checks reported", re.IGNORECASE)


def checks_timeout_detail(number: int, timeout: float, last: str) -> str:
    detail = (f"gh pr checks {number} did not report a usable result within "
              f"{timeout:g}s")
    return f"{detail}; last output: {last}" if last else detail


def wait_for_checks(repo: Path, number: int, timeout: float,
                    interval: float) -> None:
    """Watch the PR checks until they are green, tolerating registration lag.

    The retry loop is deliberately narrow: only "checks pending" is transient.
    That state is recognised from the ``gh`` exit code (8, documented by
    ``gh pr checks --help``) or, for older builds, from the exact phrase
    "no checks reported".  Any other non-zero exit is a real CI failure and
    blocks the merge immediately.  Each invocation gets the time left on the
    single ``--check-timeout`` deadline, so the whole gate stays bounded.
    """
    argv = ["pr", "checks", str(number), "--watch", "--fail-fast"]
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MergeBlocked("checks", "timeout",
                               checks_timeout_detail(number, timeout, last))
        cp = run_gh(repo, argv, phase="checks", timeout=remaining)
        output = "\n".join(part.strip() for part in
                           (cp.stdout or "", cp.stderr or "") if part.strip())
        if cp.returncode == 0:
            return
        if not (cp.returncode == CHECKS_PENDING_EXIT
                or CHECKS_PENDING_RE.search(output)):
            raise MergeBlocked("checks", "checks",
                               output or f"exit code {cp.returncode}")
        last = output
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MergeBlocked("checks", "timeout",
                               checks_timeout_detail(number, timeout, last))
        time.sleep(min(interval, remaining))


def expected_merge_head(env: dict) -> str:
    """The implementation head a PR merge must match (PILOT-058)."""
    head = env.get("implementation_head_sha")
    return head.strip() if isinstance(head, str) else ""


def pr_remote_merge(repo: Path, env: dict, args) -> dict:
    """Steps 1-4 of a ``--mode pr`` merge: push, create, checks, merge the PR.

    The remote half is split from the fast-forward half so the caller can
    persist ``remote_merged`` before touching the local branch.  Raises
    :class:`MergeBlocked` on the first failure.
    """
    branch = str(env.get("branch") or "")
    base = str(env.get("base", "main"))
    remote = getattr(args, "remote", None) or "origin"
    timeout = int(getattr(args, "check_timeout", 900) or 900)
    interval = float(getattr(args, "check_interval", 10) or 10)
    if interval <= 0:
        interval = 1.0

    # 1. the remote must actually see the envelope branch before a PR exists.
    require_git(repo, "push", "push", remote, branch)

    # 2. open the PR: real gh has no ``--json`` here and prints the URL only.
    body = (
        f"Tower merge envelope {args.envelope} for task {env.get('task')}.\n\n"
        f"- implementation: {env.get('implementation_head_sha')}\n"
        f"- envelope head: {env.get('envelope_head_sha')}\n"
        f"- supervisor: {args.supervisor}\n"
    )
    cp = run_gh(repo, ["pr", "create", "--base", base, "--head", branch,
                       "--title", f"merge: {env.get('task')} ({args.envelope})",
                       "--body", body],
                phase="pr-create", timeout=timeout)
    if cp.returncode != 0:
        combined = f"{cp.stdout or ''}\n{cp.stderr or ''}"
        if "already exists" in combined.lower():
            # Re-running a merge reuses the open PR (``gh pr view`` supports json).
            cp = run_gh(repo, ["pr", "view", branch, "--json", "number,url"],
                        phase="pr-view", timeout=timeout)
            if cp.returncode != 0:
                raise MergeBlocked("pr-view", "view", command_failure(cp))
            try:
                viewed = json.loads(cp.stdout)
                number = viewed["number"]
                url = viewed["url"]
            except (TypeError, ValueError, KeyError):
                raise MergeBlocked(
                    "pr-view", "parse",
                    f"cannot parse gh pr view output: {(cp.stdout or '').strip()}"
                ) from None
        else:
            raise MergeBlocked("pr-create", "create", command_failure(cp))
    else:
        parsed = parse_created_pr(cp.stdout)
        if parsed is None:
            raise MergeBlocked(
                "pr-create", "no-url",
                f"cannot parse PR URL from gh pr create output: "
                f"{(cp.stdout or '')}{(cp.stderr or '')}".strip())
        url, number = parsed

    # 3. CI gate, bounded by --check-timeout; a PR whose checks have not
    #    registered yet is retried until that deadline.
    wait_for_checks(repo, number, timeout, interval)

    # 4. merge the PR once the checks are green.  ``--match-head-commit`` pins
    #    the merge to the implementation head this envelope names.
    cp = run_gh(repo, ["pr", "merge", str(number), "--merge",
                       "--match-head-commit", expected_merge_head(env)],
                phase="pr-merge", timeout=timeout)
    if cp.returncode != 0:
        raise MergeBlocked("pr-merge", "merge", command_failure(cp))
    return {"pr_number": number, "pr_url": url}


def pr_fast_forward(repo: Path, env: dict, args) -> str:
    """Steps 5-6: fetch the merged base, require a fast-forward, return HEAD."""
    base = str(env.get("base", "main"))
    remote = getattr(args, "remote", None) or "origin"
    require_git(repo, "fetch", "fetch", remote, base)
    require_git(repo, "ff-only", "merge", "--ff-only", f"{remote}/{base}")
    return git_ok(repo, "rev-parse", "HEAD")


def block_pr_merge(root: Path, args, env: dict, env_path: Path, queue: dict,
                   entry: dict, phase: str, reason: str, detail: str) -> None:
    """Record a blocked PR merge: both the entry and the envelope need correction.

    ``MERGED`` is never written on this path; only ``CORRECTION_REQUIRED`` plus
    a ``MERGE_BLOCKED`` ledger event naming the failing ``phase``.
    """
    entry["status"] = "CORRECTION_REQUIRED"
    save_queue(root, queue)
    env.update({"status": "CORRECTION_REQUIRED"})
    jdump(env_path, env)
    append_supervision_ledger(root, "MERGE_BLOCKED", "supervision", {
        "envelope": args.envelope,
        "phase": phase,
        "reason": reason,
        "detail": detail,
    })


def merge_queue_errors(root: Path, env: dict, envelope_id: str,
                       entry: dict | None) -> list[str]:
    """Envelope/queue preconditions checked after both files are read.

    The entry must be queued and still ``WAITING``/``CORRECTION_REQUIRED`` (a
    failed merge marks it for correction and the retry reuses the same entry).
    The envelope file must not be a ``DRAFT`` that a re-envelope reset; see
    :func:`envelope_remerge_errors` for why the first envelope stays exempt.
    """
    if entry is None:
        return [f"envelope not queued: {envelope_id}"]
    if entry.get("status") not in ENVELOPE_MERGEABLE_STATUSES:
        return [
            f"queue entry status {entry.get('status')} is not "
            "WAITING/CORRECTION_REQUIRED; only a waiting or corrected entry "
            "may merge"
        ]
    return envelope_remerge_errors(root, env, envelope_id)


def cmd_merge(root: Path, args) -> None:
    if args.role != "supervisor":
        fail(["merge requires --role supervisor"])
    envelope_id = check_package_id(args.envelope, "envelope")
    supervision = load_supervision(root)
    primary = jload(root / "primary" / "CURRENT_STATE.json").get("primary", {})
    if args.supervisor == primary.get("id"):
        fail(["primary cannot merge; supervisor must differ"])
    # Authority state is decided before the envelope, queue or repository is
    # even read.  A registered authority pins exactly one merge identity, and
    # a missing/unbacked/mismatched chain fails closed instead of merging as
    # if the tower were legacy.  No queue status is written here.
    authority = authority_state_check(root)
    if authority["errors"]:
        fail(authority["errors"])
    if authority["status"] == "configured":
        pinned = authority["merge_authority"]
        if args.supervisor != pinned:
            fail([f"merge authority mismatch: state pins {pinned}, "
                  f"request {args.supervisor}"])
    # PILOT-039: the audit-chain precondition runs before the envelope, the
    # queue or any git state is read.  A forged row that keeps seq/prev_hash
    # legal (only the hash is wrong) used to ride a legacy envelope all the way
    # to MERGED; now it fails here, with the queue untouched and no
    # MERGE_START/MERGING written.
    breaks = ledger_precondition_breaks(root)
    if breaks:
        # The trailing tag names the envelope-level check that reports the same
        # condition, so callers keyed on ``ledger chain intact`` keep working
        # even though this gate now fires before the envelope is read.
        fail([f"merge precondition: {ledger_break_phrase(name, first)} "
              "(ledger chain intact)"
              for name, first in breaks])
    # PILOT-040: 039 catches a *missing* ledger; a truncation to 0 bytes keeps
    # the file and slipped through.  Still before the envelope, queue,
    # repository or git state is read: a refusal leaves the queue entry, both
    # ledgers and the envelope byte-for-byte untouched and records no
    # MERGE_START/MERGING.
    empty_ledger = ledger_empty_guard(root)
    if empty_ledger:
        fail(empty_ledger)
    env_path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    # The requested id is authoritative: every later decision (queue entry,
    # git head, status transitions) is keyed on it, so a file whose declared
    # id differs must be rejected before any of that work happens.  The
    # comparison is exact (no ``str()`` normalisation): a JSON declaration of
    # ``42`` must not pass for the requested id ``"42"``.
    declared = env.get("envelope_id")
    if declared != envelope_id:
        fail([f"envelope identity matches request: file declares "
              f"{declared if declared is not None else '(missing)'!r}, "
              f"request {envelope_id!r}"])
    if env.get("status") in ENVELOPE_TERMINAL_STATUSES:
        fail([f"envelope already {env.get('status')}"])
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == envelope_id), None)
    queue_errors = merge_queue_errors(root, env, envelope_id, entry)
    if queue_errors:
        fail(queue_errors)
    base = env.get("base", "main")
    repo = resolve_repository(root, env.get("repository"))
    try:
        current_branch = git_ok(repo, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as exc:
        entry["status"] = "CORRECTION_REQUIRED"
        save_queue(root, queue)
        append_supervision_ledger(root, "MERGE_BLOCKED", "supervision",
                                  {"envelope": args.envelope, "base": base,
                                   "reason": f"branch check failed: {exc}"})
        fail([f"cannot verify current branch against envelope base {base}: {exc}"])
    if current_branch != base:
        entry["status"] = "CORRECTION_REQUIRED"
        save_queue(root, queue)
        append_supervision_ledger(root, "MERGE_BLOCKED", "supervision",
                                  {"envelope": args.envelope, "base": base,
                                   "current_branch": current_branch})
        fail([
            f"current branch {current_branch} != envelope base {base}; "
            "checkout the envelope.base branch before merging"
        ])
    checks = envelope_checks(root, env, expected_id=envelope_id)
    checks.append({"name": "queued", "ok": entry is not None,
                   "detail": entry.get("status") if entry else "missing"})
    if not all(c["ok"] for c in checks):
        entry["status"] = "CORRECTION_REQUIRED"
        save_queue(root, queue)
        append_supervision_ledger(root, "MERGE_BLOCKED", "supervision",
                                  {"envelope": args.envelope,
                                   "errors": [c for c in checks if not c["ok"]]})
        emit({"ok": False, "envelope": args.envelope,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    mode = getattr(args, "mode", "local") or "local"
    # A previous attempt may already have merged the PR remotely and then
    # failed only at fetch/fast-forward.  Such a retry must not push, create,
    # check or merge again -- it resumes straight at step 5.
    resume_remote = (mode == "pr" and env.get("remote_merged") is True
                     and bool(env.get("pr_number")) and bool(env.get("pr_url")))
    if mode == "pr" and not resume_remote:
        # Preflight before the queue is pinned at MERGING: a host without a
        # runnable gh must fail the gate cleanly instead of leaving a
        # half-started merge.  gh_command() emits the JSON error itself, so
        # the abort is recorded and the SystemExit(2) is re-raised untouched.
        try:
            gh_command()
            require_gh_auth(repo, int(getattr(args, "check_timeout", 900) or 900))
        except SystemExit:
            block_pr_merge(root, args, env, env_path, queue, entry,
                           "gh", "gh-not-found",
                           "gh executable not found; install GitHub CLI or "
                           "set TOWERCTL_GH")
            raise
        except MergeBlocked as exc:
            block_pr_merge(root, args, env, env_path, queue, entry,
                           exc.phase, exc.reason, exc.detail)
            fail([f"pr merge blocked at {exc.phase} ({exc.reason}): {exc.detail}"])
    entry["status"] = "MERGING"
    save_queue(root, queue)
    append_supervision_ledger(root, "MERGE_START", "supervision",
                              {"envelope": args.envelope, "supervisor": args.supervisor})
    merge_extra: dict = {}
    if mode == "pr":
        try:
            if not resume_remote:
                identity = pr_remote_merge(repo, env, args)
                env.update({
                    "pr_number": identity["pr_number"],
                    "pr_url": identity["pr_url"],
                    "remote_merged": True,
                    "remote_merged_at": now(),
                })
                # Persist the remote half before touching the local branch: if
                # the fast-forward fails, the retry knows the PR is merged and
                # block_pr_merge() must never discard these fields.
                jdump(env_path, env)
            merge_commit = pr_fast_forward(repo, env, args)
        except MergeBlocked as exc:
            block_pr_merge(root, args, env, env_path, queue, entry,
                           exc.phase, exc.reason, exc.detail)
            fail([f"pr merge blocked at {exc.phase} ({exc.reason}): {exc.detail}"])
        except SystemExit:
            # gh vanished between the preflight and an actual call; the queue
            # must not be left at MERGING after the gate already emitted.
            block_pr_merge(root, args, env, env_path, queue, entry,
                           "gh", "gh-not-found",
                           "gh executable not found; install GitHub CLI or "
                           "set TOWERCTL_GH")
            raise
        merge_extra = {
            "merge_mode": "pr",
            "pr_number": env["pr_number"],
            "pr_url": env["pr_url"],
            "check_conclusion": "success",
        }
    else:
        cp = git(repo, "merge", "--no-ff", "-m",
                 f"merge: {env.get('task')} ({args.envelope})", env.get("branch", ""))
        if cp.returncode != 0:
            git(repo, "merge", "--abort")
            entry["status"] = "CORRECTION_REQUIRED"
            save_queue(root, queue)
            append_supervision_ledger(root, "MERGE_FAILED", "supervision",
                                      {"envelope": args.envelope, "stderr": cp.stderr.strip()})
            fail([f"git merge failed: {cp.stderr.strip() or cp.stdout.strip()}"])
        merge_commit = git_ok(repo, "rev-parse", "HEAD")
        # Local merges keep their existing records; only the mode is added.
        merge_extra = {"merge_mode": "local"}
    env.update({"status": "MERGED", "merge_commit": merge_commit,
                "merged_at": now(), "supervisor": args.supervisor})
    env.update(merge_extra)
    jdump(env_path, env)
    entry["status"] = "MERGED"
    entry["merge_commit"] = merge_commit
    save_queue(root, queue)
    ledger_entry = {
        "envelope_id": args.envelope, "task": env.get("task"),
        "implementation_head_sha": env.get("implementation_head_sha"),
        "envelope_head_sha": env.get("envelope_head_sha"),
        "merge_commit": merge_commit, "supervisor": args.supervisor,
        "at": now(),
    }
    merge_payload = {"envelope": args.envelope, "merge_commit": merge_commit}
    if mode == "pr":
        for key in ("merge_mode", "pr_number", "pr_url"):
            ledger_entry[key] = env[key]
            merge_payload[key] = env[key]
    add_merge_ledger(root, ledger_entry)
    append_supervision_ledger(root, "MERGE", "supervision", merge_payload)
    emit({"ok": True, "envelope": args.envelope, "status": "MERGED",
          "merge_commit": merge_commit})


def write_task_merge_record(root: Path, env: dict, envelope_id: str,
                            checks: list[dict]) -> Path | None:
    """Write ``tasks/<id>/MERGE.md`` for a verified merge.

    The closeout points at this file; it records the envelope, the
    implementation head, the merge commit, the verification time and the
    post-merge checks (all checks must pass on success) so a task's completion
    is evidenced by ``POST_MERGE_VERIFIED`` rather than by the merge alone.
    """
    task_id = str(env.get("task") or "")
    if not is_safe_id(task_id, TASK_ID_RE):
        return None
    tdir = task_dir(root, task_id)
    tdir.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for check in checks if check["ok"])
    verified_at = env.get("post_merge_at") or now()
    lines = [
        f"# {task_id} — Merge record", "",
        f"- Envelope: `{envelope_id}`",
        f"- Implementation head: `{env.get('implementation_head_sha') or ''}`",
        f"- Envelope head: `{env.get('envelope_head_sha') or ''}`",
        f"- Merge commit: `{env.get('merge_commit') or ''}`",
        f"- Base: `{env.get('base', 'main')}`",
        "- Status: `POST_MERGE_VERIFIED`",
        f"- Verified at: {verified_at}",
        f"- Post-merge checks: {passed}/{len(checks)}",
        "", "## Checks", "",
    ]
    lines += [f"- [{'x' if check['ok'] else ' '}] {check['name']} — {check['detail']}"
              for check in checks]
    path = tdir / "MERGE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
