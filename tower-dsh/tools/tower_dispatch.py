"""Dispatch: provenance, base sha and dependency scheduling."""
from __future__ import annotations

from pathlib import Path
from tower_common import emit, ensure_within, fail, git, now, rel
from tower_ledger import append_ledger, task_dir
from tower_ledger_replay import ledger_payloads_by_task
from tower_task import (
    DEPENDS_ON_CLOSED, dependency_target_status, load_record, read_task_records,
    save_record, spec_gate_errors, update_board,
)
from tower_command import scalar_items
from tower_authority import authority_repo
from tower_campaign import load_campaign_docs


def dependency_closure_errors(root: Path, rec: dict) -> list[str]:
    """Scheduling gate: every recorded dependency must already be ``closed``.

    A missing target is reported as ``depends_on.<id>: missing``; every other
    unmet state keeps its own name, so an operator can tell "not merged yet"
    from "card was voided".
    """
    errors: list[str] = []
    for raw in rec.get("depends_on") or []:
        dep = raw.strip() if isinstance(raw, str) else ""
        status = dependency_target_status(root, dep)
        if status is None:
            errors.append(f"depends_on.{dep}: missing")
        elif status != DEPENDS_ON_CLOSED:
            errors.append(f"depends_on.{dep}: {status} (unmet)")
    return errors


def dependency_cycle_errors(root: Path) -> list[str]:
    """DFS every live card's ``depends_on``; a cycle (self included) is fatal.

    The graph is read from records, never from the board: a board-only target
    has no outgoing edges.  The message names the cycle in visit order
    (``A -> B -> A``), which is enough to locate the loop without a graph dump.
    """
    graph: dict[str, list[str]] = {}
    for record in read_task_records(root):
        deps = [item.strip() for item in (record.get("depends_on") or [])
                if isinstance(item, str) and item.strip()]
        graph[str(record.get("id"))] = deps
    visiting: set[str] = set()
    done: set[str] = set()
    path: list[str] = []

    def walk(node: str) -> list[str] | None:
        if node in done:
            return None
        if node in visiting:
            return path[path.index(node):] + [node]
        visiting.add(node)
        path.append(node)
        for dep in graph.get(node, []):
            cycle = walk(dep)
            if cycle:
                return cycle
        path.pop()
        visiting.discard(node)
        done.add(node)
        return None

    for node in sorted(graph):
        cycle = walk(node)
        if cycle:
            return [f"depends_on.cycle: {' -> '.join(cycle)}"]
    return []


def scheduling_dependency_errors(root: Path, rec: dict) -> list[str]:
    """Ready/dispatch gate: dependencies closed and the whole graph acyclic."""
    return dependency_closure_errors(root, rec) + dependency_cycle_errors(root)


