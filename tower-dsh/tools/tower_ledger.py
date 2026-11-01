"""Append-only ledgers/registries: hash chain, lock, task ids."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tower_common import (
    TASK_ID_RE, check_task_id, emit, fail, is_safe_id, jdump, jload, now, rel,
    resolve_input_within,
)


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
    except OSError:
        # A pending-delete / sharing violation is contention, not staleness.
        return False
    if time.time() - stat.st_mtime <= stale_after:
        return False
    # Displace atomically so two waiters cannot both break the same lock.
    displaced = path.with_name(f"{path.name}.stale.{os.getpid()}.{time.time_ns()}")
    try:
        os.replace(path, displaced)
    except FileNotFoundError:
        return True
    except PermissionError:
        # Windows can deny the displacement while the lock is pending delete;
        # report "not cleared" so the caller keeps waiting/retrying.
        return False
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
        except PermissionError:
            # Windows reports a lock file that another thread is deleting
            # (pending delete) as EACCES instead of EEXIST.  Treat it as
            # contention there; on POSIX a PermissionError is a real error.
            if os.name != "nt":
                raise
            fd = None
        if fd is not None:
            try:
                os.write(fd, f"pid={os.getpid()} at={now()}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return
        if _clear_stale_lock(path, stale_after):
            # "Nothing to clear" must still honour the deadline.  A persistent
            # PermissionError against a path that does not exist (Windows ACL /
            # pending-delete) makes _clear_stale_lock() return True forever;
            # without this check the caller would spin instead of timing out.
            if time.monotonic() >= deadline:
                raise LedgerLockTimeout(
                    f"ledger write lock busy for more than {timeout:g}s: {path}")
            time.sleep(LEDGER_LOCK_POLL_INTERVAL)
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
    except OSError:
        # Windows pending-delete / sharing violation: the lock is going away
        # and release must never raise out of the lock's finally block.
        return
    if identity is not None and (current.st_dev, current.st_ino) != (
            identity.st_dev, identity.st_ino):
        # The lock was broken and re-taken by somebody else; leave it alone.
        return
    try:
        path.unlink()
    except OSError:
        # Never propagate: at worst the stale-lock cleaner removes it later.
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
    except OSError:
        # A transient stat failure only disables the identity check.
        identity = None
    try:
        yield path
    finally:
        _release_lock_file(path, identity)


@contextmanager
def authority_lock(root: Path, timeout: float | None = None,
                   stale_after: float | None = None):
    """Single-writer lock around the whole authority read/write/append section.

    PILOT-039: ``authority-set``/``authority-require`` read the current
    revision (or the policy half), validate, write the file and append the
    ledger event.  Without one lock around that whole section two writers can
    read the same revision, or race the same ``.tmp`` file.  This lock is
    always taken *before* ``append_ledger`` takes the ledger lock; the reverse
    order is forbidden (and no code does it).  Timeouts raise
    :class:`LedgerLockTimeout`, which ``main`` turns into one JSON payload with
    exit 2; the acquire path creates no file, so a timeout leaves no residue.
    """
    path = root / AUTHORITY_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = LEDGER_LOCK_TIMEOUT if timeout is None else timeout
    stale = LEDGER_LOCK_STALE_AFTER if stale_after is None else stale_after
    _acquire_lock_file(path, limit, stale)
    try:
        identity = path.stat()
    except OSError:
        identity = None
    try:
        yield path
    finally:
        _release_lock_file(path, identity)


def _append_ledger_event_locked(root: Path, filename: str, event_type: str,
                                actor: str, payload: dict) -> dict:
    """Append one event assuming the caller already holds ``ledger_lock``.

    ``ledger_lock`` is deliberately not re-entrant.  ``completion-add`` has to
    read the ledger, decide whether the ``COMPLETION_ADDED`` half is missing
    (idempotency / half-write repair) and append inside one critical section,
    so the locked append is factored out instead of taking the lock twice.
    """
    ledger = root / "ledger" / filename
    ledger.parent.mkdir(parents=True, exist_ok=True)
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


def _append_ledger_event(root: Path, filename: str, event_type: str,
                         actor: str, payload: dict) -> dict:
    with ledger_lock(root):
        return _append_ledger_event_locked(
            root, filename, event_type, actor, payload)


def append_ledger(root: Path, event_type: str, actor: str, payload: dict) -> dict:
    return _append_ledger_event(root, LEDGER_FILES["primary"], event_type, actor, payload)


def append_supervision_ledger(root: Path, event_type: str, actor: str,
                              payload: dict) -> dict:
    return _append_ledger_event(root, LEDGER_FILES["supervision"], event_type, actor, payload)


def task_dir(root: Path, tid: str) -> Path:
    return root / "tasks" / check_task_id(tid)


TASK_IDS_SCHEMA = "tower/task-ids@1"


TASK_IDS_REL = "state/TASK_IDS.json"


TASK_IDS_LOCK_FILE = "state/.task-ids.lock"


TASK_ID_STATUSES = ("reserved", "active", "closed", "void")


TASK_ID_VOID_RE = re.compile(r"-VOID\d*$")


@contextmanager
def task_ids_lock(root: Path, timeout: float | None = None,
                  stale_after: float | None = None):
    """Single-writer lock around the registry read/modify/write section.

    Same primitive as :func:`authority_lock`: ``jdump`` keeps the write itself
    atomic, so only the read-then-write window needs the lock.  The lock file is
    created under ``state/`` and released in ``finally`` even when a gate fails.
    """
    path = root / TASK_IDS_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = LEDGER_LOCK_TIMEOUT if timeout is None else timeout
    stale = LEDGER_LOCK_STALE_AFTER if stale_after is None else stale_after
    _acquire_lock_file(path, limit, stale)
    try:
        identity = path.stat()
    except OSError:
        identity = None
    try:
        yield path
    finally:
        _release_lock_file(path, identity)


def task_id_base(name: str) -> str:
    """The id a task directory owns (``PILOT-055-VOID2`` -> ``PILOT-055``)."""
    return TASK_ID_VOID_RE.sub("", name)


def task_id_dir_status(name: str, record: dict) -> str:
    """Registry status for one directory: closed, then void, else active."""
    if record.get("status") == "closed":
        return "closed"
    return "void" if "-VOID" in name else "active"


def task_id_record(tdir: Path) -> dict:
    """The directory's record, or ``{}`` when it is absent/unreadable."""
    path = tdir / "record.json"
    if not path.is_file():
        return {}
    try:
        record = jload(path)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def task_id_spec_path(root: Path, tid: str, record: dict) -> str | None:
    """The recorded spec path, else ``pilot/<id>.spec.json`` when it exists."""
    recorded = record.get("spec_path")
    if isinstance(recorded, str) and recorded:
        return recorded
    candidate = root / "pilot" / f"{tid}.spec.json"
    return rel(root, candidate) if candidate.is_file() else None


