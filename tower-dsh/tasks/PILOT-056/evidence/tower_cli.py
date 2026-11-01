"""Argument parser, command table and process entry point."""
from __future__ import annotations

import tower_arch_check
import argparse
import spec_coverage
import spec_lint
from pathlib import Path
from tower_common import DEFAULT_ROOT, _force_utf8_stdio, emit, fail
from tower_ledger import LedgerLockTimeout, cmd_task_ids_init, cmd_task_ids_reserve
from tower_ledger_replay import cmd_verify_ledger
from tower_task import (
    ACCEPTANCE_KINDS, ACCEPTANCE_STATUSES, cmd_spec_approve, cmd_task_new,
)
from tower_authority_cmd import (
    cmd_authority_check, cmd_authority_require, cmd_authority_set,
)
from tower_profile import cmd_profile_check
from tower_shape import cmd_shape_check
from tower_campaign import cmd_campaign_check
from tower_dispatch import cmd_dispatch
from tower_delivery import cmd_completion_add, cmd_deliver
from tower_envelope import cmd_checkback, cmd_envelope_new, cmd_queue_add
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
    "acceptance-add": cmd_acceptance_add}


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
    pm.add_argument("--envelope", required=True)
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
    return profile_layer_parsers(arch_layer_parsers(position_layer_parsers(
        status_layer_parsers(acceptance_layer_parsers(task_ids_layer_parsers(parser))))))


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
        "merge-check": cmd_merge_check, "merge": cmd_merge, "post-merge": cmd_post_merge,
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
