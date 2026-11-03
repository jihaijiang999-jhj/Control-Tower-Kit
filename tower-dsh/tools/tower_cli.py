"""Argument parser, command table and process entry point."""
from __future__ import annotations

import tower_arch_check
import argparse
import spec_coverage
import spec_lint
from pathlib import Path
from tower_common import (
    DEFAULT_ROOT, PACKAGE_ID_RE, _force_utf8_stdio, check_package_id, emit,
    fail, git, git_ok, is_safe_id, jdump, jload, now, repo_relative,
    resolve_repository,
)
from tower_ledger import (
    LedgerLockTimeout, append_supervision_ledger, cmd_task_ids_init,
    cmd_task_ids_reserve,
)
from tower_ledger_replay import (
    ENVELOPE_ABANDONABLE_STATUSES, ENVELOPE_ABANDONED_STATUS,
    ENVELOPE_TERMINAL_STATUSES, cmd_verify_ledger, ledger_has_event,
)
from tower_task import (
    ACCEPTANCE_KINDS, ACCEPTANCE_STATUSES, cmd_spec_approve, cmd_task_new,
    cmd_task_supersede,
)
from tower_authority_cmd import (
    authority_state_check, cmd_authority_check, cmd_authority_require,
    cmd_authority_set,
)
from tower_profile import cmd_profile_check
from tower_shape import cmd_shape_check
from tower_campaign import cmd_campaign_check
from tower_dispatch import cmd_dispatch
from tower_delivery import cmd_completion_add, cmd_deliver
from tower_envelope import (
    cmd_checkback, cmd_envelope_new, cmd_queue_add, load_queue,
    load_supervision, save_queue,
)
from tower_handoff import (
    cmd_handoff_accept, cmd_handoff_activate, cmd_handoff_check, cmd_handoff_claim,
    cmd_handoff_new, cmd_handoff_receipt, cmd_handoff_status,
)
from tower_merge import cmd_merge, cmd_merge_check
from tower_arch import cmd_arch_graph
from tower_arch_check import cmd_arch_check
from tower_post_merge import (
    cmd_accept, cmd_acceptance_add, cmd_close, cmd_phase, cmd_post_merge,
    cmd_status, cmd_supervision_init, cmd_supervision_phase,
    cmd_supervision_status, cmd_task_next,
)
from tower_views import cmd_init, cmd_startup, cmd_wiring
from tower_lookup import cmd_check, cmd_hash, cmd_where
from tower_status import (
    STATUS_EVENTS, cmd_brief, cmd_status_archive, cmd_status_index,
    cmd_status_rollup, cmd_status_snapshot,
)
from tower_state_verify import cmd_state_verify


def cmd_spec_lint(root: Path, args) -> None:
    commands = set(cli_commands())
    strict = bool(getattr(args, "strict", False))
    if getattr(args, "dir", None) is None:
        # Default scan: specs/*.md plus root-level tower/policy@1 documents.
        result = spec_lint.lint_root(root, commands=commands, strict=strict)
        emit(result, 0 if result["ok"] else 2)
        return
    directory = Path(args.dir)
    if not directory.is_absolute():
        directory = root / directory
    result = spec_lint.lint_dir(
        directory,
        root=root,
        commands=commands,
        dir_label=args.dir,
        strict=strict,
    )
    emit(result, 0 if result["ok"] else 2)


def cmd_spec_coverage(root: Path, args) -> None:
    result = spec_coverage.evaluate(
        root,
        bindings_path=getattr(args, "bindings", None),
        tests_dir=getattr(args, "tests_dir", None),
    )
    emit(result, 0 if result["ok"] else 2)


ENVELOPE_ABANDON_EVENT = "ENVELOPE_ABANDON"


