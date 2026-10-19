#!/usr/bin/env python3
"""Tower/DSH v0.3 pilot control-plane CLI.

File-backed, local-only, no network. It records state, evidence and gates;
it never executes the task itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def jdump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def emit(data: dict, code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(errors: list[str], **extra) -> None:
    payload = {"ok": False, "errors": errors}
    payload.update(extra)
    emit(payload, 2)


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


GENESIS_PREV_HASH = "GENESIS"
LEDGER_FILES = {"primary": "primary.jsonl", "supervision": "supervision.jsonl"}
LEDGER_LOCK_TIMEOUT = 10.0
LEDGER_LOCK_STALE_AFTER = 60.0
LEDGER_LOCK_POLL_INTERVAL = 0.05


class LedgerLockTimeout(RuntimeError):
    """Raised when the single-writer ledger lock cannot be acquired in time."""


def canonical_event_bytes(event: dict) -> bytes:
    """Canonical bytes hashed for an event.

    The ``hash`` field itself is excluded; every other field (including
    ``prev_hash``) is serialised as compact, key-sorted, non-ASCII-escaped
    JSON and encoded as UTF-8.
    """
    body = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def event_hash(event: dict) -> str:
    return hashlib.sha256(canonical_event_bytes(event)).hexdigest()


def ledger_rows(path: Path) -> list[bytes]:
    """Raw content bytes of each non-blank JSONL row, terminator excluded.

    Only ``\\n`` (optionally preceded by ``\\r``) is treated as a row
    terminator; ``bytes.splitlines`` is deliberately avoided because UTF-8
    continuation bytes such as ``0x85`` would be misread as line breaks.
    """
    if not path.exists():
        return []
    data = path.read_bytes()
    if not data:
        return []
    raw_rows = data.split(b"\n")
    if raw_rows and raw_rows[-1] == b"":
        raw_rows.pop()
    rows = []
    for raw in raw_rows:
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        if raw.strip():
            rows.append(raw)
    return rows


def legacy_anchor(raw_row: bytes) -> str:
    """SHA-256 of a legacy row's raw content bytes (no hash on that row)."""
    return hashlib.sha256(raw_row).hexdigest()