def task_id_title(root: Path, tid: str, record: dict) -> str:
    """The card/spec title recorded for an id, falling back to the id itself."""
    title = record.get("title")
    if isinstance(title, str) and title.strip():
        return title
    spec_path = task_id_spec_path(root, tid, record)
    if spec_path:
        try:
            spec = jload(root / spec_path)
        except (OSError, ValueError):
            spec = None
        if isinstance(spec, dict) and isinstance(spec.get("title"), str):
            return spec["title"]
    return tid


def task_id_entry(root: Path, tid: str, record: dict, status: str) -> dict:
    """One registry entry; card timestamps are kept, ``now`` fills the gaps."""
    stamp = now()
    return {
        "title": task_id_title(root, tid, record),
        "status": status,
        "spec_path": task_id_spec_path(root, tid, record),
        "created_at": record.get("created_at") or stamp,
        "updated_at": record.get("updated_at") or stamp,
    }


def scan_task_ids(root: Path) -> dict[str, dict]:
    """Every id already present under ``tasks/`` (``-VOID`` dirs included).

    Directories are walked in sorted order and the first directory for an id
    wins, so the canonical ``PILOT-NNN`` card (which sorts before its
    ``-VOID``/``-VOID2`` tombstones) decides the recorded status.  The result is
    sorted by id, which makes repeated ``task-ids-init`` runs byte-stable.
    """
    entries: dict[str, dict] = {}
    tasks = root / "tasks"
    if not tasks.is_dir():
        return entries
    for tdir in sorted(path for path in tasks.iterdir() if path.is_dir()):
        tid = task_id_base(tdir.name)
        if tid in entries or not is_safe_id(tid, TASK_ID_RE):
            continue
        record = task_id_record(tdir)
        entries[tid] = task_id_entry(
            root, tid, record, task_id_dir_status(tdir.name, record))
    return dict(sorted(entries.items()))


def load_task_ids(root: Path) -> dict[str, dict] | None:
    """The registry entries, ``None`` when absent, exit 2 when malformed."""
    path = root / TASK_IDS_REL
    if not path.is_file():
        return None
    try:
        data = jload(path)
    except (OSError, ValueError) as exc:
        fail([f"task id registry unreadable: {TASK_IDS_REL}: {exc}"])
    if not isinstance(data, dict) or data.get("schema") != TASK_IDS_SCHEMA:
        fail([f"task id registry must be a {TASK_IDS_SCHEMA} object: "
              f"{TASK_IDS_REL}"])
    entries = data.get("ids")
    if not isinstance(entries, dict):
        fail([f"task id registry ids must be an object: {TASK_IDS_REL}"])
    ids: dict[str, dict] = {}
    for tid, entry in entries.items():
        if not isinstance(entry, dict):
            fail([f"task id registry entry {tid} must be an object"])
        if entry.get("status") not in TASK_ID_STATUSES:
            fail([f"task id registry entry {tid} has invalid status "
                  f"{entry.get('status')!r}"])
        ids[str(tid)] = entry
    return ids