def abandon_actor(root: Path, args) -> str:
    """The supervisor allowed to tombstone an envelope: mirrors ``merge``.

    Healthy authority, never the primary, pinned or registered supervisor.
    """
    authority = authority_state_check(root)
    if authority["errors"]:
        fail(authority["errors"])
    pinned = (authority["merge_authority"]
              if authority["status"] == "configured" else "")
    primary_id = (jload(root / "primary" / "CURRENT_STATE.json").get("primary")
                  or {}).get("id")
    supervisor = ((load_supervision(root).get("supervisor") or {}).get("id")
                  or "")
    expected = pinned or supervisor
    by = (getattr(args, "by", None) or "").strip() or expected
    if not by:
        fail(["no supervisor identity: pass --by or register a merge authority"])
    if by == primary_id:
        fail([f"primary cannot abandon an envelope: --by {by!r} equals "
              f"primary.id {primary_id!r}"])
    if expected and by != expected:
        fail([f"only {expected!r} may abandon envelopes, request {by!r}"])
    return str(by)


def abandon_target(root: Path, envelope_id: str) -> tuple[dict, dict, dict]:
    """Read envelope/queue and reject a state that cannot be abandoned.

    Read-only, so a refusal writes nothing.  A half-written ``ABANDONED`` side
    is accepted (a retry finishes it); terminal and ``DRAFT`` states are not.
    """
    path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not path.exists():
        fail([f"envelope not found: {envelope_id}"])
    env = jload(path)
    declared = env.get("envelope_id")
    if declared != envelope_id:
        fail([f"envelope identity matches request: file declares {declared!r}, "
              f"request {envelope_id!r}"])
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries") or []
                  if isinstance(e, dict)
                  and e.get("envelope_id") == envelope_id), None)
    status, queued = env.get("status"), entry.get("status") if entry else None
    if status in ENVELOPE_TERMINAL_STATUSES or queued in ENVELOPE_TERMINAL_STATUSES:
        fail([f"envelope already {status or queued}; a merged envelope cannot "
              "be abandoned"])
    if entry is None:
        fail([f"envelope not queued: {envelope_id}"])
    if (ENVELOPE_ABANDONED_STATUS not in (status, queued)
            and (status not in ENVELOPE_ABANDONABLE_STATUSES
                 or queued not in ENVELOPE_ABANDONABLE_STATUSES)):
        fail([f"envelope status {status!r} / queue status {queued!r} cannot be "
              "abandoned (only WAITING/CORRECTION_REQUIRED/MERGE_BLOCKED/"
              "MERGING)"])
    return env, queue, entry


def cmd_envelope_abandon(root: Path, args) -> None:
    """Tombstone a failed envelope: queue + envelope + ledger, no deletes.

    Queue first, then the envelope, then the append-only ``ENVELOPE_ABANDON``
    event: every crash window is finishable, and a repeat writes nothing.
    """
    envelope_id = check_package_id(args.envelope, "envelope")
    reason = (args.reason or "").strip()
    if not reason:
        fail(["--reason must be a non-empty string"])
    by = abandon_actor(root, args)
    env, queue, entry = abandon_target(root, envelope_id)
    recorded = ledger_has_event(root, "supervision", ENVELOPE_ABANDON_EVENT,
                                envelope_id)
    if (env.get("status") == ENVELOPE_ABANDONED_STATUS
            and entry.get("status") == ENVELOPE_ABANDONED_STATUS and recorded):
        emit({"ok": True, "envelope": envelope_id,
              "status": ENVELOPE_ABANDONED_STATUS, "already": True})
        return
    entry["status"] = ENVELOPE_ABANDONED_STATUS
    save_queue(root, queue)
    env["status"] = ENVELOPE_ABANDONED_STATUS
    jdump(root / "supervision" / "envelopes" / f"{envelope_id}.json", env)
    if not recorded:
        append_supervision_ledger(root, ENVELOPE_ABANDON_EVENT, "supervision",
                                  {"envelope": envelope_id, "reason": reason,
                                   "by": by, "at": now()})
    emit({"ok": True, "envelope": envelope_id,
          "status": ENVELOPE_ABANDONED_STATUS, "by": by,
          "repaired": bool(recorded)})