def parse_ledger_row(raw_row: bytes):
    """Parse a raw ledger row, returning ``None`` when it is not valid JSON."""
    try:
        event = json.loads(raw_row.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


def prev_hash_for_rows(rows: list[bytes]) -> str:
    """prev_hash for the next event given the existing rows of a ledger."""
    if not rows:
        return GENESIS_PREV_HASH
    last = parse_ledger_row(rows[-1])
    if last is not None:
        recorded = last.get("hash")
        if isinstance(recorded, str) and recorded:
            return recorded
    return legacy_anchor(rows[-1])


def ledger_lock_path(root: Path) -> Path:
    return root / "ledger" / ".lock"


def _clear_stale_lock(path: Path, stale_after: float) -> bool:
    """Remove an over-age lock file; returns True when the caller may retry."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return True
    if time.time() - stat.st_mtime <= stale_after:
        return False
    # Displace atomically so two waiters cannot both break the same lock.
    displaced = path.with_name(f"{path.name}.stale.{os.getpid()}.{time.time_ns()}")
    try:
        os.replace(path, displaced)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        displaced.unlink()
    except OSError:
        pass
    print(f"warning: removed stale ledger lock {path}", file=sys.stderr)
    return True


def _acquire_lock_file(path: Path, timeout: float, stale_after: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            fd = None
        if fd is not None:
            try:
                os.write(fd, f"pid={os.getpid()} at={now()}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return
        if _clear_stale_lock(path, stale_after):
            continue
        if time.monotonic() >= deadline:
            raise LedgerLockTimeout(
                f"ledger write lock busy for more than {timeout:g}s: {path}")
        time.sleep(LEDGER_LOCK_POLL_INTERVAL)


def _release_lock_file(path: Path, identity) -> None:
    try:
        current = path.stat()
    except FileNotFoundError:
        return
    if identity is not None and (current.st_dev, current.st_ino) != (
            identity.st_dev, identity.st_ino):
        # The lock was broken and re-taken by somebody else; leave it alone.
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def ledger_lock(root: Path, timeout: float | None = None,
                stale_after: float | None = None):
    """Single-writer lock around the read-max(seq)+append critical section."""
    path = ledger_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = LEDGER_LOCK_TIMEOUT if timeout is None else timeout
    stale = LEDGER_LOCK_STALE_AFTER if stale_after is None else stale_after
    _acquire_lock_file(path, limit, stale)
    try:
        identity = path.stat()
    except FileNotFoundError:
        identity = None
    try:
        yield path
    finally:
        _release_lock_file(path, identity)


def _append_ledger_event(root: Path, filename: str, event_type: str,
                         actor: str, payload: dict) -> dict:
    ledger = root / "ledger" / filename
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(root):
        rows = ledger_rows(ledger)
        seq = 0
        for raw in rows:
            parsed = parse_ledger_row(raw)
            if parsed is None:
                continue
            try:
                seq = max(seq, int(parsed.get("seq", 0)))
            except (TypeError, ValueError):
                continue
        event = {
            "seq": seq + 1,
            "at": now(),
            "type": event_type,
            "actor": actor,
            "payload": payload,
            "prev_hash": prev_hash_for_rows(rows),
        }
        event["hash"] = event_hash(event)
        # Binary append keeps the line terminator LF on every platform.
        with ledger.open("ab") as fh:
            fh.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
    return event


def append_ledger(root: Path, event_type: str, actor: str, payload: dict) -> dict:
    return _append_ledger_event(root, LEDGER_FILES["primary"], event_type, actor, payload)


def append_supervision_ledger(root: Path, event_type: str, actor: str,
                              payload: dict) -> dict:
    return _append_ledger_event(root, LEDGER_FILES["supervision"], event_type, actor, payload)


def task_dir(root: Path, tid: str) -> Path:
    return root / "tasks" / tid


def task_record_path(root: Path, tid: str) -> Path:
    return task_dir(root, tid) / "record.json"


def load_record(root: Path, tid: str) -> dict:
    path = task_record_path(root, tid)
    if not path.exists():
        fail([f"task record missing: {rel(root, path)}"])
    return jload(path)


def save_record(root: Path, record: dict) -> None:
    record["updated_at"] = now()
    jdump(task_record_path(root, record["id"]), record)


def load_board(root: Path) -> dict:
    path = root / "primary" / "TASK_BOARD.json"
    if path.exists():
        return jload(path)
    return {"schema": "tower/task-board@1", "tower_id": "tower-dsh", "tasks": []}


def save_board(root: Path, board: dict) -> None:
    board["updated_at"] = now()
    jdump(root / "primary" / "TASK_BOARD.json", board)


def update_board(root: Path, record: dict) -> None:
    board = load_board(root)
    entry = {
        "id": record["id"],
        "title": record["title"],
        "status": record["status"],
        "authority": record.get("authority"),
        "executor": record.get("executor"),
        "reviewer": (record.get("review") or {}).get("reviewer"),
        "next": record.get("next", ""),
        "updated_at": record.get("updated_at", now()),
    }
    tasks = [t for t in board.get("tasks", []) if t.get("id") != record["id"]]
    tasks.append(entry)
    board["tasks"] = tasks
    save_board(root, board)


def resolve_input(root: Path, value: str) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    cand = root / p
    return cand if cand.exists() else p.resolve()


def check_evidence(root: Path, record: dict) -> list[str]:
    errors: list[str] = []
    evidence = record.get("evidence") or []
    if not evidence:
        errors.append("no evidence recorded")
    for e in evidence:
        path = root / e.get("path", "")
        if not e.get("path") or not path.exists():
            errors.append(f"evidence missing: {e.get('path')}")
            continue
        actual = sha256_file(path)
        if actual != e.get("sha256"):
            errors.append(f"evidence hash mismatch: {e.get('path')}")
    return errors


def spec_gate_errors(root: Path, rec: dict) -> list[str]:
    """Re-check the spec gate against the live spec file.

    The recorded ``spec_sha256`` is compared with the file on disk every time
    the gate is consulted, so editing a spec after ``task-new`` invalidates a
    previously recorded ``spec_gate: PASS``.  A task card without ``spec_path``
    is no longer exempt: without an unchanged spec file the gate cannot pass.
    """
    errors: list[str] = []
    spec_path = rec.get("spec_path")
    if not spec_path:
        errors.append("task card has no spec_path (legacy task card); spec gate cannot pass")
        return errors
    full = root / spec_path
    if not full.exists():
        errors.append(f"spec file missing: {spec_path}")
        return errors
    recorded = rec.get("spec_sha256")
    actual = sha256_file(full)
    if recorded != actual:
        errors.append(
            "spec file changed since task-new "
            f"(spec_sha256 mismatch: recorded {recorded}, current {actual}); "
            "spec_gate is invalid, rebuild the task card"
        )
        return errors
    if rec.get("spec_gate") != "PASS":
        errors.append("spec gate not passed; run check --phase spec first")
    return errors


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def git_ok(repo: Path, *args: str) -> str:
    cp = git(repo, *args)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


# State directories towerctl itself writes during post-merge.  The tower root
# can live inside the verified repository (the kit repo is often the parent of
# ``tower-dsh``), so these artefacts must not count as implementation dirt.
TOOL_OWNED_STATE_DIRS = ("supervision/reviews", "supervision/outbox")


def repo_relative(repo: Path, path: Path) -> str | None:
    """Return ``path`` relative to ``repo`` (posix form), or None if outside."""
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def tool_owned_paths(root: Path, repo: Path) -> list[str]:
    """Repo-relative prefixes of the state directories towerctl owns."""
    owned: list[str] = []
    for name in TOOL_OWNED_STATE_DIRS:
        rel_path = repo_relative(repo, root / name)
        if rel_path:
            owned.append(rel_path)
    return owned


def status_path(line: str) -> str:
    """Extract the path from one ``git status --porcelain`` line."""
    path = line[3:] if len(line) > 3 else ""
    if " -> " in path:  # rename / copy entries use ``old -> new``
        path = path.split(" -> ", 1)[1]
    return path.strip().strip('"')


def working_tree_state(root: Path, repo: Path) -> tuple[list[str], list[str]]:
    """Return ``(dirty, tool_owned)`` porcelain entries for ``repo``.

    ``dirty`` holds everything a caller would normally see; ``tool_owned``
    holds the entries under :data:`TOOL_OWNED_STATE_DIRS` that post-merge
    itself produced (reviews, correction notes).
    """
    cp = git(repo, "status", "--porcelain")
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip() or "git status failed"
        return [detail], []
    owned = tool_owned_paths(root, repo)
    dirty: list[str] = []
    ignored: list[str] = []
    for line in cp.stdout.splitlines():
        if not line.strip():
            continue
        path = status_path(line)
        if any(path == prefix or path.startswith(prefix + "/") for prefix in owned):
            ignored.append(path)
        else:
            dirty.append(line)
    return dirty, ignored


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


def envelope_checks(root: Path, env: dict) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    repo = root / env.get("repository", "pilot/repo")
    add("repository exists", repo.exists(), str(repo))
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
    try:
        rec = load_record(root, env.get("task", ""))
        add("task accepted/closed", rec.get("status") in ("accepted", "closed"),
            str(rec.get("status")))
        review = rec.get("review") or {}
        add("review PASS", review.get("verdict") == "PASS", str(review.get("verdict")))
        add("reviewer != executor", review.get("reviewer") != rec.get("executor"),
            f"{review.get('reviewer')} vs {rec.get('executor')}")
        ev_errors = check_evidence(root, rec)
        add("evidence hashes valid", not ev_errors, "; ".join(ev_errors) or "ok")
    except SystemExit:
        add("task record", False, "task record missing")
    return checks


def cmd_init(root: Path, args) -> None:
    for d in ["shared", "primary", "primary/registries", "primary/handoffs",
              "supervision", "tasks", "ledger", "receipts", "handoffs",
              "tools", "tools/templates", "pilot/repo", "pilot/worktrees"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    state_path = root / "primary" / "CURRENT_STATE.json"
    if not state_path.exists():
        jdump(state_path, {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "phase": "G0",
            "objective": "用 tower-dsh 的内部任务跑通控制塔首版闭环",
            "owner": {
                "name": "mac",
                "gates": {"merge": "owner", "external_call": "owner",
                          "deploy_prod": "owner", "l0_main": "owner"},
            },
            "primary": {"id": f"ctl-{uuid.uuid4()}", "session": "phase1-pilot"},
            "next_action": "创建 PILOT-001 任务卡",
            "blockers": [],
            "updated_at": now(),
            "revision": 1,
        })
    board_path = root / "primary" / "TASK_BOARD.json"
    if not board_path.exists():
        jdump(board_path, {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                           "tasks": [], "updated_at": now()})
    ledger = root / "ledger" / "primary.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if not ledger.exists():
        ledger.touch()
    append_ledger(root, "INIT", "primary", {"root": str(root)})
    emit({"ok": True, "root": str(root), "state": str(state_path),
          "board": str(board_path), "ledger": str(ledger)})


def cmd_wiring(root: Path, args) -> None:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    tower = root / "TOWER.md"
    add("TOWER.md", tower.exists(), rel(root, tower))
    own_agents = root / "AGENTS.md"
    own_text = own_agents.read_text(encoding="utf-8") if own_agents.exists() else ""
    add("tower/AGENTS.md -> TOWER.md", "TOWER.md" in own_text, rel(root, own_agents))
    parent_agents = root.parent / "AGENTS.md"
    parent_text = parent_agents.read_text(encoding="utf-8") if parent_agents.exists() else ""
    add("workspace/AGENTS.md -> tower-dsh/TOWER.md",
        "tower-dsh/TOWER.md" in parent_text, str(parent_agents))
    start = root / "START-HERE.md"
    start_text = start.read_text(encoding="utf-8") if start.exists() else ""
    add("START-HERE.md -> CURRENT_STATE", "CURRENT_STATE" in start_text, rel(root, start))
    profile = root / "shared" / "PROJECT_PROFILE.json"
    if profile.exists():
        try:
            data = jload(profile)
            root_ok = Path(data.get("workspace_root", "")).exists()
            add("PROJECT_PROFILE.workspace_root exists", root_ok,
                data.get("workspace_root", ""))
        except Exception as exc:
            add("PROJECT_PROFILE parse", False, str(exc))
    else:
        add("PROJECT_PROFILE exists", False, rel(root, profile))
    for name in ["primary/CURRENT_STATE.json", "primary/TASK_BOARD.json"]:
        p = root / name
        try:
            jload(p)
            add(f"{name} parse", True, rel(root, p))
        except Exception as exc:
            add(f"{name} parse", False, str(exc))
    failed = [c for c in checks if not c["ok"]]
    if failed:
        emit({"ok": False, "status": "ORPHANED", "checks": checks}, 2)
    emit({"ok": True, "status": "WIRED", "checks": checks})


def cmd_startup(root: Path, args) -> None:
    required = [
        "TOWER.md", "AGENTS.md", "START-HERE.md",
        "shared/PROJECT_PROFILE.json", "shared/AUTHORITY_MODEL.json",
        "primary/CURRENT_STATE.json", "primary/TASK_BOARD.json",
        "ledger/primary.jsonl",
    ]
    errors = [f"missing: {p}" for p in required if not (root / p).exists()]
    if errors:
        fail(errors)
    state = jload(root / "primary" / "CURRENT_STATE.json")
    if state.get("role") != "primary":
        errors.append("current state role is not primary")
    if not (state.get("primary") or {}).get("id"):
        errors.append("primary.id missing")
    if not (state.get("owner") or {}).get("name"):
        errors.append("owner.name missing")
    if errors:
        fail(errors)
    board = load_board(root)
    emit({"ok": True, "tower_id": state.get("tower_id"), "role": state.get("role"),
          "phase": state.get("phase"), "primary": state.get("primary"),
          "tasks": len(board.get("tasks", [])), "next_action": state.get("next_action")})


SPEC_SCHEMA = "tower/spec@1"


def validate_spec(spec: dict) -> list[str]:
    """Content checks for a task spec, beyond field presence.

    Returns a list of human-readable errors; empty means the spec is sound.
    """
    errors = []
    if spec.get("schema") != SPEC_SCHEMA:
        errors.append(f"spec.schema must be {SPEC_SCHEMA}")
    acceptance = spec.get("acceptance") or []
    if not all(isinstance(x, str) and x.strip() for x in acceptance):
        errors.append("spec.acceptance items must be non-empty strings")
    forbidden = " ".join(str(x).lower() for x in (spec.get("forbidden") or []))
    if "merge" not in forbidden:
        errors.append("spec.forbidden must include 'merge'")
    if "production" not in forbidden:
        errors.append("spec.forbidden must include 'production access'")
    allowed = spec.get("allowed_paths") or []
    if not all(isinstance(x, str) and x.strip() for x in allowed):
        errors.append("spec.allowed_paths items must be non-empty strings")
    return errors


def cmd_task_new(root: Path, args) -> None:
    spec_path = resolve_input(root, args.spec)
    if not spec_path.exists():
        fail([f"spec not found: {spec_path}"])
    spec = jload(spec_path)
    tid = str(spec.get("id", ""))
    errors = []
    if not TASK_ID_RE.match(tid):
        errors.append(f"invalid task id: {tid}")
    for field in ["title", "authority", "scope", "allowed_paths", "forbidden", "acceptance"]:
        if not spec.get(field):
            errors.append(f"spec.{field} required")
    if not errors:
        errors += validate_spec(spec)
    worktree = spec.get("worktree")
    if not worktree:
        errors.append("spec.worktree required")
    elif not (root / worktree).exists():
        errors.append(f"worktree missing: {worktree}")
    if errors:
        fail(errors)
    tdir = task_dir(root, tid)
    if tdir.exists():
        fail([f"task already exists: {tid}"])
    (tdir / "evidence").mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "tower/task@1", "id": tid, "title": spec["title"],
        "status": "ready", "authority": spec["authority"],
        "scope": spec["scope"], "allowed_paths": spec["allowed_paths"],
        "forbidden": spec["forbidden"], "acceptance": spec["acceptance"],
        "depends_on": spec.get("depends_on", []), "worktree": worktree,
        "spec_path": rel(root, spec_path), "spec_sha256": sha256_file(spec_path),
        "spec_gate": None,
        "executor": None, "dispatch": None, "evidence": [], "review": None,
        "decision": None, "closeout": None,
        "created_at": now(), "updated_at": now(),
        "next": "spec 审批：owner 或独立 reviewer 运行 spec-approve，然后 check --phase spec",
    }
    jdump(tdir / "record.json", record)
    lines = [f"# {tid} — {record['title']}", "", f"- Status: `ready`",
             f"- Authority: `{record['authority']}`", f"- Worktree: `{worktree}`", "",
             "## Scope", ""]
    lines += [f"- {x}" for x in record["scope"]]
    lines += ["", "## Allowed paths", ""]
    lines += [f"- `{x}`" for x in record["allowed_paths"]]
    lines += ["", "## Forbidden", ""]
    lines += [f"- {x}" for x in record["forbidden"]]
    lines += ["", "## Acceptance", ""]
    lines += [f"- {x}" for x in record["acceptance"]]
    (tdir / "TASK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_board(root, record)
    append_ledger(root, "TASK_NEW", "primary", {"task": tid, "title": record["title"]})
    emit({"ok": True, "task": tid, "record": rel(root, tdir / "record.json"),
          "task_md": rel(root, tdir / "TASK.md")})


def ledger_has_event(root: Path, event_type: str, task: str) -> bool:
    ledger = root / "ledger" / "primary.jsonl"
    if not ledger.exists():
        return False
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == event_type and (ev.get("payload") or {}).get("task") == task:
            return True
    return False


def cmd_spec_approve(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if not rec.get("spec_path"):
        fail([f"task {args.task} has no spec_path (legacy task card)"])
    if args.by == rec.get("executor"):
        fail(["spec approver must not be the executor"])
    append_ledger(root, "SPEC_APPROVED", args.by,
                  {"task": args.task, "by": args.by, "note": args.note or ""})
    emit({"ok": True, "task": args.task, "approved_by": args.by,
          "next": f"python tools/towerctl.py check --task {args.task} --phase spec"})


def cmd_check(root: Path, args) -> None:
    rec = load_record(root, args.task)
    phase = args.phase
    errors = []
    if phase == "spec":
        spec_path = rec.get("spec_path")
        if not spec_path:
            errors.append(
                "task card has no spec_path; legacy task cards are no longer exempt "
                "from the spec gate, rebuild the card from a spec"
            )
        else:
            full = root / spec_path
            if not full.exists():
                errors.append(f"spec file missing: {spec_path}")
            else:
                if sha256_file(full) != rec.get("spec_sha256"):
                    errors.append("spec file changed since task-new; rebuild the task card instead of editing in place")
                else:
                    errors += validate_spec(jload(full))
        if not ledger_has_event(root, "SPEC_APPROVED", args.task):
            errors.append("SPEC_APPROVED ledger event missing; run spec-approve first")
        if not errors and rec.get("spec_gate") != "PASS":
            rec["spec_gate"] = "PASS"
            save_record(root, rec)
            append_ledger(root, "CHECK", "primary", {"task": args.task, "phase": "spec", "ok": True})
    elif phase == "ready":
        if rec.get("status") != "ready":
            errors.append(f"status is {rec.get('status')}, expected ready")
        if not (task_dir(root, args.task) / "TASK.md").exists():
            errors.append("TASK.md missing")
        if not (root / rec.get("worktree", "")).exists():
            errors.append("worktree missing")
        errors += spec_gate_errors(root, rec)
    elif phase == "dispatch":
        if rec.get("status") != "dispatched":
            errors.append(f"status is {rec.get('status')}, expected dispatched")
        if not rec.get("executor"):
            errors.append("executor missing")
        if not (rec.get("dispatch") or {}).get("at"):
            errors.append("dispatch record missing")
    elif phase == "deliver":
        if rec.get("status") not in ("delivered", "reviewed", "accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected delivered")
        errors += check_evidence(root, rec)
    elif phase == "review":
        if rec.get("status") not in ("reviewed", "accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected reviewed")
        review = rec.get("review") or {}
        if review.get("verdict") != "PASS":
            errors.append("review verdict is not PASS")
        reviewer = (review.get("reviewer") or "").strip()
        if not reviewer:
            errors.append("reviewer missing or empty in review record")
        elif reviewer == (rec.get("executor") or "").strip():
            errors.append("reviewer equals executor")
        errors += check_evidence(root, rec)
    elif phase == "accept":
        if rec.get("status") not in ("accepted", "closed"):
            errors.append(f"status is {rec.get('status')}, expected accepted")
        if not rec.get("decision"):
            errors.append("decision missing")
        errors += check_evidence(root, rec)
    elif phase == "close":
        if rec.get("status") != "closed":
            errors.append(f"status is {rec.get('status')}, expected closed")
        if not (rec.get("closeout") or {}).get("path"):
            errors.append("closeout missing")
        errors += check_evidence(root, rec)
    if errors:
        emit({"ok": False, "task": args.task, "phase": phase, "errors": errors}, 2)
    emit({"ok": True, "task": args.task, "phase": phase,
          "status": rec.get("status"), "evidence": len(rec.get("evidence") or [])})


def cmd_hash(root: Path, args) -> None:
    path = resolve_input(root, args.path)
    if not path.exists():
        fail([f"path not found: {path}"])
    emit({"ok": True, "path": str(path), "sha256": sha256_file(path),
          "bytes": path.stat().st_size})


def cmd_dispatch(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in ("ready", "rework"):
        fail([f"task status {rec.get('status')} cannot dispatch"])
    worktree = args.worktree or rec.get("worktree")
    if not worktree or not (root / worktree).exists():
        fail([f"worktree missing: {worktree}"])
    task_md = task_dir(root, args.task) / "TASK.md"
    if not task_md.exists():
        fail([f"TASK.md missing: {rel(root, task_md)}; cannot dispatch without a task card"])
    gate_errors = spec_gate_errors(root, rec)
    if gate_errors:
        fail(gate_errors)
    rec["executor"] = args.executor
    rec["dispatch"] = {"executor": args.executor, "worktree": worktree, "at": now()}
    rec["status"] = "dispatched"
    rec["next"] = "等待 executor 交付"
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "DISPATCH", "primary",
                  {"task": args.task, "executor": args.executor, "worktree": worktree})
    emit({"ok": True, "task": args.task, "status": rec["status"], "executor": args.executor,
          "worktree": worktree})


def cmd_deliver(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in ("dispatched", "delivered", "rework"):
        fail([f"task status {rec.get('status')} cannot deliver"])
    tdir = task_dir(root, args.task)
    evdir = tdir / "evidence"
    evdir.mkdir(parents=True, exist_ok=True)
    existing = {e.get("path") for e in rec.get("evidence", [])}
    for value in args.evidence:
        src = resolve_input(root, value)
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
            "id": f"E-{len(rec.get('evidence', [])) + 1:03d}",
            "path": relpath, "sha256": digest, "bytes": dest.stat().st_size, "at": now(),
        })
        existing.add(relpath)
    rec["status"] = "delivered"
    rec["delivered_at"] = now()
    rec["next"] = "等待独立 reviewer"
    save_record(root, rec)
    update_board(root, rec)
    lines = [f"# {rec['id']} — Delivery", "", f"- Status: `delivered`",
             f"- Executor: `{rec.get('executor')}`", f"- Worktree: `{rec.get('worktree')}`", "",
             "## Evidence", "", "| ID | Path | SHA-256 | Bytes |", "|---|---|---|---|"]
    for e in rec["evidence"]:
        lines.append(f"| {e['id']} | `{e['path']}` | `{e['sha256']}` | {e['bytes']} |")
    (tdir / "DELIVERY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_ledger(root, "DELIVER", "executor" if rec.get("executor") else "primary",
                  {"task": args.task, "evidence": len(rec["evidence"])})
    emit({"ok": True, "task": args.task, "status": rec["status"],
          "evidence": len(rec["evidence"])})


def cmd_checkback(root: Path, args) -> None:
    rec = load_record(root, args.task)
    if rec.get("status") not in ("delivered", "reviewed", "rework"):
        fail([f"task status {rec.get('status')} cannot checkback"])
    reviewer = (args.reviewer or "").strip()
    if not reviewer:
        fail(["reviewer must be non-empty (whitespace-only is not a reviewer)"])
    if reviewer == (rec.get("executor") or "").strip():
        fail(["reviewer must differ from executor"])
    rec["review"] = {"reviewer": reviewer, "verdict": args.verdict,
                     "note": args.note or "", "at": now()}
    rec["status"] = "reviewed" if args.verdict == "PASS" else "rework"
    rec["next"] = "等待 accept" if args.verdict == "PASS" else "返工"
    save_record(root, rec)
    update_board(root, rec)
    tdir = task_dir(root, args.task)
    lines = [f"# {rec['id']} — Independent Checkback", "",
             f"- Reviewer: `{reviewer}`", f"- Verdict: **{args.verdict}**",
             f"- At: {rec['review']['at']}", "", "## Note", "", args.note or "(none)", "",
             "## Evidence checked", ""]
    lines += [f"- `{e['path']}` `{e['sha256']}`" for e in rec.get("evidence", [])]
    (tdir / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_ledger(root, "CHECKBACK", "reviewer",
                  {"task": args.task, "reviewer": reviewer, "verdict": args.verdict})
    emit({"ok": True, "task": args.task, "status": rec["status"], "verdict": args.verdict})


def cmd_accept(root: Path, args) -> None:
    rec = load_record(root, args.task)
    review = rec.get("review") or {}
    if review.get("verdict") != "PASS":
        fail(["cannot accept without PASS checkback"])
    if rec.get("status") not in ("reviewed", "accepted"):
        fail([f"task status {rec.get('status')} cannot accept"])
    evidence_errors = check_evidence(root, rec)
    if evidence_errors:
        fail(evidence_errors)
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
    emit({"ok": True, "task": args.task, "status": rec["status"], "decision": args.decision})


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
    next_text = "merge/handoff decision (owner gate) — not performed in Phase 1"
    lines = [f"# {rec['id']} — Closeout", "", f"- Status: `closed`",
             f"- Executor: `{rec.get('executor')}`",
             f"- Reviewer: `{(rec.get('review') or {}).get('reviewer')}`",
             f"- Decision: `{rec.get('decision', {}).get('id')}`",
             "- Merge: **not performed** (first version; merge is a separate owner gate)", "",
             "## Evidence", ""]
    lines += [f"- `{e['path']}` `{e['sha256']}`" for e in rec.get("evidence", [])]
    lines += ["", "## Next", "", next_text]
    closeout.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec["status"] = "closed"
    rec["closeout"] = {"path": rel(root, closeout), "at": now()}
    rec["next"] = next_text
    save_record(root, rec)
    update_board(root, rec)
    append_ledger(root, "CLOSEOUT", "primary",
                  {"task": args.task, "closeout": rel(root, closeout)})
    emit({"ok": True, "task": args.task, "status": rec["status"],
          "closeout": rel(root, closeout)})


def _latest_by(items: list[dict], field: str) -> dict:
    """Return the item whose ``field`` timestamp is newest (empty if none)."""
    if not items:
        return {}

    def sort_key(item: dict) -> float:
        raw = str(item.get(field) or "")
        try:
            return datetime.fromisoformat(raw).timestamp()
        except Exception:
            return float("-inf")

    return max(items, key=sort_key)


def select_task(board: dict, task_id: str | None = None) -> dict:
    """Pick the task a handoff is about.

    An explicit ``task_id`` wins.  Otherwise a single non-closed task is used;
    with several non-closed tasks the most recently updated one wins, and when
    every task is closed the most recently updated task overall is used.
    """
    tasks = [t for t in (board.get("tasks") or []) if isinstance(t, dict)]
    if task_id:
        return next((t for t in tasks if t.get("id") == task_id), {})
    open_tasks = [t for t in tasks if t.get("status") != "closed"]
    if len(open_tasks) == 1:
        return open_tasks[0]
    if open_tasks:
        return _latest_by(open_tasks, "updated_at")
    return _latest_by(tasks, "updated_at")


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


def load_profile(root: Path) -> dict:
    path = root / "shared" / "PROJECT_PROFILE.json"
    if not path.exists():
        return {}
    try:
        return jload(path)
    except Exception:
        return {}


def _profile_base(root: Path, profile: dict) -> Path:
    """Base for ``pilot.repo`` / ``pilot.worktree`` declared in the profile.

    The profile records the tower root it belongs to; a worktree copy of the
    tower keeps that absolute value, so resolving the declared pilot paths
    against it points at the real pilot instead of the copy.
    """
    declared = profile.get("tower_root")
    if declared:
        try:
            candidate = Path(str(declared))
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
    return root


def _profile_worktree_matches_task(pilot: dict, worktree: str, task_id: str) -> bool:
    """Only use the profile worktree when it belongs to the selected task."""
    if not worktree:
        return False
    if not task_id:
        return True
    declared_task = str(pilot.get("task") or "").strip()
    if declared_task:
        return declared_task == task_id
    return Path(worktree).name == task_id


def resolve_pilot_paths(root: Path, record: dict, profile: dict,
                        task_id: str) -> tuple[Path | None, Path | None]:
    """Resolve the pilot repo and worktree for the selected task.

    ``PROJECT_PROFILE.pilot.repo`` / ``pilot.worktree`` win when present.  The
    profile worktree is only used when it belongs to the selected task;
    otherwise the task's own ``record.worktree`` wins, so a handoff never
    points at another task's worktree.  Missing values fall back to the record
    and finally to the conventional ``pilot/worktrees/<task>`` path.
    """
    pilot = profile.get("pilot") or {}
    profile_base = _profile_base(root, profile)

    repo_value = str(pilot.get("repo") or "").strip()
    repo_base = profile_base
    if not repo_value:
        repo_value = str(record.get("repo") or "").strip()
        repo_base = root
    if not repo_value:
        repo_value = "pilot/repo"
        repo_base = root

    worktree_value = ""
    worktree_base = root
    profile_worktree = str(pilot.get("worktree") or "").strip()
    if _profile_worktree_matches_task(pilot, profile_worktree, task_id):
        worktree_value = profile_worktree
        worktree_base = profile_base
    if not worktree_value:
        worktree_value = str(record.get("worktree") or "").strip()
        worktree_base = root
    if not worktree_value and task_id:
        worktree_value = f"pilot/worktrees/{task_id}"
        worktree_base = root

    def join(base: Path, value: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else base / path

    return join(repo_base, repo_value), join(worktree_base, worktree_value)


def _optional_git(repo: Path | None, *args: str) -> str:
    """Run git best-effort: a missing path or git failure yields ``""``."""
    if repo is None:
        return ""
    try:
        if not repo.exists():
            return ""
        return git_ok(repo, *args)
    except Exception:
        return ""


def _optional_git_status(repo: Path | None) -> str:
    """``clean`` / porcelain text, or ``""`` when git/path is unavailable."""
    if repo is None or not repo.exists():
        return ""
    try:
        cp = git(repo, "status", "--porcelain")
    except Exception:
        return ""
    if cp.returncode != 0:
        return ""
    return cp.stdout.strip() or "clean"


def _load_optional_record(root: Path, task_id: str) -> dict:
    if not task_id:
        return {}
    path = task_record_path(root, task_id)
    if not path.exists():
        return {}
    try:
        return jload(path)
    except Exception:
        return {}


def match_task_by_evidence(root: Path, state: dict) -> str | None:
    """Match a legacy package (no ``task`` field) to a task by evidence hashes.

    Returns the task id whose record contains every ``(path, sha256)`` pair
    recorded in the package's ``state.evidence``; when no record matches
    completely, the task with the largest overlap wins; no overlap returns
    ``None`` so the caller can fall back to the default selection.
    """
    wanted = {(e.get("path"), e.get("sha256"))
              for e in (state.get("evidence") or []) if e.get("path")}
    if not wanted:
        return None
    best_id: str | None = None
    best_score = 0
    for task in load_board(root).get("tasks", []):
        tid = task.get("id") or ""
        if not tid:
            continue
        record = _load_optional_record(root, tid)
        have = {(e.get("path"), e.get("sha256"))
                for e in (record.get("evidence") or [])}
        score = len(wanted & have)
        if score > best_score:
            best_score, best_id = score, tid
        if wanted <= have:
            return tid
    return best_id if best_score else None


def envelope_for_task(root: Path, task_id: str) -> str:
    """Best-effort envelope id for a task (legacy packages carry no envelope)."""
    if not task_id:
        return ""
    entries = [e for e in load_queue(root).get("entries", [])
               if isinstance(e, dict) and e.get("task") == task_id]
    if not entries:
        return ""
    entry = _latest_by(entries, "added_at") if len(entries) > 1 else entries[0]
    return str(entry.get("envelope_id") or "")


def current_snapshot(root: Path, task_id: str | None = None,
                     envelope_id: str | None = None) -> dict:
    """Capture live tower state for the selected task / envelope.

    Task and envelope selection is explicit-id first, then single-candidate,
    then most-recently-updated.  Repo/worktree come from the project profile
    (falling back to the task record), and git is best-effort: an unavailable
    repository or worktree yields ``""`` instead of raising.
    """
    state = jload(root / "primary" / "CURRENT_STATE.json")
    supervision = load_supervision(root)
    board = load_board(root)
    queue = load_queue(root)
    task = select_task(board, task_id)
    selected_task = str(task.get("id") or "")
    record = _load_optional_record(root, selected_task)
    entry = select_envelope(queue, envelope_id)
    selected_envelope = str(entry.get("envelope_id") or "")
    profile = load_profile(root)
    repo, worktree = resolve_pilot_paths(root, record, profile, selected_task)
    evidence = [{"path": e.get("path"), "sha256": e.get("sha256")}
                for e in (record.get("evidence") or [])]
    open_tasks = [{"id": t.get("id"), "status": t.get("status"),
                   "next": t.get("next") or ""}
                  for t in (board.get("tasks") or [])
                  if isinstance(t, dict) and t.get("status") != "closed"]
    ledger = root / "ledger" / "primary.jsonl"
    ledger_seq = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    ledger_seq = max(ledger_seq, int(json.loads(line).get("seq", 0)))
                except Exception:
                    pass
    return {
        "tower_id": state.get("tower_id"),
        "phase": state.get("phase"),
        "primary_id": (state.get("primary") or {}).get("id"),
        "supervisor_id": (supervision.get("supervisor") or {}).get("id"),
        "supervision_phase": supervision.get("phase"),
        "owner": (state.get("owner") or {}).get("name") or "",
        "next_action": state.get("next_action") or "",
        "task_id": selected_task,
        "task_status": record.get("status") or task.get("status") or "",
        "task_next": record.get("next") or task.get("next") or "",
        "task_evidence_count": len(record.get("evidence") or []),
        "envelope_id": selected_envelope,
        "queue_status": entry.get("status") or "",
        "merge_commit": entry.get("merge_commit") or "",
        "main_sha": _optional_git(repo, "rev-parse", "main"),
        "worktree_head": _optional_git(worktree, "rev-parse", "HEAD"),
        "repo_status": _optional_git_status(repo),
        "worktree_status": _optional_git_status(worktree),
        "tower_root": str(root.resolve()),
        "repo": str(repo) if repo is not None else "",
        "worktree": str(worktree) if worktree is not None else "",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "open_tasks": open_tasks,
        "evidence": evidence,
        "ledger_seq": ledger_seq,
        "captured_at": now(),
    }


def handoff_checks(root: Path, package_id: str, pkg: dict) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    pkgdir = root / "handoffs" / package_id
    handoff = pkgdir / "HANDOFF.md"
    selfcheck = pkgdir / "SELF-CHECK.md"
    add("HANDOFF.md exists", handoff.exists(), str(handoff))
    add("SELF-CHECK.md exists", selfcheck.exists(), str(selfcheck))
    if handoff.exists():
        text = handoff.read_text(encoding="utf-8")
        for marker in ["## §0", "## §0a", "## §1", "## §2", "## §3",
                       "## §4", "## §4a", "## §5", "## §6", "## §7"]:
            add(f"section {marker}", marker in text, marker)
    if selfcheck.exists():
        text = selfcheck.read_text(encoding="utf-8")
        add("self-check no unchecked items", "- [ ]" not in text, "all checked")
    files = pkg.get("files") or {}
    for name in ["HANDOFF.md", "SELF-CHECK.md"]:
        path = pkgdir / name
        if path.exists():
            add(f"{name} hash", sha256_file(path) == files.get(name), files.get(name, ""))
    # New packages carry the task/envelope they were generated for.  Legacy
    # packages (e.g. HANDOFF-PILOT-001) predate those fields: match them back
    # to a task by evidence hashes, then fall back to the default selection.
    pkg_task = str(pkg.get("task") or "").strip()
    if not pkg_task:
        pkg_task = match_task_by_evidence(root, pkg.get("state") or {}) or ""
    pkg_envelope = str(pkg.get("envelope") or "").strip()
    if not pkg_envelope and pkg_task:
        pkg_envelope = envelope_for_task(root, pkg_task)
    snap = current_snapshot(root, task_id=pkg_task or None,
                            envelope_id=pkg_envelope or None)
    expected = pkg.get("state") or {}
    add("main SHA unchanged", snap["main_sha"] == expected.get("main_sha"),
        f"{snap['main_sha']} vs {expected.get('main_sha')}")
    add("worktree head unchanged", snap["worktree_head"] == expected.get("worktree_head"),
        f"{snap['worktree_head']} vs {expected.get('worktree_head')}")
    add("queue still POST_MERGE_VERIFIED",
        snap["queue_status"] == "POST_MERGE_VERIFIED", str(snap["queue_status"]))
    add("task still closed", snap["task_status"] == "closed", str(snap["task_status"]))
    add("repo working tree clean", snap["repo_status"] == "clean", snap["repo_status"])
    add("worktree clean", snap["worktree_status"] == "clean", snap["worktree_status"])
    return checks


def cmd_handoff_new(root: Path, args) -> None:
    package_id = args.package
    pkgdir = root / "handoffs" / package_id
    if pkgdir.exists():
        fail([f"handoff package already exists: {package_id}"])
    snap = current_snapshot(root, task_id=args.task, envelope_id=args.envelope)
    if args.task and not snap["task_id"]:
        fail([f"task not found for --task {args.task}"])
    if args.envelope and not snap["envelope_id"]:
        fail([f"envelope not found for --envelope {args.envelope}"])
    pkgdir.mkdir(parents=True)

    task_id = snap["task_id"]
    envelope_id = snap["envelope_id"]
    evidence_rows = "\n".join(
        f"| `{e['path']}` | `{e['sha256']}` |" for e in snap["evidence"]
    ) or "| （无） | （无） |"
    if task_id:
        task_line = (f"任务 `{task_id}` 状态 `{snap['task_status'] or 'unknown'}`"
                     f"（next：{snap['task_next'] or '—'}）")
    else:
        task_line = "任务：未选择（TASK_BOARD 为空或显式查询未命中）"
    if envelope_id:
        queue_line = (f"合并队列 `{envelope_id}` 状态 "
                      f"`{snap['queue_status'] or 'unknown'}`（merge commit："
                      f"`{snap['merge_commit'] or '—'}`）")
    else:
        queue_line = "合并队列：空"
    section1 = f"主塔 phase `{snap['phase'] or 'unknown'}`；{task_line}；{queue_line}。"
    open_lines = "\n".join(
        f"- `{t['id']}` — `{t['status']}` — {t.get('next') or '—'}"
        for t in snap["open_tasks"]
    ) or "- 无在途任务。"
    task_card = f"tasks/{task_id}/TASK.md" if task_id else "—"
    closeout = f"tasks/{task_id}/CLOSEOUT.md" if task_id else "—"
    in_flight = (f"当前 {len(snap['open_tasks'])} 项在途" if snap["open_tasks"]
                 else "当前无在途")
    handoff_md = f"""# tower-dsh 交接上下文包 — {package_id}

> 项目：Tower/DSH · 机制：project-handoff v2.1 · 装配路径：塔台直写
> 交接时刻：{snap['captured_at']} · 交出塔：{snap['primary_id']}

## §0 交接时刻实值

| 锚点 | 值 |
|---|---|
| tower_id | `{snap['tower_id']}` |
| primary phase | `{snap['phase']}` |
| primary id | `{snap['primary_id']}` |
| supervisor id | `{snap['supervisor_id']}` |
| supervision phase | `{snap['supervision_phase']}` |
| task id | `{task_id or '—'}` |
| envelope id | `{envelope_id or '—'}` |
| main SHA | `{snap['main_sha']}` |
| worktree head | `{snap['worktree_head']}` |
| repo status | `{snap['repo_status']}` |
| worktree status | `{snap['worktree_status']}` |
| task status | `{snap['task_status'] or '—'}` |
| task next | `{snap['task_next'] or '—'}` |
| merge queue | `{snap['queue_status'] or '—'}` |
| merge commit | `{snap['merge_commit'] or '—'}` |
| primary ledger seq | `{snap['ledger_seq']}` |

### 证据锚点

| 证据 | SHA-256 |
|---|---|
{evidence_rows}

## §0a 材料漂移警示

NONE（无阻断性漂移；证据锚点：package {len(snap['evidence'])} 项，所选 task record {snap['task_evidence_count']} 项）。

## §1 30 秒版现状

{section1}

## §2 接续读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`
4. `shared/AUTHORITY_MODEL.json`
5. `primary/CURRENT_STATE.json`
6. `supervision/CURRENT_STATE.json`
7. `primary/TASK_BOARD.json`
8. `supervision/MERGE_QUEUE.json`
9. `{closeout}`
10. `ledger/primary.jsonl` 与 `ledger/supervision.jsonl`

## §3 运行时操作手册

- Tower root：`{snap['tower_root']}`
- Pilot repo：`{snap['repo'] or '（未配置）'}`
- Pilot worktree：`{snap['worktree'] or '（未配置）'}`
- Python：{snap['python']}；测试：`python -B -m unittest discover -s tools/tests -v`
- CLI：`python tools/towerctl.py <command>`
- 不读凭据、不调用生产、不部署；所有状态经 `towerctl`。

## §4 在途任务队列

{open_lines}
- 下一动作：{snap['next_action'] or '—'}

## §4a 调研/方案/未实现需求资产登记

- `control-tower/DESIGN.md` — Tower/DSH v0.3 设计（双塔/文件化/接线门/handoff v2.1）。
- `tower-dsh/PHASE2-REPORT.md` — Phase 2 双塔 pilot 报告。
- `%APPDATA%\\kimi-desktop\\daimon-share\\daimon\\skills\\project-handoff\\SKILL.md` — v2.1 源机制（只读参考）。
- `D:\\SeeMake-K3\\_k3-ops\\templates\\项目交接机制-v2.1-通用模板.md` — v2.1 通用模板（只读参考）。
- `~/.agents/skills/control-tower/`、`~/.agents/skills/control-tower-supervisor/` — 本塔技能。

## §5 owner 偏好与裁决档案

- Owner：`{snap['owner'] or '—'}`。
- 四闸永远归 owner：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。
- Primary 不 merge；Supervision 独占合并队列。
- 生产轨 `no_access`；本 pilot 未碰生产。
- 偏好：证据优先、单一写者、先手动后自动化。

## §6 判例与环境陷阱

- 本地 git 合并，不是远端 PR；无服务端分支保护。
- `--role supervisor` 是程序性分离，不是密码学身份。
- 证据锚点以 package 与 task record 各自的列表为准，两侧条目数可能不同（如 `commit.txt` 可能只登记在 record 中）。
- Windows CRLF 警告属正常；控制台中文可能显示乱码，文件本身 UTF-8。
- 不要手改 `primary/`、`supervision/`、`ledger/`；用 `towerctl`。

## §7 红线四闸与文档地图

| 对象 | 路径 |
|---|---|
| 塔身份 | `TOWER.md` |
| 宪法 | `AGENTS.md` |
| 启动读序 | `START-HERE.md` |
| 主塔状态 | `primary/CURRENT_STATE.json` |
| 监督塔状态 | `supervision/CURRENT_STATE.json` |
| 合并队列 | `supervision/MERGE_QUEUE.json` |
| 合并账本 | `supervision/registries/merge-ledger.json` |
| 任务卡 | `{task_card}` |
| 收口 | `{closeout}` |
| Ledger | `ledger/primary.jsonl`、`ledger/supervision.jsonl` |

**四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。**
"""
    (pkgdir / "HANDOFF.md").write_text(handoff_md, encoding="utf-8")
    selfcheck_md = f"""# 交出前自查 — {package_id}

- [x] 无未释放的锁/残留工作树/残留进程端口
- [x] 唯一真相源已更新到最新，在途项都有“下一步”
- [x] 在途任务卡每张有明确状态（{in_flight}）
- [x] 高危操作处于完整闸点，无半截（本 pilot 无生产动作）
- [x] 待 owner 输入项已汇总进 §4
- [x] 本窗调研/方案/未实现需求已登记进 §4a
- [x] §0 实值逐项复核于交接时刻

复核时刻：{snap['captured_at']}
主塔：`{snap['primary_id']}`
"""
    (pkgdir / "SELF-CHECK.md").write_text(selfcheck_md, encoding="utf-8")
    pkg = {
        "schema": "tower/handoff-package@1",
        "package_id": package_id,
        "project": "tower-dsh",
        "mechanism": "project-handoff-v2.1",
        "assembly_path": "tower_direct",
        "created_at": now(),
        "source_controller": snap["primary_id"],
        "task": task_id,
        "envelope": envelope_id,
        "status": "PREPARED",
        "files": {
            "HANDOFF.md": sha256_file(pkgdir / "HANDOFF.md"),
            "SELF-CHECK.md": sha256_file(pkgdir / "SELF-CHECK.md"),
        },
        "state": snap,
        "claim": None,
        "acceptance": None,
    }
    jdump(pkgdir / "package.json", pkg)
    append_ledger(root, "HANDOFF_NEW", "primary",
                  {"package": package_id, "source": snap["primary_id"],
                   "task": task_id, "envelope": envelope_id})
    emit({"ok": True, "package": package_id, "dir": rel(root, pkgdir),
          "task": task_id, "envelope": envelope_id, "files": pkg["files"]})


def cmd_handoff_check(root: Path, args) -> None:
    pkgdir = root / "handoffs" / args.package
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    checks = handoff_checks(root, args.package, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    emit({"ok": True, "package": args.package, "checks": checks})


def cmd_handoff_claim(root: Path, args) -> None:
    pkgdir = root / "handoffs" / args.package
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    if args.controller == pkg.get("source_controller"):
        fail(["receiver must differ from source controller"])
    checks = handoff_checks(root, args.package, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    claim = {
        "schema": "tower/handoff-claim@1",
        "package_id": args.package,
        "controller": args.controller,
        "claimed_at": now(),
        "checks": checks,
        "status": "READY_FOR_RECEIVER",
    }
    jdump(pkgdir / "CLAIM.json", claim)
    pkg.update({"status": "READY_FOR_RECEIVER", "claim": claim})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_CLAIM", "receiver",
                  {"package": args.package, "controller": args.controller})
    emit({"ok": True, "package": args.package, "status": pkg["status"],
          "controller": args.controller})


def cmd_handoff_accept(root: Path, args) -> None:
    pkgdir = root / "handoffs" / args.package
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    claim = pkg.get("claim") or {}
    if pkg.get("status") not in ("READY_FOR_RECEIVER", "RECEIVED"):
        fail([f"package status {pkg.get('status')} is not READY_FOR_RECEIVER/RECEIVED"])
    if claim.get("controller") != args.controller:
        fail(["claim controller does not match --controller"])
    acceptance = {
        "schema": "tower/handoff-acceptance@1",
        "package_id": args.package,
        "source_controller": pkg.get("source_controller"),
        "receiver": args.controller,
        "accepted_at": now(),
        "status": "ACCEPTED",
    }
    jdump(pkgdir / "ACCEPTANCE.json", acceptance)
    pkg.update({"status": "ACCEPTED", "acceptance": acceptance})
    jdump(pkg_path, pkg)
    state_path = root / "primary" / "CURRENT_STATE.json"
    state = jload(state_path)
    state["handoff"] = {"status": "ACCEPTED", "package": args.package,
                        "receiver": args.controller, "accepted_at": now()}
    state["phase"] = "HANDOFF_ACCEPTED"
    state["next_action"] = f"new controller {args.controller} must run startup from handoffs/{args.package}/HANDOFF.md"
    state["updated_at"] = now()
    jdump(state_path, state)
    append_ledger(root, "HANDOFF_ACCEPT", "primary",
                  {"package": args.package, "receiver": args.controller})
    emit({"ok": True, "package": args.package, "status": "ACCEPTED",
          "receiver": args.controller})


def cmd_handoff_receipt(root: Path, args) -> None:
    pkgdir = root / "handoffs" / args.package
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    claim = pkg.get("claim") or {}
    if pkg.get("status") != "READY_FOR_RECEIVER":
        fail([f"package status {pkg.get('status')} is not READY_FOR_RECEIVER"])
    if claim.get("controller") != args.controller:
        fail(["claim controller does not match --controller"])
    checks = handoff_checks(root, args.package, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    receipt_md = f"""# 接收回执 — {args.package}

- Receiver: `{args.controller}`
- Received at: {now()}
- Source: `{pkg.get('source_controller')}`
- Mechanism: `{pkg.get('mechanism')}`

## 首验

- [x] 读 HANDOFF.md（§0/§0a/§1–§7）
- [x] 读 CURRENT_STATE / TASK_BOARD / MERGE_QUEUE
- [x] 全项实值比对通过
- [x] 在途任务复述：无
- [x] 等待 owner 口令后开工

## Note

{args.note or '(none)'}
"""
    (pkgdir / "RECEIPT.md").write_text(receipt_md, encoding="utf-8")
    receipt = {"controller": args.controller, "received_at": now(),
               "checks": checks, "note": args.note or "",
               "path": rel(root, pkgdir / "RECEIPT.md")}
    pkg.update({"status": "RECEIVED", "receipt": receipt})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_RECEIPT", "receiver",
                  {"package": args.package, "controller": args.controller})
    emit({"ok": True, "package": args.package, "status": "RECEIVED",
          "receipt": receipt["path"]})


def cmd_handoff_activate(root: Path, args) -> None:
    pkgdir = root / "handoffs" / args.package
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    acceptance = pkg.get("acceptance") or {}
    if pkg.get("status") != "ACCEPTED":
        fail([f"package status {pkg.get('status')} is not ACCEPTED"])
    if acceptance.get("receiver") != args.controller:
        fail(["acceptance receiver does not match --controller"])
    state_path = root / "primary" / "CURRENT_STATE.json"
    state = jload(state_path)
    state["primary"] = {"id": args.controller, "session": "handoff-receiver"}
    state["handoff"] = {"status": "ACTIVE", "package": args.package,
                        "receiver": args.controller, "activated_at": now()}
    state["phase"] = "HANDOFF_ACTIVE"
    state["next_action"] = f"resume from handoffs/{args.package}/HANDOFF.md"
    state["updated_at"] = now()
    jdump(state_path, state)
    activation = {"schema": "tower/handoff-activation@1",
                  "package_id": args.package, "controller": args.controller,
                  "activated_at": now(), "status": "ACTIVE"}
    jdump(pkgdir / "ACTIVATION.json", activation)
    pkg.update({"status": "ACTIVE", "activation": activation})
    jdump(pkg_path, pkg)
    append_ledger(root, "HANDOFF_ACTIVATE", "receiver",
                  {"package": args.package, "controller": args.controller})
    emit({"ok": True, "package": args.package, "status": "ACTIVE",
          "controller": args.controller})


def cmd_handoff_status(root: Path, args) -> None:
    packages = []
    pkg_root = root / "handoffs"
    if pkg_root.exists():
        for p in sorted(pkg_root.glob("*/package.json")):
            data = jload(p)
            packages.append({"package_id": data.get("package_id"),
                             "status": data.get("status"),
                             "source": data.get("source_controller"),
                             "receiver": (data.get("claim") or {}).get("controller"),
                             "created_at": data.get("created_at")})
    emit({"ok": True, "packages": packages})


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


def cmd_envelope_new(root: Path, args) -> None:
    file = resolve_input(root, args.file)
    if not file.exists():
        fail([f"envelope file not found: {file}"])
    env = jload(file)
    env_id = env.get("envelope_id")
    task = env.get("task")
    if not env_id or not task:
        fail(["envelope_id and task are required"])
    if env.get("task") != args.task:
        fail([f"envelope task {env.get('task')} != --task {args.task}"])
    rec = load_record(root, args.task)
    if rec.get("status") not in ("accepted", "closed"):
        fail([f"task status {rec.get('status')} cannot submit envelope"])
    if not (rec.get("review") or {}).get("verdict") == "PASS":
        fail(["task has no PASS review"])
    repo = root / env.get("repository", "pilot/repo")
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
    record.update({"envelope_head_sha": b, "status": "DRAFT", "created_at": now()})
    jdump(root / "supervision" / "envelopes" / f"{env_id}.json", record)
    append_supervision_ledger(root, "ENVELOPE_NEW", "primary",
                              {"envelope": env_id, "task": task, "head": b})
    emit({"ok": True, "envelope": env_id, "head": b, "checks": checks})


def cmd_queue_add(root: Path, args) -> None:
    env_path = root / "supervision" / "envelopes" / f"{args.envelope}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    queue = load_queue(root)
    if any(e.get("envelope_id") == args.envelope for e in queue.get("entries", [])):
        fail([f"envelope already queued: {args.envelope}"])
    queue.setdefault("entries", []).append({
        "envelope_id": args.envelope,
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


def cmd_merge_check(root: Path, args) -> None:
    env_path = root / "supervision" / "envelopes" / f"{args.envelope}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    checks = envelope_checks(root, env)
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == args.envelope), None)
    checks.append({"name": "queued", "ok": entry is not None,
                   "detail": entry.get("status") if entry else "missing"})
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "envelope": args.envelope,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    emit({"ok": True, "envelope": args.envelope, "checks": checks})


def cmd_merge(root: Path, args) -> None:
    if args.role != "supervisor":
        fail(["merge requires --role supervisor"])
    supervision = load_supervision(root)
    primary = jload(root / "primary" / "CURRENT_STATE.json").get("primary", {})
    if args.supervisor == primary.get("id"):
        fail(["primary cannot merge; supervisor must differ"])
    env_path = root / "supervision" / "envelopes" / f"{args.envelope}.json"
    if not env_path.exists():
        fail([f"envelope not found: {args.envelope}"])
    env = jload(env_path)
    if env.get("status") in ("MERGED", "POST_MERGE_VERIFIED"):
        fail([f"envelope already {env.get('status')}"])
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == args.envelope), None)
    if entry is None:
        fail([f"envelope not queued: {args.envelope}"])
    if entry.get("status") not in ("WAITING", "CORRECTION_REQUIRED"):
        fail([
            f"queue entry status {entry.get('status')} is not WAITING/CORRECTION_REQUIRED; "
            "only a waiting or corrected entry may merge"
        ])
    base = env.get("base", "main")
    repo = root / env.get("repository", "pilot/repo")
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
    checks = envelope_checks(root, env)
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
    entry["status"] = "MERGING"
    save_queue(root, queue)
    append_supervision_ledger(root, "MERGE_START", "supervision",
                              {"envelope": args.envelope, "supervisor": args.supervisor})
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
    env.update({"status": "MERGED", "merge_commit": merge_commit,
                "merged_at": now(), "supervisor": args.supervisor})
    jdump(env_path, env)
    entry["status"] = "MERGED"
    entry["merge_commit"] = merge_commit
    save_queue(root, queue)
    add_merge_ledger(root, {
        "envelope_id": args.envelope, "task": env.get("task"),
        "implementation_head_sha": env.get("implementation_head_sha"),
        "envelope_head_sha": env.get("envelope_head_sha"),
        "merge_commit": merge_commit, "supervisor": args.supervisor,
        "at": now(),
    })
    append_supervision_ledger(root, "MERGE", "supervision",
                              {"envelope": args.envelope, "merge_commit": merge_commit})
    emit({"ok": True, "envelope": args.envelope, "status": "MERGED",
          "merge_commit": merge_commit})


def cmd_post_merge(root: Path, args) -> None:
    env_path = root / "supervision" / "envelopes" / f"{args.envelope}.json"
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
    repo = root / env.get("repository", "pilot/repo")
    base = env.get("base", "main")
    a = env.get("implementation_head_sha")
    envelope_path = env.get("envelope_path")
    env_vars = dict(os.environ)
    env_vars["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", env=env_vars,
    )
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
        f"- test_exit: {tests.returncode}\n\n## Test output\n\n"
        f"{tests.stdout}\n{tests.stderr}\n", encoding="utf-8")
    checks = [
        {"name": "post-merge tests pass", "ok": tests.returncode == 0,
         "detail": f"exit {tests.returncode}"},
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
    ok = args.result == "PASS" and all(c["ok"] for c in checks)
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
        append_supervision_ledger(root, "POST_MERGE_VERIFIED", "supervision",
                                  {"envelope": args.envelope, "checks": checks})
        emit({"ok": True, "envelope": args.envelope, "status": "POST_MERGE_VERIFIED",
              "checks": checks, "review": rel(root, review_file)})
    env["status"] = "CORRECTION_REQUIRED"
    jdump(env_path, env)
    if entry is not None:
        entry["status"] = "CORRECTION_REQUIRED"
        save_queue(root, queue)
    append_supervision_ledger(root, "POST_MERGE_FAILED", "supervision",
                              {"envelope": args.envelope, "result": args.result,
                               "checks": checks})
    emit({"ok": False, "envelope": args.envelope, "status": "CORRECTION_REQUIRED",
          "checks": checks, "review": rel(root, review_file)}, 2)


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
    emit({"ok": True, "tower": state.get("tower_id"), "role": state.get("role"),
          "phase": state.get("phase"), "next_action": state.get("next_action"),
          "tasks": board.get("tasks", [])})


def verify_ledger_file(root: Path, name: str) -> dict:
    """Validate one ledger file: JSON, seq continuity, hashes and prev links."""
    path = root / "ledger" / LEDGER_FILES[name]
    rows = ledger_rows(path)
    result = {
        "path": rel(root, path),
        "exists": path.exists(),
        "events": 0,
        "legacy_unhashed": 0,
        "errors": [],
    }
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

    de = sub.add_parser("deliver")
    de.add_argument("--task", required=True)
    de.add_argument("--evidence", action="append", required=True)

    cb = sub.add_parser("checkback")
    cb.add_argument("--task", required=True)
    cb.add_argument("--reviewer", required=True)
    cb.add_argument("--verdict", required=True, choices=["PASS", "FAIL"])
    cb.add_argument("--note")

    ac = sub.add_parser("accept")
    ac.add_argument("--task", required=True)
    ac.add_argument("--decision", required=True)
    ac.add_argument("--note")

    cl = sub.add_parser("close")
    cl.add_argument("--task", required=True)
    return p


def main() -> None:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    if not root.exists():
        fail([f"root not found: {root}"])
    handlers = {
        "init": cmd_init, "wiring": cmd_wiring, "startup": cmd_startup,
        "status": cmd_status, "phase": cmd_phase, "task-new": cmd_task_new, "check": cmd_check,
        "spec-approve": cmd_spec_approve,
        "task-next": cmd_task_next,
        "hash": cmd_hash, "dispatch": cmd_dispatch, "deliver": cmd_deliver,
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
    }
    try:
        handlers[args.cmd](root, args)
    except LedgerLockTimeout as exc:
        fail([str(exc)])


if __name__ == "__main__":
    main()