def task_id_view(root: Path) -> dict[str, dict]:
    """The registry, or an in-memory scan while it does not exist yet.

    Legacy fixtures and pre-PILOT-057 towers have cards but no registry; they
    must keep working, so a missing registry is read as "whatever ``tasks/``
    proves" instead of failing.  This function never writes: ``task-new``
    bootstraps on its own successful write, ``check`` only reads.
    """
    entries = load_task_ids(root)
    return scan_task_ids(root) if entries is None else entries


def task_ids_save(root: Path, ids: dict[str, dict], failure: str) -> None:
    """Write the sorted registry atomically or exit 2 naming what was kept."""
    try:
        jdump(root / TASK_IDS_REL,
              {"schema": TASK_IDS_SCHEMA, "ids": dict(sorted(ids.items()))})
    except OSError as exc:
        fail([f"{failure}: {exc}",
              f"{TASK_IDS_REL} is unchanged; run task-ids-init to repair it"])


def activate_task_id(root: Path, record: dict, base: dict[str, dict]) -> None:
    """Register a card that was just written as ``active`` (bootstraps too).

    ``base`` is the registry view taken *before* the card existed: a missing
    registry must be seeded from that view, because re-scanning after the write
    would find this very card and refuse it as a duplicate.
    """
    tid = str(record["id"])
    with task_ids_lock(root):
        ids = load_task_ids(root)
        if ids is None:
            ids = dict(base)
        if tid in ids and ids[tid].get("status") != "reserved":
            fail([f"task id already registered: {tid} "
                  f"(status {ids[tid].get('status')})"])
        ids[tid] = task_id_entry(root, tid, record, "active")
        task_ids_save(root, ids, f"task card written but id {tid} was not "
                                 "registered")


def close_task_id(root: Path, record: dict) -> None:
    """Mark the closed card's id ``closed``; the entry is never removed."""
    tid = str(record["id"])
    with task_ids_lock(root):
        ids = task_id_view(root)
        entry = ids.get(tid) or task_id_entry(root, tid, record, "closed")
        entry["status"] = "closed"
        entry["updated_at"] = now()
        ids[tid] = entry
        task_ids_save(root, ids, f"task {tid} is closed but its id registry "
                                 "entry was not updated")


def spec_registry_errors(root: Path, record: dict) -> list[str]:
    """``check --phase spec``: the id must be registered under the same title."""
    tid = str(record.get("id") or "")
    entry = task_id_view(root).get(tid)
    if entry is None:
        return [f"task id not registered: {tid}; run task-ids-init to backfill "
                f"{TASK_IDS_REL}"]
    expected = record.get("title")
    spec_path = record.get("spec_path")
    if spec_path:
        try:
            spec = jload(root / spec_path)
        except (OSError, ValueError):
            spec = None
        if isinstance(spec, dict) and isinstance(spec.get("title"), str):
            expected = spec["title"]
    if entry.get("title") != expected:
        return [f"task id registry title mismatch for {tid}: registry "
                f"{entry.get('title')!r} != spec {expected!r}"]
    return []


def cmd_task_ids_init(root: Path, args) -> None:
    """Backfill the registry from ``tasks/``; existing entries are never edited."""
    scanned = scan_task_ids(root)
    with task_ids_lock(root):
        ids = load_task_ids(root) or {}
        added = [tid for tid in scanned if tid not in ids]
        for tid in added:
            ids[tid] = scanned[tid]
        task_ids_save(root, ids, "cannot write the task id registry")
        total = len(ids)
    emit({"ok": True, "registry": TASK_IDS_REL, "scanned": len(scanned),
          "added": len(added), "ids": total})


def cmd_task_ids_reserve(root: Path, args) -> None:
    """Reserve an id for a draft with no card yet (any existing id exits 2)."""
    tid = check_task_id(args.id)
    title = (args.title or "").strip()
    if not title:
        fail(["--title must be a non-empty string"])
    spec_path = (rel(root, resolve_input_within(root, args.spec, "spec"))
                 if args.spec else None)
    with task_ids_lock(root):
        ids = task_id_view(root)
        if tid in ids:
            fail([f"task id already registered: {tid} "
                  f"(status {ids[tid].get('status')})"])
        stamp = now()
        ids[tid] = {"title": title, "status": "reserved",
                    "spec_path": spec_path, "created_at": stamp,
                    "updated_at": stamp}
        task_ids_save(root, ids, f"cannot reserve {tid}")
    emit({"ok": True, "task": tid, "status": "reserved",
          "registry": TASK_IDS_REL})


AUTHORITY_LOCK_FILE = "state/.authority.lock"