def envelope_abandon_layer_parsers(
        parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-062: the ``envelope-abandon`` tombstone surface.

    Registered here, not in ``build_parser``: the PILOT-044 parser keeps its
    size, exactly like the review and acceptance layers.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        abandon = action.add_parser("envelope-abandon")
        abandon.add_argument("--envelope", required=True)
        abandon.add_argument("--reason", required=True)
        abandon.add_argument("--by", default=None,
                             help="supervisor id (default: pinned merge authority)")
    return parser


def supersede_layer_parsers(
        parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-071: the owner-only ``task-supersede`` lifecycle exit.

    Registered through the command-layer chain like the abandon/review layers,
    so ``build_parser`` keeps its frozen PILOT-044 shape.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        supersede = action.add_parser("task-supersede")
        supersede.add_argument("--task", required=True)
        supersede.add_argument("--by-task", dest="by_task", required=True)
        supersede.add_argument("--reason", required=True)
        supersede.add_argument("--by", required=True)
    return parser


def status_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-046 status commands on the PILOT-045 parser."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        snapshot = action.add_parser("status-snapshot")
        snapshot.add_argument("--task", required=True)
        snapshot.add_argument("--event", required=True,
                              choices=list(STATUS_EVENTS))
        snapshot.add_argument("--note")
        snapshot.add_argument("--tests", type=int)
        snapshot.add_argument("--at")
        action.add_parser("status-index")
        rollup = action.add_parser("status-rollup")
        rollup.add_argument("--week", required=True)
        archive = action.add_parser("status-archive")
        archive.add_argument("--before", required=True)
    return parser


def position_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-047 ``where`` command on the command-layer parser."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        where = action.add_parser("where")
        where.add_argument("--json", action="store_true",
                           help="machine view: tower/position@1 JSON only")
        where.add_argument("--md", action="store_true",
                           help="Markdown wrapper around the human view")
    return parser


def arch_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-048 ``arch-check`` / ``arch-graph`` subcommands."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        action.add_parser("arch-check")
        graph = action.add_parser("arch-graph")
        graph.add_argument("--json", action="store_true",
                           help="machine view: tower/arch-graph@1 JSON only")
    return parser


def profile_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-052 ``profile-check`` subcommand."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        check = action.add_parser("profile-check")
        check.add_argument("--file", default=None,
                           help="PROFILE path (default: state/PROFILE-TOWER-DSH.md)")
        check.add_argument("--object", default=None,
                           help="object id, read as state/PROFILE-<id>.md")
    return parser


COMMAND_LAYER_HANDLERS = {
    "campaign-check": cmd_campaign_check, "brief": cmd_brief,
    "status-snapshot": cmd_status_snapshot, "status-index": cmd_status_index,
    "status-rollup": cmd_status_rollup, "status-archive": cmd_status_archive,
    "where": cmd_where, "arch-check": cmd_arch_check,
    "arch-graph": cmd_arch_graph, "profile-check": cmd_profile_check,
    "acceptance-add": cmd_acceptance_add,
    "envelope-abandon": cmd_envelope_abandon,
    "task-supersede": cmd_task_supersede}


TASK_IDS_HANDLERS = {"task-ids-init": cmd_task_ids_init,
                     "task-ids-reserve": cmd_task_ids_reserve}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tower/DSH file-backed control-plane CLI")
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    sub.add_parser("wiring")
    sub.add_parser("startup")
    sub.add_parser("status")
    sub.add_parser("supervision-init")
    sub.add_parser("supervision-status")
    sub.add_parser("handoff-status")
    vl = sub.add_parser("verify-ledger")
    vl.add_argument("--ledger", default="all",
                    choices=["primary", "supervision", "all"])

    sub.add_parser("state-verify")
    shp = sub.add_parser("shape-check")
    shp.add_argument("--write-baseline", action="store_true")
    sub.add_parser("authority-check")
    aset = sub.add_parser("authority-set")
    aset.add_argument("--supervisor", required=True,
                      help="registered supervisor id that becomes merge authority")
    aset.add_argument("--decision", required=True,
                      help="decision id recorded in state and ledger")
    aset.add_argument("--by", required=True,
                      help="must equal primary/CURRENT_STATE.json owner.name")
    aset.add_argument("--note")

    areq = sub.add_parser("authority-require")
    areq.add_argument("--decision", required=True,
                      help="decision id recorded in the policy and ledger")
    areq.add_argument("--by", required=True,
                      help="must equal primary/CURRENT_STATE.json owner.name")
    sl = sub.add_parser("spec-lint")
    sl.add_argument("--dir", default=None,
                    help="lint one directory (default: root specs/ plus root policy docs)")
    sl.add_argument("--strict", action="store_true",
                    help="enable strict structural checks (opt-in)")

    sc = sub.add_parser("spec-coverage")
    sc.add_argument("--bindings", default=None,
                    help="bindings module (default: tools/tests/clause_bindings.py)")
    sc.add_argument("--tests-dir", default=None,
                    help="test directory to scan (default: tools/tests)")

    hn = sub.add_parser("handoff-new")
    hn.add_argument("--package", required=True)
    hn.add_argument("--task", help="task id to capture (default: derived selection)")
    hn.add_argument("--envelope", help="merge-queue envelope id (default: derived selection)")

    hc = sub.add_parser("handoff-check")
    hc.add_argument("--package", required=True)

    hcl = sub.add_parser("handoff-claim")
    hcl.add_argument("--package", required=True)
    hcl.add_argument("--controller", required=True)

    ha = sub.add_parser("handoff-accept")
    ha.add_argument("--package", required=True)
    ha.add_argument("--controller", required=True)

    hr = sub.add_parser("handoff-receipt")
    hr.add_argument("--package", required=True)
    hr.add_argument("--controller", required=True)
    hr.add_argument("--note")

    hv = sub.add_parser("handoff-activate")
    hv.add_argument("--package", required=True)
    hv.add_argument("--controller", required=True)

    sp = sub.add_parser("supervision-phase")
    sp.add_argument("--phase", required=True)
    sp.add_argument("--next")

    en = sub.add_parser("envelope-new")
    en.add_argument("--task", required=True)
    en.add_argument("--file", required=True)

    qa = sub.add_parser("queue-add")
    qa.add_argument("--envelope", required=True)

    mc = sub.add_parser("merge-check")
    mc.add_argument("--envelope", required=True)

    mg = sub.add_parser("merge")
    mg.add_argument("--envelope", required=True)
    mg.add_argument("--role", required=True, choices=["supervisor"])
    mg.add_argument("--supervisor", required=True)
    mg.add_argument("--mode", default="local", choices=["local", "pr"],
                    help="local merge (default) or PR-mode merge through gh")
    mg.add_argument("--remote", default="origin",
                    help="git remote used by --mode pr (default: origin)")
    mg.add_argument("--check-timeout", dest="check_timeout", type=int, default=900,
                    help="seconds bounding every gh step of a PR merge: "
                         "auth status, pr create, pr view, pr checks and "
                         "pr merge (default: 900)")
    mg.add_argument("--check-interval", dest="check_interval", type=int, default=10,
                    help="seconds between retries while a new PR reports no "
                         "checks yet, within --check-timeout (default: 10)")

    pm = sub.add_parser("post-merge")
    pm.add_argument("--envelope", required=True, help="envelope id; the file is looked up at the repository root for a branch-side envelope and under the tower root for a base-side one")
    pm.add_argument("--result", default="PASS", choices=["PASS", "FAIL"])
    pm.add_argument("--note")

    ph = sub.add_parser("phase")
    ph.add_argument("--phase", required=True)
    ph.add_argument("--next")

    t = sub.add_parser("task-new")
    t.add_argument("--spec", required=True)

    tn = sub.add_parser("task-next")
    tn.add_argument("--task", required=True)
    tn.add_argument("--next", required=True)

    c = sub.add_parser("check")
    c.add_argument("--task", required=True)
    c.add_argument("--phase", required=True,
                   choices=["spec", "ready", "dispatch", "deliver", "review", "accept", "close"])

    sa = sub.add_parser("spec-approve")
    sa.add_argument("--task", required=True)
    sa.add_argument("--by", required=True)
    sa.add_argument("--note")

    h = sub.add_parser("hash")
    h.add_argument("path")

    d = sub.add_parser("dispatch")
    d.add_argument("--task", required=True)
    d.add_argument("--executor", required=True)
    d.add_argument("--worktree")
    d.add_argument("--kind", default="subagent",
                   help="executor kind recorded as provenance (default: subagent)")
    d.add_argument("--model", default=None,
                   help="model id recorded as provenance (optional)")
    d.add_argument("--parent", default=None,
                   help="parent session/agent id recorded as provenance (optional)")

    de = sub.add_parser("deliver")
    de.add_argument("--task", required=True)
    de.add_argument("--evidence", action="append", required=True)

    ca = sub.add_parser("completion-add")
    ca.add_argument("--task", required=True)
    ca.add_argument("--path", required=True,
                    help="tower-root-relative path the branch legitimately needs")
    ca.add_argument("--by", required=True,
                    help="must equal primary/CURRENT_STATE.json owner.name")
    ca.add_argument("--reason", required=True)
    ca.add_argument("--decision", required=True)

    cb = sub.add_parser("checkback")
    cb.add_argument("--task", required=True)
    cb.add_argument("--reviewer", required=True)
    cb.add_argument("--verdict", required=True, choices=["PASS", "FAIL"])
    cb.add_argument("--note")
    cb.add_argument("--structure", help="reviewer answers to the five structure questions")

    ac = sub.add_parser("accept")
    ac.add_argument("--task", required=True)
    ac.add_argument("--decision", required=True)
    ac.add_argument("--note")

    cl = sub.add_parser("close")
    cl.add_argument("--task", required=True)
    return command_layer_parsers(p)


def dispatch_campaign_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-050: add ``--campaign`` to the existing ``dispatch`` subparser.

    The argument is registered here, not in ``build_parser``, so the frozen
    PILOT-044 parser keeps its shape while the command layer grows the
    dispatch surface.  Returns ``parser`` so the caller can keep chaining.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        dispatch = action.choices.get("dispatch")
        if dispatch is not None:
            dispatch.add_argument(
                "--campaign", default=None,
                help="campaign id this dispatch belongs to (required while a "
                     "single campaign is active)")
    return parser


def task_ids_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-057 id-registry subcommands.

    ``build_parser`` and the PILOT-044/045 command layer keep their frozen
    shape; this layer owns only its own two subcommands and returns ``parser``
    so the caller can keep chaining.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        action.add_parser("task-ids-init")
        reserve = action.add_parser("task-ids-reserve")
        reserve.add_argument("--id", required=True)
        reserve.add_argument("--title", required=True)
        reserve.add_argument("--spec", default=None)
    return parser


def review_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-058: the structured-review flags on the existing ``checkback``.

    ``build_parser`` is frozen at its PILOT-044 size, so the new arguments are
    registered here, the same way ``dispatch_campaign_parser`` grows dispatch.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        checkback = action.choices.get("checkback")
        if checkback is not None:
            checkback.add_argument("--head", default=None,
                                   help="reviewed head (default: worktree HEAD)")
            checkback.add_argument("--base", default=None,
                                   help="reviewed base (default: dispatch.base_sha)")
            checkback.add_argument("--scope", action="append", default=[],
                                   help="reviewed path (repeatable)")
            checkback.add_argument("--finding", action="append", default=[],
                                   help="review finding (repeatable)")
    return parser


def base_sync_layer_parsers(
        parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-067: the ``--allow-state-ahead`` flag on the existing ``merge``.

    Same layering as the review flags: ``build_parser`` keeps its PILOT-044
    size, and this layer owns only the one explicit, audited escape hatch for a
    base branch that advanced with state-only changes.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        merge = action.choices.get("merge")
        if merge is not None:
            merge.add_argument(
                "--allow-state-ahead", dest="allow_state_ahead",
                action="store_true",
                help="allow an audited --admin merge when the base advanced "
                     "with state-only paths only (ledger/primary/supervision/"
                     "tasks/state/merge-envelopes)")
    return parser


# PILOT-067: the base-sync policy behind ``merge --mode pr``.  The tower root
# usually lives in a sub-directory of the merge repository ("repository": ".."),
# so base-only paths are classified after stripping that prefix; anything
# outside it is code/docs by default.
# PILOT-068: ``merge-envelopes/`` joins the whitelist.  A base-side envelope is
# committed straight to the base branch before the PR exists (063/065/066/067),
# so its appearance is state, not a code change; without this entry the
# audited ``--allow-state-ahead`` path could never be used for its own envelope.
STATE_ONLY_PREFIXES = ("ledger/", "primary/", "supervision/", "tasks/", "state/",
                       "merge-envelopes/")


def tower_repo_prefix(root: Path, repo: Path) -> str:
    """Repo-relative prefix of the tower root (``""`` when they coincide)."""
    relative = repo_relative(repo, root)
    return f"{relative}/" if relative else ""


def classify_base_paths(paths: list[str], prefix: str) -> tuple[list[str], list[str]]:
    """Split base-only paths into ``(state_only, code_docs)``.

    A path is state-only only when it sits under the tower prefix and its
    tower-relative spelling starts with :data:`STATE_ONLY_PREFIXES` (the
    primary/supervision ledgers and state, plus the base-side
    ``merge-envelopes/``); every other path -- tools, arch, EVENT_CATALOG.json,
    pilot, root docs, or anything outside the tower -- is code/docs.  The
    default is the strict side, so an unclassifiable path can never earn
    ``--admin``.
    """
    state: list[str] = []
    code: list[str] = []
    for raw in paths:
        path = str(raw).replace("\\", "/")
        inside = path[len(prefix):] if path.startswith(prefix) else ""
        if any(inside.startswith(name) for name in STATE_ONLY_PREFIXES):
            state.append(path)
        else:
            code.append(path)
    return state, code


def base_ahead_paths(repo: Path, impl_head: str, base: str = "main",
                     remote: str = "origin") -> list[str]:
    """Repo-relative paths ``<remote>/<base>`` gained after the fork point.

    PILOT-070: the fork point is ``merge-base(impl_head, tip)`` of the
    envelope's *implementation* head, never the current ``HEAD``.  At merge time
    the checkout is the base branch, so ``HEAD`` and ``origin/main`` are usually
    the same commit: a ``HEAD``-based merge-base makes ``mb == tip`` and the
    base-ahead policy can never see (or audit) the base-only state commits it
    exists for.  Using the implementation head instead answers the real
    question -- what did the base gain after the implementation forked? -- and
    branch-only code stays out of the diff by construction.

    The fetch is what makes the answer current: a stale remote-tracking ref
    could hide a code change and wrongly classify the base as state-only.  Any
    git failure (offline remote, no such branch, unknown implementation head)
    yields ``[]``: the policy stays dormant and the merge keeps its original
    up-to-date semantics, so an unverified base can never earn ``--admin``.
    """
    if not impl_head:
        return []
    if git(repo, "fetch", "--quiet", remote, base).returncode != 0:
        return []
    try:
        tip = git_ok(repo, "rev-parse", "FETCH_HEAD")
        common = git_ok(repo, "merge-base", impl_head, tip)
        if common == tip:
            return []
        changed = git_ok(repo, "diff", "--name-only", common, tip)
    except Exception:
        return []
    return [line.strip() for line in changed.splitlines() if line.strip()]


def merge_envelope_for_gate(root: Path, args) -> dict | None:
    """The envelope a ``merge --mode pr`` request names, or ``None``.

    Only a request that ``cmd_merge`` could actually merge qualifies: same
    envelope id, not already resumed or merged.  Anything else is left for
    ``cmd_merge`` to report, so the preflight never replaces the merge gate's
    own verdict.
    """
    if (getattr(args, "mode", "local") or "local") != "pr":
        return None
    envelope_id = str(getattr(args, "envelope", "") or "")
    path = root / "supervision" / "envelopes" / f"{envelope_id}.json"
    if not is_safe_id(envelope_id, PACKAGE_ID_RE) or not path.is_file():
        return None
    try:
        env = jload(path)
    except (OSError, ValueError):
        return None
    if not isinstance(env, dict) or env.get("envelope_id") != envelope_id:
        return None
    if env.get("remote_merged") is True or env.get("status") in ENVELOPE_TERMINAL_STATUSES:
        return None
    return env


def base_sync_env(root: Path, args) -> dict | None:
    """The envelope to classify, when the checkout is its base branch too."""
    env = merge_envelope_for_gate(root, args)
    if env is None:
        return None
    try:
        current = git_ok(resolve_repository(root, env.get("repository")),
                         "rev-parse", "--abbrev-ref", "HEAD")
    except Exception:
        return None
    return env if current == str(env.get("base", "main")) else None


def base_sync_audit(root: Path, args) -> dict:
    """PILOT-067/070: refuse or audit ``merge --mode pr`` when the base advanced.

    The base-ahead comparison starts at the envelope's
    ``implementation_head_sha`` (PILOT-070): the current checkout is the base
    branch, so ``HEAD`` describes the base tip, not the implementation.  A
    missing or unresolvable implementation head is a fail-closed exit 2 -- never
    a silent fallback to ``HEAD``, which is exactly the bug that made
    ``base_ahead_paths`` return ``[]`` for every real merge.

    Returns the audit payload (``{}`` when the base did not move) that
    ``cmd_merge`` persists into the envelope and both merge records, and that
    ``pr_merge_argv`` requires before it may add ``--admin``.  A base that moved
    with code/docs exits 2 even with ``--allow-state-ahead``; a state-only base
    without the flag exits 2 too.  Nothing is written before either refusal, so
    the queue, the envelope and both ledgers stay untouched.
    """
    env = base_sync_env(root, args)
    if env is None:
        return {}
    base = str(env.get("base", "main"))
    remote = getattr(args, "remote", None) or "origin"
    repo = resolve_repository(root, env.get("repository"))
    impl_head = env.get("implementation_head_sha")
    if not isinstance(impl_head, str) or not impl_head.strip():
        fail([f"envelope {args.envelope} has no implementation_head_sha; "
              "base-ahead is computed from the envelope implementation head "
              "and never falls back to HEAD"])
    impl_head = impl_head.strip()
    try:
        git_ok(repo, "rev-parse", "--verify", f"{impl_head}^{{commit}}")
    except Exception:
        fail([f"envelope implementation_head_sha {impl_head!r} is not a "
              f"resolvable commit in {repo}; base-ahead is computed from the "
              "envelope implementation head and never falls back to HEAD"])
    ahead = base_ahead_paths(repo, impl_head, base, remote)
    if not ahead:
        return {}
    state, code = classify_base_paths(ahead, tower_repo_prefix(root, repo))
    if code:
        fail([f"base {remote}/{base} advanced with code/docs changes: "
              f"{', '.join(code)}; run 'git rebase {remote}/{base}', update the "
              f"envelope implementation_head_sha and the review head, and "
              f"re-run review; --admin is never allowed for code/docs"])
    if not getattr(args, "allow_state_ahead", False):
        fail([f"base {remote}/{base} advanced with state-only changes: "
              f"{', '.join(state)}; pass --allow-state-ahead to merge with an "
              f"audited --admin, or rebase onto {remote}/{base}"])
    return {"base_sync": "state-only", "base_ahead_paths": state, "admin": True}


def cmd_merge_with_base_sync(root: Path, args) -> None:
    """PILOT-067: run the base-sync preflight, then the real merge.

    The preflight is read-only, so a refusal leaves the queue, the envelope and
    both ledgers exactly as it found them.  The audit it hands over through
    ``args`` is the only thing that can make ``gh pr merge`` use ``--admin``.
    """
    args.base_sync_audit = base_sync_audit(root, args)
    cmd_merge(root, args)


def acceptance_layer_parsers(
        parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-059: the ``acceptance-add`` command and accept's manual flag.

    Same layering as ``review_layer_parsers``: ``build_parser`` keeps its
    PILOT-044 size, and this layer owns only its own surface.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        accept = action.choices.get("accept")
        if accept is not None:
            accept.add_argument(
                "--allow-manual-pending", action="store_true",
                help="owner decision to leave manual items pending (each needs a note)")
        add = action.add_parser("acceptance-add")
        add.add_argument("--task", required=True)
        add.add_argument("--id", required=True)
        add.add_argument("--kind", required=True, choices=list(ACCEPTANCE_KINDS))
        add.add_argument("--status", required=True,
                         choices=list(ACCEPTANCE_STATUSES))
        add.add_argument("--note", default="")
        add.add_argument("--replace", action="store_true",
                         help="update an existing id (kind may not change)")
    return parser


def envelope_base_side_layer_parsers(
        parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """PILOT-063: the ``--base-side`` flag on the existing ``envelope-new``.

    The envelope commit lives on the base branch, so this layer registers only
    the flag; ``build_parser`` keeps its PILOT-044 size.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        envelope_new = action.choices.get("envelope-new")
        if envelope_new is not None:
            envelope_new.add_argument(
                "--base-side", dest="base_side", action="store_true",
                help="envelope commit is on base; the implementation branch "
                     "carries only code")
    return parser


def command_layer_parsers(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the PILOT-045 commands on the parser built by ``build_parser``.

    The base parser stays at its PILOT-044 size on purpose: ``shape-check``
    freezes every existing function in ``state/SHAPE-BASELINE.json``, so the
    command layer adds its subcommands here instead of growing
    ``build_parser``.  Returns ``parser`` so ``build_parser`` can tail-call it.
    """
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        cc = action.add_parser("campaign-check")
        cc.add_argument("--strict", action="store_true",
                        help="treat warnings (W1/W2) as errors")
        action.add_parser("brief")
    dispatch_campaign_parser(parser)
    review_layer_parsers(parser)
    return base_sync_layer_parsers(envelope_base_side_layer_parsers(envelope_abandon_layer_parsers(supersede_layer_parsers(profile_layer_parsers(
        arch_layer_parsers(position_layer_parsers(status_layer_parsers(acceptance_layer_parsers(task_ids_layer_parsers(parser))))))))))


def cli_commands() -> list[str]:
    """Every registered towerctl subcommand, derived from build_parser()."""
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    return []


def main() -> None:
    args = build_parser().parse_args()
    _force_utf8_stdio()
    root = Path(args.root).resolve()
    if not root.exists():
        fail([f"root not found: {root}"])
    handlers = {**COMMAND_LAYER_HANDLERS, **TASK_IDS_HANDLERS,
        "init": cmd_init, "wiring": cmd_wiring, "startup": cmd_startup,
        "status": cmd_status, "phase": cmd_phase, "task-new": cmd_task_new, "check": cmd_check,
        "spec-approve": cmd_spec_approve,
        "task-next": cmd_task_next,
        "hash": cmd_hash, "dispatch": cmd_dispatch, "deliver": cmd_deliver,
        "completion-add": cmd_completion_add,
        "checkback": cmd_checkback, "accept": cmd_accept, "close": cmd_close,
        "supervision-init": cmd_supervision_init, "supervision-status": cmd_supervision_status,
        "supervision-phase": cmd_supervision_phase,
        "handoff-new": cmd_handoff_new, "handoff-check": cmd_handoff_check,
        "handoff-claim": cmd_handoff_claim, "handoff-accept": cmd_handoff_accept,
        "handoff-receipt": cmd_handoff_receipt, "handoff-activate": cmd_handoff_activate,
        "handoff-status": cmd_handoff_status,
        "envelope-new": cmd_envelope_new, "queue-add": cmd_queue_add,
        "merge-check": cmd_merge_check, "merge": cmd_merge_with_base_sync, "post-merge": cmd_post_merge,
        "verify-ledger": cmd_verify_ledger,
        "state-verify": cmd_state_verify,
        "authority-check": cmd_authority_check,
        "authority-set": cmd_authority_set,
        "authority-require": cmd_authority_require,
        "spec-lint": cmd_spec_lint,
        "spec-coverage": cmd_spec_coverage, "shape-check": cmd_shape_check,
    }
    try:
        handlers[args.cmd](root, args)
    except LedgerLockTimeout as exc:
        fail([str(exc)])


# The parser owns the command list; arch-check reads it through this
# registry so the domain layer never imports the entry layer.
tower_arch_check.CLI_COMMANDS = set(cli_commands())