def dispatch_provenance_field(value, label: str) -> str | None:
    """Normalise an optional provenance flag: absent -> None, empty -> exit 2.

    ``--model`` and ``--parent`` are optional, but passing them with an empty
    (or whitespace-only) value is a caller mistake: silently recording nothing
    would erase the provenance the flag exists to capture.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        fail([f"{label} must be a non-empty string when given"])
    return text


def _dispatch_base_sha(rec: dict) -> str | None:
    """The recorded immutable deliver baseline, or None for a legacy record."""
    dispatch = rec.get("dispatch")
    if not isinstance(dispatch, dict):
        return None
    value = dispatch.get("base_sha")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _payload_base_sha(payload: dict | None) -> str | None:
    """The non-empty ``base_sha`` of one DISPATCH payload, or None."""
    raw = payload.get("base_sha") if isinstance(payload, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def deliver_dispatch_base_sha(root: Path, rec: dict) -> str | None:
    """PILOT-043 R1: the latest DISPATCH payload is the only diff baseline.

    ``record.dispatch.base_sha`` is a working copy, so an attacker could set it
    to ``HEAD`` (emptying the deliver diff) and restore it afterwards.  The
    ledger event is the authority: a record value that disagrees with (or is
    unbacked by) the latest ``DISPATCH`` payload aborts before any diff or
    write.  Two empty halves stay legacy (the ``merge-base main HEAD`` path in
    :func:`deliver_scope`); when the event has a value it is returned so the
    caller can pass the *event* value, not the record value, to the diff.
    """
    events = ledger_payloads_by_task(root, "DISPATCH").get(
        str(rec.get("id") or ""), [])
    event_sha = _payload_base_sha(events[-1] if events else None)
    recorded = _dispatch_base_sha(rec)
    if event_sha is None:
        if recorded is not None:
            fail([f"dispatch base_sha does not match DISPATCH event: record "
                  f"{recorded!r} is not backed by a DISPATCH event"])
        return None
    if recorded != event_sha:
        fail([f"dispatch base_sha does not match DISPATCH event: record "
              f"{recorded!r} != event {event_sha!r}"])
    return event_sha


def dispatch_base_sha(root: Path, worktree: Path) -> str | None:
    """``git rev-parse main`` of the tower repository, or None.

    PILOT-042 anchors every dispatch to the base commit the branch was cut
    from, so ``deliver`` does not depend on a mutable local ``main`` ref.  A
    tower outside git (fixtures / legacy) simply records ``None``: that must
    not block a dispatch, it only selects the 041 fallback at deliver time.
    """
    candidates: list[Path] = []
    repo = authority_repo(root)
    if repo is not None:
        candidates.append(repo)
    candidates.append(worktree)
    for candidate in candidates:
        cp = git(candidate, "rev-parse", "--verify", "main^{commit}")
        if cp.returncode == 0:
            sha = cp.stdout.strip()
            if sha:
                return sha
    return None


def resolve_dispatch_worktree(root: Path, args, rec: dict) -> tuple[str, Path]:
    """Resolve the dispatch worktree before any state is written."""
    worktree = args.worktree or rec.get("worktree")
    if not worktree:
        fail(["worktree missing: (empty)"])
    path = ensure_within(root, root / worktree, label="worktree")
    if not path.exists():
        fail([f"worktree missing: {worktree}"])
    return worktree, path


def dispatch_campaign(root: Path, requested: str | None, task_id: str) -> str | None:
    """The campaign a dispatch joins; every check runs before any write.

    A tower with no active campaign keeps the legacy behaviour: the flag stays
    optional, but when it is given it must still name an active campaign whose
    roadmap contains the card.  Exactly one active campaign makes the flag
    mandatory; more than one is ambiguous and no dispatch may proceed.
    """
    docs, errors = load_campaign_docs(root)
    if errors:
        fail([f"campaign unreadable: {item['target']}: {item['detail']}"
              for item in errors])
    active = [doc for doc in docs if doc.get("status") == "active"]
    if len(active) > 1:
        ids = ", ".join(str(doc.get("id") or doc["_path"]) for doc in active)
        fail([f"ambiguous campaign: {len(active)} active campaigns ({ids}); "
              "retire all but one before dispatch"])
    chosen = (requested or "").strip() or None
    if chosen is None:
        if not active:
            return None
        fail([f"--campaign is required: {active[0].get('id')} is active"])
    doc = next((item for item in docs if str(item.get("id") or "") == chosen), None)
    if doc is None:
        fail([f"unknown campaign: {chosen}"])
    if doc.get("status") != "active":
        fail([f"campaign is not active: {chosen} ({doc.get('status')})"])
    if task_id not in scalar_items(doc.get("roadmap")):
        fail([f"task {task_id} is not in the roadmap of campaign {chosen}"])
    return chosen


def cmd_dispatch(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in ("ready", "rework", "dispatched"):
        fail([f"task status {rec.get('status')} cannot dispatch"])
    worktree, worktree_path = resolve_dispatch_worktree(root, args, rec)
    task_md = task_dir(root, args.task) / "TASK.md"
    if not task_md.exists():
        fail([f"TASK.md missing: {rel(root, task_md)}; cannot dispatch without a task card"])
    gate_errors = spec_gate_errors(root, rec) + scheduling_dependency_errors(root, rec)
    if gate_errors:
        fail(gate_errors)
    kind = dispatch_provenance_field(args.kind, "kind")
    if kind is None:
        fail(["kind must be a non-empty string"])
    model = dispatch_provenance_field(args.model, "model")
    parent = dispatch_provenance_field(args.parent, "parent")
    campaign = dispatch_campaign(root, args.campaign, args.task)
    dispatch = {"executor": args.executor, "worktree": worktree, "at": now(),
                "kind": kind, "model": model, "parent": parent,
                "base_sha": dispatch_base_sha(root, worktree_path)}
    if campaign:
        dispatch["campaign"] = campaign
    rec["executor"] = args.executor
    rec["dispatch"] = dispatch
    rec["status"] = "dispatched"
    rec["next"] = "等待 executor 交付"
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "DISPATCH", "primary", {"task": args.task, **dispatch})
    emit({"ok": True, "task": args.task, "status": rec["status"], "executor": args.executor,
          "worktree": worktree})


def _dispatch_base_sha_drift(task_id: str, record: dict,
                             events: list[dict]) -> list[dict]:
    """PILOT-043: compare ``record.dispatch.base_sha`` with its DISPATCH event.

    The event half is the authority: a non-empty record value must equal the
    latest ``DISPATCH`` payload's ``base_sha`` (``dispatch_base_mismatch``), and
    an event value the record dropped is ``dispatch_base_missing``.  Two empty
    halves are a legacy record and yield no row, so old towers verify clean.
    """
    recorded = _dispatch_base_sha(record)
    event_sha = _payload_base_sha(events[-1] if events else None)
    if recorded is None and event_sha is None:
        return []
    if recorded is None:
        return [{"kind": "dispatch_base_missing", "target": task_id,
                 "expected": event_sha, "actual": None}]
    if event_sha != recorded:
        return [{"kind": "dispatch_base_mismatch", "target": task_id,
                 "expected": event_sha, "actual": recorded}]
    return []
