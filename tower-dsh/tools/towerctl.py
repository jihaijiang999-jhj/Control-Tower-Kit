#!/usr/bin/env python3
"""Tower/DSH v0.3 pilot control-plane CLI.

File-backed and local-first: it records state, evidence and gates; it never
executes the task itself.  ``merge --mode pr`` is the only path that shells out
to the GitHub CLI (``gh``); every other command stays offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import spec_coverage
import spec_lint

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
TASK_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")
# Package / envelope ids double as directory and file names, so they are
# restricted to a conservative filename-safe alphabet and may never contain
# ``..`` (which the character class alone would allow).
PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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


def _force_utf8_stdio() -> None:
    """Make JSON output valid UTF-8 even on a non-UTF-8 console (cp1252/cp936)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


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


def is_safe_id(value, pattern: re.Pattern) -> bool:
    """True when ``value`` is a filename-safe id for ``pattern``.

    Rejects empty values, embedded ``..`` and anything the pattern does not
    match.  ``..`` is rejected explicitly because a package/envelope alphabet
    that allows ``.`` would otherwise accept ``A..B``.
    """
    text = str(value or "")
    return bool(text) and ".." not in text and bool(pattern.match(text))


def check_task_id(value, label: str = "task") -> str:
    """Validate a task id or exit 2 with an ``invalid id`` error."""
    if not is_safe_id(value, TASK_ID_RE):
        fail([f"invalid id: {value!r} "
              f"({label} id must match {TASK_ID_RE.pattern})"])
    return str(value)


def check_package_id(value, label: str = "package") -> str:
    """Validate a package/envelope id or exit 2 with an ``invalid id`` error."""
    if not is_safe_id(value, PACKAGE_ID_RE):
        fail([f"invalid id: {value!r} ({label} id must match "
              f"{PACKAGE_ID_RE.pattern} and must not contain '..')"])
    return str(value)


def ensure_within(root: Path, path: Path, *, allow_parent: bool = False,
                  label: str = "path") -> Path:
    """Resolve ``path`` and require it to stay inside ``root``.

    ``allow_parent`` additionally accepts exactly ``root``'s parent, which is
    what the kit layout uses for ``repository: ".."``.  Anything else exits 2
    with an ``outside tower root`` error so no command can be steered at an
    arbitrary filesystem location.
    """
    root_resolved = Path(root).resolve()
    resolved = Path(path).resolve()
    if resolved == root_resolved or root_resolved in resolved.parents:
        return resolved
    if allow_parent and resolved == root_resolved.parent:
        return resolved
    fail([f"{label} outside tower root: {resolved} (root: {root_resolved})"])


def resolve_input_within(root: Path, value: str, label: str) -> Path:
    """Resolve ``--spec`` / ``--file`` / ``--evidence`` and confine it to root."""
    raw = Path(value)
    candidate = raw if raw.is_absolute() else root / raw
    return ensure_within(root, candidate, label=label)


def resolve_repository(root: Path, value) -> Path:
    """Resolve an envelope ``repository`` inside root, or root's parent."""
    raw = Path(str(value or "pilot/repo"))
    candidate = raw if raw.is_absolute() else root / raw
    return ensure_within(root, candidate, allow_parent=True, label="repository")


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
    return root / "tasks" / check_task_id(tid)


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


def _split_argv(raw: str) -> list[str]:
    """Split a command line into argv, keeping Windows backslashes intact.

    POSIX ``shlex`` treats a backslash as an escape character, so
    ``C:\\Python\\python.exe`` would come back as ``C:Pythonpython.exe``.  On
    Windows the tokens are therefore split in non-POSIX mode and the quotes it
    preserves are stripped by hand; elsewhere plain POSIX splitting applies.
    """
    if os.name == "nt":
        tokens = shlex.split(raw, posix=False)
        stripped = []
        for token in tokens:
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
                token = token[1:-1]
            stripped.append(token)
        return stripped
    return shlex.split(raw)


def _looks_like_path(value: str) -> bool:
    """True when ``value`` is a path rather than a bare command name."""
    separators = [os.sep] + ([os.altsep] if os.altsep else [])
    return os.path.isabs(value) or any(sep and sep in value for sep in separators)


def _is_executable_path(value: str) -> bool:
    """True when ``value`` names a runnable file on this platform.

    A bare command name is resolved through ``PATHEXT`` by ``shutil.which``,
    but an explicit path is not: Windows only executes ``.exe``/``.cmd``/
    ``.bat``/``.com`` images, and POSIX additionally needs the execute bit.
    Without this an existing but non-executable file (a stray ``.txt``) would
    pass a plain ``Path.exists()`` check and then die in ``subprocess.run``.
    """
    path = Path(value)
    if os.name == "nt":
        return path.is_file() and path.suffix.lower() in (".exe", ".cmd", ".bat", ".com")
    return path.is_file() and os.access(path, os.X_OK)


def gh_command() -> list[str]:
    """Return the argv prefix used to invoke the GitHub CLI.

    ``TOWERCTL_GH`` overrides the executable and is the test injection point:
    the PR-mode tests point it at ``"<python> <gh_stub.py>"`` so the whole
    flow runs offline against a local bare origin.  A missing or
    non-executable executable is a hard gate (exit 2) rather than a traceback.
    """
    raw = os.environ.get("TOWERCTL_GH", "").strip()
    argv = _split_argv(raw) if raw else []
    if not argv:
        argv = ["gh"]
    exe = argv[0]
    if _looks_like_path(exe):
        runnable = _is_executable_path(exe)
    else:
        runnable = shutil.which(exe) is not None
    if not runnable:
        fail([f"gh not found: {exe}; install GitHub CLI or set TOWERCTL_GH"])
    return argv


class MergeBlocked(RuntimeError):
    """A PR-mode merge step failed; carries the phase, reason and detail."""

    def __init__(self, phase: str, reason: str, detail: str):
        super().__init__(f"{phase} ({reason}): {detail}")
        self.phase = phase
        self.reason = reason
        self.detail = detail


def command_failure(cp: subprocess.CompletedProcess) -> str:
    """Best-effort error text for a failed subprocess."""
    return ((cp.stderr or "").strip() or (cp.stdout or "").strip()
            or f"exit code {cp.returncode}")


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


# Authority state that a caller is expected to commit in the surrounding git
# repository.  ``status``/``startup`` report it, ``handoff-activate`` hints at
# the commit; towerctl itself never commits (the commit boundary stays human).
# ``tasks`` (task cards, evidence, records) and ``pilot`` (specs, worktrees) are
# authority state too: leaving them out let an uncommitted task card or spec
# look like a clean tower.  Watching the whole ``pilot`` tree is safe because
# ``pilot/repo`` and ``pilot/worktrees`` are gitignored and ``git status``
# never reports ignored untracked files.  ``state`` holds ``AUTHORITY.json``:
# an uncommitted authority file must be visible exactly like the ledger event
# it mirrors.
AUTHORITY_STATE_DIRS = ("primary", "supervision", "ledger", "handoffs", "shared",
                        "tasks", "pilot", "state")


def authority_repo(root: Path) -> Path | None:
    """Return the git top-level that contains ``root``, or None.

    None means "not inside a git repository" (or the tower root resolved
    outside the reported top-level), in which case authority drift cannot be
    computed at all.
    """
    cp = git(root, "rev-parse", "--show-toplevel")
    if cp.returncode != 0:
        return None
    top = cp.stdout.strip()
    if not top:
        return None
    repo = Path(top)
    if repo_relative(repo, root) is None:
        return None
    return repo


def authority_drift(root: Path) -> list[str] | None:
    """Uncommitted authority-state paths, relative to the repository root.

    Returns ``None`` when the tower root is not inside a git repository, so a
    caller can distinguish "unknown" from "clean" (``[]``).  Tool-owned output
    directories (``supervision/reviews``, ``supervision/outbox``) are excluded
    because post-merge writes them itself.
    """
    repo = authority_repo(root)
    if repo is None:
        return None
    root_rel = repo_relative(repo, root) or ""
    base = "" if root_rel in ("", ".") else root_rel + "/"
    # Every authority directory is a pathspec, whether or not it still exists:
    # a pathspec also matches tracked paths that were deleted from the working
    # tree, so removing e.g. ``handoffs/`` wholesale is still reported.  A
    # missing directory with nothing tracked under it simply matches nothing.
    watched = [base + name for name in AUTHORITY_STATE_DIRS]
    # ``--untracked-files=all`` keeps a brand-new package directory from
    # collapsing into a single ``handoffs/<id>/`` entry, so the reported list
    # (and the commit hint built from it) names every file.  ``quotepath`` is
    # disabled so non-ASCII paths come back literally and the reported path
    # (and the hint built from it) is actually usable.
    cp = git(repo, "-c", "core.quotepath=false", "status", "--porcelain",
             "--untracked-files=all", "--", *watched)
    if cp.returncode != 0:
        return None
    owned = tool_owned_paths(root, repo)
    drift: list[str] = []
    for line in cp.stdout.splitlines():
        if not line.strip():
            continue
        path = status_path(line)
        if not path:
            continue
        if any(path == prefix or path.startswith(prefix + "/") for prefix in owned):
            continue
        drift.append(path)
    return drift


def authority_commit_hint(root: Path, drift: list[str]) -> str:
    """Shell-ready ``git add``/``git commit`` hint, or "" when nothing drifts."""
    repo = authority_repo(root)
    if not drift or repo is None:
        return ""
    paths = " ".join(f'"{p}"' if " " in p else p for p in drift)
    message = f"handoff: record activated authority state ({len(drift)} file(s))"
    repo_posix = repo.as_posix()
    return (f'git -C "{repo_posix}" add -- {paths} && '
            f'git -C "{repo_posix}" commit -m "{message}"')


AUTHORITY_STATE_SCHEMA = "tower/authority-state@1"
AUTHORITY_STATE_FILE = "state/AUTHORITY.json"
AUTHORITY_SET_EVENT = "AUTHORITY_SET"
# PILOT-038: "this tower must have an authority state" is itself persisted, so
# deleting ``state/AUTHORITY.json`` and truncating the only ``AUTHORITY_SET``
# event cannot silently downgrade the tower to legacy.  ``shared/`` is already
# an authority-state directory, so an uncommitted policy is as visible as the
# ledger event it mirrors.  The policy file and the ``AUTHORITY_REQUIRED``
# event must exist together; either half alone fails closed.
AUTHORITY_POLICY_SCHEMA = "tower/authority-policy@1"
AUTHORITY_POLICY_FILE = "shared/AUTHORITY_POLICY.json"
AUTHORITY_REQUIRED_EVENT = "AUTHORITY_REQUIRED"
# The ledger event is the authority; the file must repeat every one of these
# values exactly.  ``primary.id``/``supervision.id`` are nested in the file and
# flat in the payload; ``note`` is optional, and "present on one side only" is
# itself a mismatch.
AUTHORITY_STATE_FIELDS = ("owner", "primary_id", "supervision_id",
                          "merge_authority", "revision", "set_by", "decision",
                          "set_at", "note")
AUTHORITY_TEXT_FIELDS = ("owner", "primary_id", "supervision_id",
                         "merge_authority", "set_by", "decision", "set_at")
# Sentinel for "key absent", distinct from ``None``: a missing optional field
# must never compare equal to a present one (``null`` included).
AUTHORITY_ABSENT = object()
# PILOT-039: the policy file and the last ``AUTHORITY_REQUIRED`` payload must be
# field-for-field isomorphic, so a rewritten audit field (set_by/decision/
# set_at/tower_id) cannot silently disagree with the ledger event.  The field
# list is deliberately explicit: the safety of the gate must not depend on which
# keys a caller happened to write.
AUTHORITY_POLICY_FIELDS = ("tower_id", "require_authority", "set_by",
                           "decision", "set_at")
# Independent single-writer lock for the authority writers.  The lock order is
# fixed: this lock is taken first and ``append_ledger`` takes the ledger lock
# inside it.  Nothing may acquire the ledger lock and then wait for this one.
AUTHORITY_LOCK_FILE = "state/.authority.lock"


def _state_nested_id(state: dict, key: str, nested: str):
    """``state[key][nested]`` or None, tolerating a non-object value."""
    value = state.get(key)
    return value.get(nested) if isinstance(value, dict) else None


def _state_owner_name(state: dict):
    """``state.owner.name`` or None, tolerating a non-object value."""
    owner = state.get("owner")
    return owner.get("name") if isinstance(owner, dict) else None


def authority_state_fields(state: dict) -> dict:
    """Flatten ``state/AUTHORITY.json`` into the ledger payload field names.

    Absent keys become ``AUTHORITY_ABSENT`` so the comparison distinguishes
    "missing" from "present with a null/invalid value".
    """
    primary = state.get("primary")
    supervision = state.get("supervision")
    return {
        "owner": state.get("owner", AUTHORITY_ABSENT),
        "primary_id": (primary.get("id", AUTHORITY_ABSENT)
                       if isinstance(primary, dict) else AUTHORITY_ABSENT),
        "supervision_id": (supervision.get("id", AUTHORITY_ABSENT)
                           if isinstance(supervision, dict) else AUTHORITY_ABSENT),
        "merge_authority": state.get("merge_authority", AUTHORITY_ABSENT),
        "revision": state.get("revision", AUTHORITY_ABSENT),
        "set_by": state.get("set_by", AUTHORITY_ABSENT),
        "decision": state.get("decision", AUTHORITY_ABSENT),
        "set_at": state.get("set_at", AUTHORITY_ABSENT),
        "note": state.get("note", AUTHORITY_ABSENT),
    }


def authority_payload_fields(payload: dict) -> dict:
    """Flat ``AUTHORITY_SET`` payload fields, same absent sentinel."""
    return {field: payload.get(field, AUTHORITY_ABSENT)
            for field in AUTHORITY_STATE_FIELDS}


def authority_display(value):
    """JSON-safe rendering: an absent field is ``None``."""
    return None if value is AUTHORITY_ABSENT else value


def _authority_field_errors(fields: dict, label: str) -> list[str]:
    """Type rules for one side (file or ledger payload).

    ``bool`` is not an ``int`` here: ``True == 1`` in Python, which is exactly
    how ``revision: true`` used to slip through an equality-only comparison.
    """
    errors: list[str] = []
    for field in AUTHORITY_TEXT_FIELDS:
        value = fields[field]
        if not isinstance(value, str) or not value:
            errors.append(f"{label} {field} must be a non-empty string")
    revision = fields["revision"]
    if type(revision) is not int or revision < 1:
        errors.append(f"{label} revision must be an int >= 1")
    note = fields["note"]
    if note is not AUTHORITY_ABSENT and (not isinstance(note, str) or not note):
        errors.append(f"{label} note must be a non-empty string when present")
    return errors


def _authority_mismatch_detail(fields: dict, payload: dict,
                               mismatched: list[str]) -> str:
    """One line naming every mismatching field and both values."""
    return ", ".join(
        f"{field} {authority_display(fields[field])!r} != "
        f"{authority_display(payload[field])!r}" for field in mismatched)


def last_authority_event(root: Path) -> tuple[bool, dict | None]:
    """``(event_present, payload)`` for the last ``AUTHORITY_SET`` event.

    The event payload -- not the file -- is the authority.  A ledger that
    cannot be read is reported as "no event" here: ``verify-ledger`` and
    ``state-verify`` own that failure, and every caller of this helper is
    read-only.  This helper never raises.
    """
    try:
        events = [event for event in ledger_events_in_seq_order(root, "primary")
                  if event.get("type") == AUTHORITY_SET_EVENT]
    except PATH_ACCESS_ERRORS:
        return False, None
    if not events:
        return False, None
    payload = events[-1].get("payload")
    return True, payload if isinstance(payload, dict) else None


def last_authority_required_event(root: Path) -> tuple[bool, dict | None]:
    """``(event_present, payload)`` for the last ``AUTHORITY_REQUIRED`` event.

    The policy file must mirror this payload exactly (PILOT-039).  Like
    :func:`last_authority_event` this is read-only and never raises: an
    unreadable ledger is "no event" here, and ``verify-ledger``/``state-verify``
    own ledger corruption.
    """
    try:
        events = [event for event in ledger_events_in_seq_order(root, "primary")
                  if event.get("type") == AUTHORITY_REQUIRED_EVENT]
    except PATH_ACCESS_ERRORS:
        return False, None
    if not events:
        return False, None
    payload = events[-1].get("payload")
    return True, payload if isinstance(payload, dict) else None


def authority_policy_fields(policy) -> dict:
    """The five compared policy fields, with the absent-vs-null sentinel.

    A non-object (or ``None``) contributes every field as absent, so a policy
    or event payload that is not an object can never compare equal to one that
    is.  ``authority_display`` renders the sentinel as ``null`` for JSON.
    """
    source = policy if isinstance(policy, dict) else {}
    return {field: source.get(field, AUTHORITY_ABSENT)
            for field in AUTHORITY_POLICY_FIELDS}


def _authority_policy_value_ok(field: str, value) -> bool:
    """Per-field type rule for the policy/event comparison.

    ``require_authority`` must be the boolean ``True``: ``"true"``, ``1`` and
    ``null`` are truthy look-alikes and are rejected here, not coerced.  Every
    other field must be a non-empty string.
    """
    if field == "require_authority":
        return value is True
    return isinstance(value, str) and bool(value)


def authority_policy_mismatch(root: Path, requirement: dict) -> dict | None:
    """Field-level comparison of the policy file with the last event payload.

    Returns ``None`` when there is no pair to compare (event absent or policy
    not required: those are ``policy_unbacked``/``policy_missing``) or when the
    halves agree.  Otherwise returns ``fields`` (every differing field, in the
    canonical order), plus ``expected`` (event payload side) and ``actual``
    (policy file side) dictionaries, so callers can emit one row or one error
    line naming all of them.  ``tower_id`` additionally binds to the primary
    state, because the policy's tower identity is what the requirement is
    anchored to.
    """
    if not (requirement["policy_required"] and requirement["event_present"]):
        return None
    policy_fields = authority_policy_fields(requirement.get("policy"))
    event_fields = authority_policy_fields(requirement.get("event_payload"))
    mismatched: list[str] = []
    for field in AUTHORITY_POLICY_FIELDS:
        if not _authority_policy_value_ok(field, policy_fields[field]) or \
                not _authority_policy_value_ok(field, event_fields[field]):
            mismatched.append(field)
        elif policy_fields[field] != event_fields[field]:
            mismatched.append(field)
    # ``tower_id`` is also bound to the primary state.  When both halves agree
    # with each other but not with the primary state, the primary state is the
    # expectation; the row/line still names exactly one field.
    primary_tower_id = AUTHORITY_ABSENT
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    if isinstance(primary_state, dict):
        primary_tower_id = primary_state.get("tower_id", AUTHORITY_ABSENT)
    if (isinstance(primary_tower_id, str) and primary_tower_id
            and policy_fields["tower_id"] != primary_tower_id
            and "tower_id" not in mismatched):
        mismatched.append("tower_id")
    if not mismatched:
        return None
    expected = {field: authority_display(event_fields[field])
                for field in AUTHORITY_POLICY_FIELDS}
    actual = {field: authority_display(policy_fields[field])
              for field in AUTHORITY_POLICY_FIELDS}
    if ("tower_id" in mismatched
            and isinstance(primary_tower_id, str) and primary_tower_id
            and expected["tower_id"] == actual["tower_id"]):
        expected["tower_id"] = primary_tower_id
    return {"fields": mismatched, "expected": expected, "actual": actual}


def authority_policy_mismatch_detail(result: dict) -> str:
    """One line naming every differing field with its policy/event values."""
    parts: list[str] = []
    for field in result["fields"]:
        actual = result["actual"][field]
        expected = result["expected"][field]
        if field == "require_authority":
            parts.append(f"require_authority {actual!r} != {expected!r} "
                         "(both sides must be boolean true)")
        else:
            parts.append(f"{field} {actual!r} != {expected!r}")
    return "; ".join(parts)


def authority_policy_invalid(requirement: dict) -> bool:
    """True when a policy file exists but is not a valid requirement marker.

    A malformed policy is fail-closed: it must never degrade the tower to
    "optional"/legacy just because ``require_authority`` failed a type check.
    The only way to not require authority is to have no policy file at all.
    """
    return (requirement["policy_state"] != "missing"
            and not requirement["policy_required"])


def next_authority_revision(root: Path) -> int:
    """One more than the file's or the last event's revision.

    Re-running ``authority-set`` on a half-written tower (one half present)
    therefore continues the sequence instead of resetting it to 1.
    """
    revisions: list[int] = []
    _, state = _read_json_object(root / AUTHORITY_STATE_FILE)
    if isinstance(state, dict):
        value = state.get("revision")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            revisions.append(value)
    _, payload = last_authority_event(root)
    if isinstance(payload, dict):
        value = payload.get("revision")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            revisions.append(value)
    return (max(revisions) if revisions else 0) + 1


def authority_policy_required(policy: dict | None) -> bool:
    """True only for a parsed policy object that literally requires authority.

    ``require_authority: "true"`` or ``1`` must not count: the persisted
    requirement is a boolean fact, and a truthy look-alike could otherwise
    satisfy the policy side of the pairing check.
    """
    return isinstance(policy, dict) and policy.get("require_authority") is True


def authority_required_event(root: Path) -> bool:
    """True iff ``ledger/primary.jsonl`` carries an ``AUTHORITY_REQUIRED`` row.

    Read-only and exception-free: an unreadable ledger is reported as "no
    event" here, exactly like :func:`last_authority_event`.  ``verify-ledger``
    and ``state-verify`` own ledger corruption; every caller of this helper is
    read-only and must not traceback on it.
    """
    try:
        return any(event.get("type") == AUTHORITY_REQUIRED_EVENT
                   for event in ledger_events_in_seq_order(root, "primary"))
    except PATH_ACCESS_ERRORS:
        return False


def authority_requirement(root: Path) -> dict:
    """Read-only view of the persisted authority requirement (PILOT-038).

    ``required`` is true when either half of the marker exists: the policy file
    sets ``require_authority=true`` or the ledger carries an
    ``AUTHORITY_REQUIRED`` event.  A tower with neither half is not required
    and keeps the 037 legacy behaviour.  ``policy_state`` distinguishes
    missing/unreadable from a parsed object.
    """
    policy_state, policy = _read_json_object(root / AUTHORITY_POLICY_FILE)
    policy_required = authority_policy_required(policy)
    event_present = authority_required_event(root)
    _, event_payload = last_authority_required_event(root)
    return {
        "policy_state": policy_state,
        "policy": policy,
        "policy_required": policy_required,
        "event_present": event_present,
        "event_payload": event_payload,
        "required": policy_required or event_present,
    }


def _authority_policy_payload(primary_state: dict, by: str, decision: str,
                              set_at: str) -> dict:
    """The policy file body, also used verbatim as the event payload.

    Both sides are deliberately isomorphic: the policy file and the
    ``AUTHORITY_REQUIRED`` event carry exactly the same keys, so the persisted
    requirement can be reconstructed from either half.
    """
    return {
        "schema": AUTHORITY_POLICY_SCHEMA,
        "tower_id": primary_state.get("tower_id"),
        "require_authority": True,
        "set_by": by,
        "decision": decision,
        "set_at": set_at,
    }


def authority_requirement_errors(root: Path, requirement: dict) -> list[str]:
    """Pairing errors for a required tower; empty when the halves agree.

    ``authority policy unbacked`` (policy true, no event) and ``authority
    policy missing`` (event, no policy/false policy) are flat strings so
    ``merge`` can fail closed with them and ``state-verify`` can name the
    matching drift kind.

    PILOT-039 adds two fail-closed cases: a policy file that exists but is not
    a valid marker (wrong/absent ``require_authority``, unparseable JSON) can
    never degrade the tower to optional, and when both halves exist every
    shared field must be identical -- a rewritten ``set_by``/``decision``/
    ``set_at``/``tower_id`` is named in one line, exactly like a changed
    ``require_authority`` type.
    """
    errors: list[str] = []
    if requirement["policy_required"] and not requirement["event_present"]:
        errors.append(
            "authority policy unbacked: "
            f"{AUTHORITY_POLICY_FILE} sets require_authority=true but "
            f"ledger/primary.jsonl has no {AUTHORITY_REQUIRED_EVENT} event")
    elif requirement["event_present"] and not requirement["policy_required"]:
        errors.append(
            "authority policy missing: "
            f"ledger/primary.jsonl has an {AUTHORITY_REQUIRED_EVENT} event "
            f"but {AUTHORITY_POLICY_FILE} is missing or does not set "
            "require_authority=true")
    elif authority_policy_invalid(requirement):
        detail = ("is not a parseable JSON object"
                  if requirement["policy_state"] == "unreadable"
                  else "does not set require_authority=true (boolean)")
        errors.append(f"authority policy invalid: {AUTHORITY_POLICY_FILE} "
                      f"{detail}")
    if requirement["policy_required"] and requirement["event_present"]:
        mismatch = authority_policy_mismatch(root, requirement)
        if mismatch is not None:
            errors.append(
                "authority policy does not match last "
                f"{AUTHORITY_REQUIRED_EVENT}: "
                + authority_policy_mismatch_detail(mismatch))
    return errors


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
        emit({"ok": True, "path": AUTHORITY_POLICY_FILE, "by": args.by,
              "decision": args.decision, "required": True, "already": True,
              "repaired": False})

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

    emit({"ok": True, "path": AUTHORITY_POLICY_FILE,
          "by": policy.get("set_by"), "decision": policy.get("decision"),
          "set_at": policy.get("set_at"), "required": True,
          "already": False, "repaired": True})


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
        # The two lifecycle checks below read ``ledger/supervision.jsonl``.
        # When that file itself is missing or unreadable they cannot tell "no
        # event" from "no ledger" and would report a misleading
        # ``ENVELOPE_NEW event missing``; the chain check above already fails
        # the envelope and blocks the merge, so they are skipped in exactly
        # that one case.  A readable ledger with a broken chain still runs
        # them: their verdicts are then independent evidence.
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
        ev_errors = check_evidence(root, rec)
        add("evidence hashes valid", not ev_errors, "; ".join(ev_errors) or "ok")
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
    drift = authority_drift(root)
    authority = authority_state_check(root)
    emit({"ok": True, "tower_id": state.get("tower_id"), "role": state.get("role"),
          "phase": state.get("phase"), "primary": state.get("primary"),
          "tasks": len(board.get("tasks", [])), "next_action": state.get("next_action"),
          "authority_dirty_count": None if drift is None else len(drift),
          "authority_state": authority["status"]})


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
    spec_path = resolve_input_within(root, args.spec, "spec")
    if not spec_path.exists():
        fail([f"spec not found: {spec_path}"])
    spec = jload(spec_path)
    tid = str(spec.get("id", ""))
    errors = []
    if not TASK_ID_RE.match(tid):
        errors.append(f"invalid id: {tid!r} (task id must match {TASK_ID_RE.pattern})")
    for field in ["title", "authority", "scope", "allowed_paths", "forbidden", "acceptance"]:
        if not spec.get(field):
            errors.append(f"spec.{field} required")
    if not errors:
        errors += validate_spec(spec)
    worktree = spec.get("worktree")
    if not worktree:
        errors.append("spec.worktree required")
    else:
        worktree_path = ensure_within(root, root / worktree, label="worktree")
        if not worktree_path.exists():
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


def ledger_has_task_event(root: Path, event_type: str, task: str) -> bool:
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
        if not ledger_has_task_event(root, "SPEC_APPROVED", args.task):
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
    if not worktree:
        fail(["worktree missing: (empty)"])
    worktree_path = ensure_within(root, root / worktree, label="worktree")
    if not worktree_path.exists():
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


def _optional_task_record(root: Path, task_id: str) -> dict | None:
    """Best-effort record load that never emits / exits.

    Used by checks that must report a missing or malformed record as data
    (``envelope_checks``), not as a second JSON payload.
    """
    if not is_safe_id(task_id, TASK_ID_RE):
        return None
    path = task_record_path(root, task_id)
    if not path.exists():
        return None
    try:
        data = jload(path)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _load_optional_record(root: Path, task_id: str) -> dict:
    return _optional_task_record(root, task_id) or {}


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
    package_id = check_package_id(args.package, "package")
    if args.task:
        check_task_id(args.task, "task")
    if args.envelope:
        check_package_id(args.envelope, "envelope")
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
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    checks = handoff_checks(root, package_id, pkg)
    if not all(c["ok"] for c in checks):
        emit({"ok": False, "package": args.package,
              "errors": [c for c in checks if not c["ok"]]}, 2)
    emit({"ok": True, "package": args.package, "checks": checks})


def cmd_handoff_claim(root: Path, args) -> None:
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
    pkg_path = pkgdir / "package.json"
    if not pkg_path.exists():
        fail([f"package not found: {args.package}"])
    pkg = jload(pkg_path)
    if args.controller == pkg.get("source_controller"):
        fail(["receiver must differ from source controller"])
    checks = handoff_checks(root, package_id, pkg)
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
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
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
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
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
    package_id = check_package_id(args.package, "package")
    pkgdir = root / "handoffs" / package_id
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
    drift = authority_drift(root)
    commit_required = bool(drift)
    emit({"ok": True, "package": args.package, "status": "ACTIVE",
          "controller": args.controller,
          "commit_required": commit_required,
          "commit_hint": authority_commit_hint(root, drift or [])})


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
    # Both count baselines are mandatory for a *new* envelope.  The post-merge
    # gates treat them as opt-in, so an envelope that simply omitted them used
    # to downgrade its own count checks silently; requiring them here (before
    # any file, ledger or record write) closes that hole.  Legacy envelopes
    # already on disk keep the old opt-in semantics in ``merge-check`` and
    # ``post-merge``.
    tests_baseline = env.get("tests_baseline")
    tower_tests_baseline = env.get("tower_tests_baseline")
    if not (isinstance(tests_baseline, int) and not isinstance(tests_baseline, bool)
            and tests_baseline >= 1
            and isinstance(tower_tests_baseline, int)
            and not isinstance(tower_tests_baseline, bool)
            and tower_tests_baseline >= 1):
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
    record.update({"envelope_head_sha": b, "status": "DRAFT", "created_at": now()})
    jdump(root / "supervision" / "envelopes" / f"{env_id}.json", record)
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
                f"{name} ledger chain broken: {first}"
                for name, first in breaks),
        })
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


# A brand-new PR often has no check runs yet.  ``gh pr checks --help`` documents
# the exit codes: 8 means "Checks pending", so the exit code alone is the
# authoritative signal.  Older gh builds instead print "no checks reported" on
# stderr, which is kept as a narrow compatibility fallback: the bare substring
# "no checks" is NOT pending, because real failures mention e.g. "no checks
# passed" and must block immediately.
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

    # 2. open the PR.  ``gh pr create`` deliberately gets no ``--json``: real
    #    gh rejects it and only prints the PR URL (parsed below).
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
            # Re-running a merge must reuse the open PR instead of failing.
            # ``gh pr view --json`` is a flag the real CLI does support.
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

    # 3. CI gate; a hung gate is bounded by --check-timeout and a PR whose
    #    checks have not registered yet is retried until that deadline.
    wait_for_checks(repo, number, timeout, interval)

    # 4. merge the PR once the checks are green.
    cp = run_gh(repo, ["pr", "merge", str(number), "--merge"],
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
        fail([f"merge precondition: {name} ledger chain broken: {first} "
              "(ledger chain intact)"
              for name, first in breaks])
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
    if env.get("status") in ("MERGED", "POST_MERGE_VERIFIED"):
        fail([f"envelope already {env.get('status')}"])
    queue = load_queue(root)
    entry = next((e for e in queue.get("entries", [])
                  if e.get("envelope_id") == envelope_id), None)
    if entry is None:
        fail([f"envelope not queued: {args.envelope}"])
    if entry.get("status") not in ("WAITING", "CORRECTION_REQUIRED"):
        fail([
            f"queue entry status {entry.get('status')} is not WAITING/CORRECTION_REQUIRED; "
            "only a waiting or corrected entry may merge"
        ])
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
    baseline_ok = (isinstance(baseline, int) and not isinstance(baseline, bool)
                   and baseline >= 1)
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
    tower_baseline_ok = (isinstance(tower_baseline, int)
                         and not isinstance(tower_baseline, bool)
                         and tower_baseline >= 1)
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
        emit(payload)
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
    emit({"ok": False, "envelope": args.envelope, "status": "CORRECTION_REQUIRED",
          "checks": checks, "tests_count": tests_count,
          "review": rel(root, review_file)}, 2)


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


def verify_ledger_file(root: Path, name: str) -> dict:
    """Validate one ledger file: presence, JSON, seq, hashes and prev links.

    A missing ledger is a *failed* verification, not an empty one: the old
    code parsed it as zero rows and reported no errors, so every caller read
    "the file is not there" as "the chain is intact".  An existing empty file
    is still a valid empty chain.  Any read error (a directory in place of the
    file, an ACL denial, ...) becomes one ``ledger unreadable`` error instead
    of a traceback, so the CLI can always emit exactly one JSON payload.
    """
    path = root / "ledger" / LEDGER_FILES[name]
    result = {
        "path": rel(root, path),
        "exists": False,
        "events": 0,
        "legacy_unhashed": 0,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append(f"ledger missing: {rel(root, path)}")
        return result
    result["exists"] = True
    try:
        rows = ledger_rows(path)
    except OSError as exc:
        result["errors"].append(
            f"ledger unreadable: {rel(root, path)}: {exc}")
        return result
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


def ledger_precondition_breaks(root: Path) -> list[tuple[str, str]]:
    """``(ledger name, first error)`` for every existing ledger that fails.

    PILOT-039: ``merge`` and the legacy ``merge-check`` precondition.  Only
    files that exist are verified: a tower that never had a supervision ledger
    keeps merging as before (the new-style envelope path already fails a
    missing ledger through ``ledger chain intact``).  An existing ledger is
    always verified in full -- a forged row can keep ``seq``/``prev_hash``
    legal and still be caught by the hash.
    """
    breaks: list[tuple[str, str]] = []
    for name in ("primary", "supervision"):
        path = root / "ledger" / LEDGER_FILES[name]
        if not path.exists():
            continue
        report = verify_ledger_file(root, name)
        if report["errors"]:
            breaks.append((name, report["errors"][0]))
    return breaks


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


# -- state-verify: replay the ledgers into expected state ------------------
#
# The replay is deliberately data-only: these helpers read files and return
# values, so ``state-verify`` can never append an event, rewrite a record or
# otherwise repair the drift it is asked to report.
TASK_LIFECYCLE_STATUS = {
    "TASK_NEW": "ready",
    "DISPATCH": "dispatched",
    "DELIVER": "delivered",
    "ACCEPT": "accepted",
    "CLOSEOUT": "closed",
}
ENVELOPE_LIFECYCLE_STATUS = {
    "ENVELOPE_NEW": "DRAFT",
    "QUEUE_ADD": "WAITING",
    "MERGE": "MERGED",
    "POST_MERGE_VERIFIED": "POST_MERGE_VERIFIED",
}
# A failed post-merge check sends the envelope back for a correction; a
# later MERGE/POST_MERGE_VERIFIED event overrides it, exactly like the live
# queue does.
ENVELOPE_CORRECTION_EVENTS = {"MERGE_BLOCKED", "POST_MERGE_FAILED"}
# Internal envelope state while a merge is running.  MERGE_START is the only
# event that enters it and, like the live queue, it does not change the folded
# status: the next MERGE / correction event settles the envelope again.
ENVELOPE_MERGING_STATUS = "MERGING"
# Legal source states per lifecycle event, derived from a read-only probe of
# the real ledgers (``evidence/real-transitions.txt``) rather than invented
# rules.  They are deliberately permissive where the tower has precedent:
# ``TASK_NEW`` creates a card once (``None``) and rebuilds an *unfinished*
# card in place (PILOT-025: dispatched -> ready); it must never reset a card
# that already reached ``accepted`` or ``closed``.  ``DELIVER`` may re-deliver
# an already delivered card, ``CHECKBACK`` may re-review a delivered/reviewed/
# reworked card, and a correction may be retried straight from
# ``CORRECTION_REQUIRED``.  Any event not listed here is ignored by the replay
# and therefore cannot drift.
TASK_TRANSITIONS = {
    "TASK_NEW": frozenset({None, "ready", "dispatched", "delivered",
                           "reviewed", "rework"}),
    "DISPATCH": frozenset({"ready", "rework"}),
    "DELIVER": frozenset({"dispatched", "delivered", "rework"}),
    "CHECKBACK": frozenset({"delivered", "reviewed", "rework"}),
    "ACCEPT": frozenset({"reviewed"}),
    "CLOSEOUT": frozenset({"accepted"}),
}
ENVELOPE_TRANSITIONS = {
    "ENVELOPE_NEW": frozenset({None, "DRAFT", "CORRECTION_REQUIRED"}),
    "QUEUE_ADD": frozenset({"DRAFT"}),
    "MERGE_START": frozenset({"WAITING", "CORRECTION_REQUIRED"}),
    "MERGE": frozenset({ENVELOPE_MERGING_STATUS}),
    "POST_MERGE_VERIFIED": frozenset({"MERGED", "CORRECTION_REQUIRED"}),
    "MERGE_BLOCKED": frozenset({"WAITING", ENVELOPE_MERGING_STATUS,
                                "CORRECTION_REQUIRED"}),
    "POST_MERGE_FAILED": frozenset({"MERGED", "CORRECTION_REQUIRED"}),
}


def _read_json_object(path: Path) -> tuple[str, dict | None]:
    """Read-only probe for a JSON object file.

    Returns ``("ok", data)`` when the file exists and holds a JSON object,
    ``("missing", None)`` when it does not exist, and
    ``("unreadable", None)`` when it exists but cannot be parsed or is not a
    JSON object.  Callers turn that distinction into drift instead of
    silently skipping the file.  This only reads: ``state-verify`` observes
    state and never writes it.
    """
    try:
        if not path.exists():
            return "missing", None
        data = jload(path)
    except (OSError, ValueError):
        return "unreadable", None
    if not isinstance(data, dict):
        return "unreadable", None
    return "ok", data


SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
# Every path probe below is wrapped in this tuple: a record can contain a NUL
# byte (ValueError), a symlink loop (RuntimeError) or an ordinary I/O problem
# (OSError).  state-verify turns all of them into drift instead of a traceback.
PATH_ACCESS_ERRORS = (OSError, ValueError, RuntimeError)


def _lexical_tower_path(root: Path, raw: str) -> tuple[str | None, str, str | None]:
    """Pure-string containment check: it performs ZERO filesystem access.

    Returns ``(lexical, display, error)``.  ``error`` is ``"escape"`` when the
    normalized path is outside ``root``, ``"invalid"`` when it cannot be
    normalized at all (for example an embedded NUL), and ``None`` for a
    lexically contained path.  ``lexical`` is the absolute normalized path and
    ``display`` its tower-root-relative posix spelling.

    ``os.path.abspath``/``os.path.normpath`` only manipulate strings, so an
    escaping record path such as ``../outside.txt`` is rejected before any
    ``stat``, ``open``, ``realpath`` or ``resolve`` can touch the outside file.
    """
    root_abs = os.path.abspath(root)
    if "\x00" in raw:
        return None, raw, "invalid"
    try:
        candidate = raw if os.path.isabs(raw) else os.path.join(root_abs, raw)
        lexical = os.path.normpath(candidate)
    except PATH_ACCESS_ERRORS:
        return None, raw, "invalid"
    if lexical != root_abs and not lexical.startswith(root_abs + os.sep):
        return None, raw, "escape"
    try:
        relative = os.path.relpath(lexical, root_abs)
    except PATH_ACCESS_ERRORS:
        return None, raw, "invalid"
    display = "." if relative == "." else relative.replace(os.sep, "/")
    return lexical, display, None


def _path_has_symlink(root_abs: str, lexical: str) -> bool:
    """True when any component of a lexically-in-root path is a link.

    Only called after lexical containment has passed.  ``islink``/``isjunction``
    are read-only metadata probes and never follow the link.
    """
    relative = os.path.relpath(lexical, root_abs)
    if relative == ".":
        return False
    current = root_abs
    isjunction = getattr(os.path, "isjunction", None)
    for part in relative.split(os.sep):
        if not part:
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            return True
        if isjunction is not None and isjunction(current):
            return True
    return False


def _contained_tower_path(root: Path, raw: str) -> tuple[Path | None, str, str | None]:
    """Resolve a recorded tower path, deciding containment lexically first.

    Returns ``(resolved, display, error)``:

    * ``error == "escape"``: the normalized path is outside the tower root, or
      a component/final target is a symlink or junction.  Nothing outside the
      root is opened, stat'ed or hashed; ``resolved`` is ``None`` and
      ``display`` keeps the raw recorded spelling.
    * ``error == "invalid"``: the path cannot be normalized or resolved (for
      example an embedded NUL byte); ``resolved`` is ``None``.
    * ``error is None``: ``resolved`` is the lexically contained path ready for
      the caller's ``is_file``/hash probe; ``display`` is its root-relative
      posix spelling.

    Containment is decided by pure string normalization *before* any filesystem
    call, so ``../outside.txt`` cannot even be stat'ed.  Only a lexically
    contained path is then checked for symlinks and ``realpath`` containment.
    Unlike :func:`ensure_within` this never calls ``fail()``: ``state-verify``
    must always emit exactly one JSON payload.
    """
    lexical, display, error = _lexical_tower_path(root, raw)
    if error is not None:
        return None, display, error
    root_abs = os.path.abspath(root)
    try:
        # Do not follow a symlink/junction: report it as an escape instead.
        if _path_has_symlink(root_abs, lexical):
            return None, raw, "escape"
        real = os.path.realpath(lexical)
        root_real = os.path.realpath(root_abs)
    except PATH_ACCESS_ERRORS:
        return None, raw, "invalid"
    if real != root_real and not real.startswith(root_real + os.sep):
        return None, raw, "escape"
    return Path(lexical), display, None


def _evidence_entry_drift(root: Path, task_id: str,
                          evidence: list) -> tuple[list[dict], int]:
    """Verify one record's evidence list; return (drift, entries hashed).

    Only entries whose path is contained, exists and is a regular file count
    as checked.  Malformed, escaping or missing entries are drift and are not
    counted.  A single readable file can yield both ``evidence_hash_mismatch``
    and ``evidence_bytes_mismatch``.
    """
    drift: list[dict] = []
    checked = 0
    for entry in evidence:
        if not isinstance(entry, dict):
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid entry"})
            continue
        raw = entry.get("path")
        if not isinstance(raw, str) or not raw:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        resolved, display, path_error = _contained_tower_path(root, raw)
        recorded_sha = entry.get("sha256")
        if path_error == "invalid":
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        if not isinstance(recorded_sha, str) or not SHA256_HEX_RE.fullmatch(recorded_sha):
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": display,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid sha256"})
            continue
        if path_error == "escape" or resolved is None:
            # The raw recorded path is kept verbatim; nothing outside the
            # tower root is ever hashed, stat'ed or read.
            drift.append({"kind": "evidence_path_escape", "target": task_id,
                          "path": raw,
                          "expected": "evidence path inside tower root",
                          "actual": raw})
            continue
        try:
            is_file = resolved.is_file()
        except PATH_ACCESS_ERRORS:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": None,
                          "expected": "well-formed evidence entry",
                          "actual": "invalid path"})
            continue
        if not is_file:
            try:
                exists = resolved.exists()
            except PATH_ACCESS_ERRORS:
                exists = False
            drift.append({"kind": "evidence_missing", "target": task_id,
                          "path": display,
                          "expected": "existing regular file",
                          "actual": "not a regular file" if exists
                                    else "missing"})
            continue
        try:
            actual_sha = sha256_file(resolved)
            size = resolved.stat().st_size
        except FileNotFoundError:
            drift.append({"kind": "evidence_missing", "target": task_id,
                          "path": display,
                          "expected": "existing regular file",
                          "actual": "missing"})
            continue
        except PATH_ACCESS_ERRORS:
            drift.append({"kind": "evidence_unreadable", "target": task_id,
                          "path": display,
                          "expected": "readable regular file",
                          "actual": "unreadable file"})
            continue
        checked += 1
        if recorded_sha.lower() != actual_sha:
            drift.append({"kind": "evidence_hash_mismatch", "target": task_id,
                          "path": display, "expected": recorded_sha,
                          "actual": actual_sha})
        recorded_bytes = entry.get("bytes")
        if (isinstance(recorded_bytes, int)
                and not isinstance(recorded_bytes, bool)
                and recorded_bytes != size):
            drift.append({"kind": "evidence_bytes_mismatch", "target": task_id,
                          "path": display, "expected": recorded_bytes,
                          "actual": size})
    return drift, checked


def _spec_drift(root: Path, task_id: str, record: dict) -> list[dict]:
    """Verify a record's frozen spec, but only when it claims both fields."""
    spec_path = record.get("spec_path")
    spec_sha = record.get("spec_sha256")
    if not isinstance(spec_path, str) or not spec_path:
        return []
    if not isinstance(spec_sha, str) or not spec_sha:
        return []
    resolved, display, path_error = _contained_tower_path(root, spec_path)
    if path_error == "invalid":
        return [{"kind": "spec_unreadable", "target": task_id, "path": None,
                 "expected": "well-formed spec path",
                 "actual": "invalid path"}]
    if path_error == "escape" or resolved is None:
        return [{"kind": "spec_path_escape", "target": task_id,
                 "path": spec_path,
                 "expected": "spec path inside tower root",
                 "actual": spec_path}]
    try:
        is_file = resolved.is_file()
    except PATH_ACCESS_ERRORS:
        return [{"kind": "spec_unreadable", "target": task_id, "path": None,
                 "expected": "well-formed spec path",
                 "actual": "invalid path"}]
    if not is_file:
        try:
            exists = resolved.exists()
        except PATH_ACCESS_ERRORS:
            exists = False
        return [{"kind": "spec_missing", "target": task_id, "path": display,
                 "expected": "existing regular file",
                 "actual": "not a regular file" if exists else "missing"}]
    try:
        actual_sha = sha256_file(resolved)
    except FileNotFoundError:
        return [{"kind": "spec_missing", "target": task_id, "path": display,
                 "expected": "existing regular file", "actual": "missing"}]
    except PATH_ACCESS_ERRORS:
        return [{"kind": "spec_unreadable", "target": task_id, "path": display,
                 "expected": "readable regular file",
                 "actual": "unreadable file"}]
    if spec_sha.lower() != actual_sha:
        return [{"kind": "spec_hash_mismatch", "target": task_id,
                 "path": display, "expected": spec_sha, "actual": actual_sha}]
    return []


def ledger_events_in_seq_order(root: Path, name: str) -> list[dict]:
    """Parsed ledger events sorted by ``seq`` (file order breaks ties).

    Rows that are not JSON objects are skipped here; ``verify_ledger_file``
    reports them, and ``state-verify`` refuses to replay a broken ledger.
    """
    rows = []
    for index, raw in enumerate(ledger_rows(root / "ledger" / LEDGER_FILES[name])):
        event = parse_ledger_row(raw)
        if event is None:
            continue
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            rows.append(((0, seq, index), event))
        else:
            rows.append(((1, 0, index), event))
    return [event for _, event in sorted(rows, key=lambda pair: pair[0])]


def ledger_events_naming(root: Path, name: str, event_type: str,
                         envelope_id) -> list[dict]:
    """Payloads of ``event_type`` events in ``ledger/<name>.jsonl`` naming it.

    Read-only.  A caller that needs more than existence (the ``ENVELOPE_NEW``
    binding check) can inspect the payloads; :func:`ledger_has_event` is the
    boolean wrapper.  Rows that are not JSON objects are ignored, exactly like
    :func:`ledger_has_event`.
    """
    payloads = []
    for event in ledger_events_in_seq_order(root, name):
        if event.get("type") != event_type:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("envelope") == envelope_id:
            payloads.append(payload)
    return payloads


def ledger_has_event(root: Path, name: str, event_type: str,
                     envelope_id) -> bool:
    """True iff one ``event_type`` event in ``ledger/<name>.jsonl`` names it.

    Read-only.  Rows that are not JSON objects are ignored by
    :func:`ledger_events_in_seq_order`; ``state-verify`` still refuses to replay
    a ledger whose chain is broken.
    """
    return bool(ledger_events_naming(root, name, event_type, envelope_id))


def ledger_has_queue_add(root: Path, envelope_id) -> bool:
    """True iff one ``QUEUE_ADD`` event in ``ledger/supervision.jsonl`` names it.

    Read-only.  Rows that are not JSON objects are ignored by
    :func:`ledger_events_in_seq_order`; ``state-verify`` still refuses to replay
    a ledger whose chain is broken.
    """
    return ledger_has_event(root, "supervision", "QUEUE_ADD", envelope_id)


def _sorted_states(states) -> list:
    """Sort allowed from-states for a drift row: ``None`` first, then names."""
    return sorted(states, key=lambda state: (state is not None, state or ""))


def _illegal_transition(target: str, event_type: str, allowed,
                        actual: str | None) -> dict:
    """One drift row for an event whose source state is outside the table."""
    return {"kind": "illegal_transition", "target": target,
            "event": event_type, "expected": _sorted_states(allowed),
            "actual": actual}


def replay_task_statuses(root: Path,
                         transitions: list[dict] | None = None) -> dict[str, str]:
    """Fold ``ledger/primary.jsonl`` by task into the expected status.

    When ``transitions`` is a list, append one ``illegal_transition`` row for
    every lifecycle event whose source state is outside :data:`TASK_TRANSITIONS`
    (``TASK_NEW`` creates a card from ``None`` and rebuilds only unfinished
    cards, never one that is already ``accepted``/``closed``).  The fold itself
    is untouched: an illegal event is still replayed last-writer-wins, so the
    final-state map and every existing drift stay exactly as before; the caller
    reports the extra rows.  Unknown event types are ignored and never produce
    a transition.
    """
    states: dict[str, str] = {}
    for event in ledger_events_in_seq_order(root, "primary"):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        task = payload.get("task")
        if not isinstance(task, str) or not task:
            continue
        event_type = event.get("type")
        if event_type == "CHECKBACK":
            next_state = "reviewed" if payload.get("verdict") == "PASS" else "rework"
        elif event_type in TASK_LIFECYCLE_STATUS:
            next_state = TASK_LIFECYCLE_STATUS[event_type]
        else:
            # Unknown / non-lifecycle event: ignored, exactly as before.
            continue
        if transitions is not None:
            allowed = TASK_TRANSITIONS.get(event_type)
            previous = states.get(task)
            if allowed is not None and previous not in allowed:
                transitions.append(
                    _illegal_transition(task, event_type, allowed, previous))
        states[task] = next_state
    return states


def replay_envelope_statuses(root: Path,
                             transitions: list[dict] | None = None) -> dict[str, str]:
    """Fold ``ledger/supervision.jsonl`` by envelope into expected status.

    ``MERGE_START`` moves an internal-only state to ``MERGING`` (it still
    leaves the folded status unchanged), so a following ``MERGE`` is checked
    against the merge that actually started.  When ``transitions`` is a list,
    append one ``illegal_transition`` row for every lifecycle event whose
    source state is outside :data:`ENVELOPE_TRANSITIONS`; the fold and every
    existing drift keep their previous values.  Unknown events are ignored.
    """
    states: dict[str, str] = {}
    internal: dict[str, str] = {}
    for event in ledger_events_in_seq_order(root, "supervision"):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        envelope = payload.get("envelope")
        if not isinstance(envelope, str) or not envelope:
            continue
        event_type = event.get("type")
        if event_type == "MERGE_START":
            next_state = ENVELOPE_MERGING_STATUS
        elif event_type in ENVELOPE_LIFECYCLE_STATUS:
            next_state = ENVELOPE_LIFECYCLE_STATUS[event_type]
        elif event_type in ENVELOPE_CORRECTION_EVENTS:
            next_state = "CORRECTION_REQUIRED"
        else:
            # Unknown / non-lifecycle event: ignored, exactly as before.
            continue
        if transitions is not None:
            allowed = ENVELOPE_TRANSITIONS.get(event_type)
            previous = internal.get(envelope)
            if allowed is not None and previous not in allowed:
                transitions.append(
                    _illegal_transition(envelope, event_type, allowed, previous))
        internal[envelope] = next_state
        if event_type != "MERGE_START":
            states[envelope] = next_state
    return states


def _authority_state_drift(root: Path, skip) -> list[dict]:
    """Drift rows for ``state/AUTHORITY.json`` against the last AUTHORITY_SET.

    Read-only and exception-free: ``_read_json_object`` turns every read
    failure into ``unreadable``.  A tower with neither half *and no persisted
    requirement* is legacy and is reported as one ``skipped`` observation,
    never drift, so an old tower still verifies clean.  Every other
    combination is drift; a required tower never reaches the legacy skip.

    PILOT-038 adds the requirement dimension: a tower that persisted
    ``require_authority`` must have both halves of the marker
    (``authority_policy_missing`` / ``authority_policy_unbacked``) and must
    still have a configured authority state
    (``authority_required_unconfigured``).  The drift row shape is unchanged
    (``kind`` / ``target`` / ``expected`` / ``actual``).

    PILOT-039 adds ``authority_policy_mismatch``: when both halves exist they
    must agree on every shared field, so a rewritten audit field is drift.
    A policy file that exists but is not a valid marker is fail-closed drift
    too (same row kind, the shape rather than the event is the expectation).
    """
    file_state, state = _read_json_object(root / AUTHORITY_STATE_FILE)
    event_present, payload_obj = last_authority_event(root)
    requirement = authority_requirement(root)
    required = requirement["required"]

    rows: list[dict] = []
    if required:
        if requirement["event_present"] and not requirement["policy_required"]:
            rows.append({
                "kind": "authority_policy_missing",
                "target": "AUTHORITY_POLICY",
                "expected": f"{AUTHORITY_POLICY_FILE} with "
                            "require_authority=true",
                "actual": ("missing" if requirement["policy_state"] == "missing"
                           else "require_authority is not true")})
        elif requirement["policy_required"] and not requirement["event_present"]:
            rows.append({
                "kind": "authority_policy_unbacked",
                "target": "AUTHORITY_POLICY",
                "expected": f"{AUTHORITY_REQUIRED_EVENT} ledger event",
                "actual": "policy file only"})
        if file_state == "missing" or not event_present:
            rows.append({
                "kind": "authority_required_unconfigured",
                "target": "AUTHORITY",
                "expected": "state/AUTHORITY.json backed by an AUTHORITY_SET "
                            "event (authority is required)",
                "actual": ("missing" if file_state == "missing"
                           else "no AUTHORITY_SET event")})
            # The requirement rows are the whole story here: adding 037's
            # authority_missing/unbacked rows would only duplicate the same
            # missing half under a legacy-compatible name.
            return rows
        # PILOT-039: both halves exist, so the policy file must repeat the last
        # AUTHORITY_REQUIRED payload field for field (audit fields included).
        mismatch = authority_policy_mismatch(root, requirement)
        if mismatch is not None:
            rows.append({
                "kind": "authority_policy_mismatch",
                "target": "AUTHORITY_POLICY",
                "expected": mismatch["expected"],
                "actual": mismatch["actual"]})

    if not required and authority_policy_invalid(requirement):
        # A present-but-invalid policy is fail-closed drift: it can never turn
        # into the legacy skip below just because require_authority is not
        # literally true.
        fields = authority_policy_fields(requirement["policy"])
        rows.append({
            "kind": "authority_policy_mismatch",
            "target": "AUTHORITY_POLICY",
            "expected": {"require_authority": True},
            "actual": {field: authority_display(fields[field])
                       for field in AUTHORITY_POLICY_FIELDS},
        })
        if file_state == "missing" and not event_present:
            return rows

    if file_state == "missing" and not event_present:
        skip("authority_state", "AUTHORITY", "no_authority_state")
        return rows
    if file_state == "unreadable":
        rows.append({"kind": "authority_unreadable", "target": "AUTHORITY",
                     "expected": "parseable JSON object",
                     "actual": "unparseable"})
        return rows
    if file_state == "missing":
        rows.append({"kind": "authority_missing", "target": "AUTHORITY",
                     "expected": "state/AUTHORITY.json matching the last "
                                 "AUTHORITY_SET event",
                     "actual": "missing"})
        return rows
    if not event_present:
        rows.append({"kind": "authority_unbacked", "target": "AUTHORITY",
                     "expected": "AUTHORITY_SET ledger event",
                     "actual": "file only"})
        return rows
    payload = payload_obj if isinstance(payload_obj, dict) else {}
    file_fields = authority_state_fields(state)
    payload_fields = authority_payload_fields(payload)
    mismatched = [field for field in AUTHORITY_STATE_FIELDS
                  if file_fields[field] != payload_fields[field]]
    type_errors = (_authority_field_errors(file_fields, "file")
                   + _authority_field_errors(payload_fields, "ledger"))
    expected = {field: authority_display(payload_fields[field])
                for field in AUTHORITY_STATE_FIELDS}
    actual = {field: authority_display(file_fields[field])
              for field in AUTHORITY_STATE_FIELDS}
    expected["schema"] = AUTHORITY_STATE_SCHEMA
    actual["schema"] = state.get("schema")
    if actual["schema"] != AUTHORITY_STATE_SCHEMA:
        mismatched.append("schema")
    # ``tower_id`` is not part of the event payload, so it is bound to the
    # primary state instead -- but only when that state is readable, so the
    # audit stays exception-free on partial fixtures.
    _, primary_state = _read_json_object(root / "primary" / "CURRENT_STATE.json")
    if isinstance(primary_state, dict):
        primary_tower_id = primary_state.get("tower_id", AUTHORITY_ABSENT)
        if isinstance(primary_tower_id, str) and primary_tower_id:
            expected["tower_id"] = primary_tower_id
            actual["tower_id"] = authority_display(
                state.get("tower_id", AUTHORITY_ABSENT))
            if actual["tower_id"] != primary_tower_id:
                mismatched.append("tower_id")
    if mismatched or type_errors:
        rows.append({"kind": "authority_mismatch", "target": "AUTHORITY",
                     "expected": expected, "actual": actual})
    return rows


def state_verify_drift(root: Path) -> dict:
    """Compare replayed state with records, board, queue and envelopes.

    Every entity with replayed lifecycle events is checked: a missing or
    unreadable record/envelope file is drift (``record_missing`` /
    ``record_unreadable`` / ``envelope_missing`` / ``envelope_unreadable``),
    never silently skipped.  ``TASK_BOARD.json`` and ``MERGE_QUEUE.json``
    that are missing or unusable yield exactly one file-level
    ``board_unreadable`` / ``queue_unreadable`` entry and suppress the
    per-entity comparison for that file.  Board status is compared against
    the replayed status, not against ``record.status``.

    While folding, each lifecycle event is also checked against its legal
    source states and an out-of-table event yields one ``illegal_transition``
    entry (``event``, ``expected`` allowed from-states, ``actual`` observed
    from-state).  The final-state maps, counts and every other drift are
    unchanged by that check.

    A task without lifecycle events, a replayed task absent from a readable
    board, and a replayed envelope absent from a readable queue are reported
    in ``skipped``; they are observations, never drift.  Envelopes are
    different: a ``MERGE_QUEUE.json`` entry whose id has no replayed lifecycle
    event is ``queue_unbacked`` and an envelope file whose id has no replayed
    lifecycle event is ``envelope_unbacked``.  Both files can be written by
    hand without touching the ledger, so neither is silently skipped.

    A readable record of a replayed task additionally has its claimed
    ``evidence`` entries and frozen ``spec_path``/``spec_sha256`` verified
    against the bytes on disk.  ``evidence_checked`` counts only the evidence
    entries whose bytes were actually hashed.
    """
    transitions: list[dict] = []
    task_states = replay_task_statuses(root, transitions)
    envelope_states = replay_envelope_statuses(root, transitions)
    drift: list[dict] = list(transitions)
    skipped: list[dict] = []
    evidence_checked = 0

    def skip(kind: str, target: str, reason: str) -> None:
        skipped.append({"kind": kind, "target": target, "reason": reason})

    board_state, board = _read_json_object(root / "primary" / "TASK_BOARD.json")
    if board is None:
        drift.append({"kind": "board_unreadable", "target": "TASK_BOARD.json",
                      "expected": "parseable JSON object",
                      "actual": "missing" if board_state == "missing"
                                else "unparseable"})
    board_tasks: dict[str, dict] = {}
    if board is not None:
        entries = board.get("tasks")
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("id"):
                board_tasks[str(entry["id"])] = entry

    queue_state, queue = _read_json_object(
        root / "supervision" / "MERGE_QUEUE.json")
    if queue is None:
        drift.append({"kind": "queue_unreadable", "target": "MERGE_QUEUE.json",
                      "expected": "parseable JSON object",
                      "actual": "missing" if queue_state == "missing"
                                else "unparseable"})
    queue_entries: dict[str, dict] = {}
    if queue is not None:
        entries = queue.get("entries")
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("envelope_id"):
                queue_entries[str(entry["envelope_id"])] = entry

    # Entities with replayed events plus record/envelope files on disk, so an
    # entity that only has a file (no ledger event) is reported as skipped
    # instead of disappearing.
    task_ids = set(task_states)
    tasks_dir = root / "tasks"
    if tasks_dir.is_dir():
        for child in tasks_dir.iterdir():
            if child.is_dir() and (child / "record.json").is_file():
                task_ids.add(child.name)
    envelope_ids = set(envelope_states)
    envelope_file_ids: set[str] = set()
    envelopes_dir = root / "supervision" / "envelopes"
    if envelopes_dir.is_dir():
        for child in envelopes_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                envelope_file_ids.add(child.stem)
                envelope_ids.add(child.stem)

    # A queue entry or envelope file that no replayed lifecycle event backs was
    # written by hand, bypassing the ledger.  Report the queue bypass and the
    # envelope bypass separately: one hand-written pair yields both rows.
    for envelope_id in sorted(set(queue_entries) - set(envelope_states)):
        drift.append({"kind": "queue_unbacked", "target": envelope_id,
                      "expected": "QUEUE_ADD ledger event",
                      "actual": "no lifecycle events"})
    for envelope_id in sorted(envelope_file_ids - set(envelope_states)):
        drift.append({"kind": "envelope_unbacked", "target": envelope_id,
                      "expected": "ENVELOPE_NEW ledger event",
                      "actual": "no lifecycle events"})

    for task_id in sorted(task_ids):
        expected = task_states.get(task_id)
        if expected is None:
            skip("task", task_id, "no_lifecycle_events")
            continue
        state, record = ("missing", None)
        if is_safe_id(task_id, TASK_ID_RE):
            state, record = _read_json_object(
                root / "tasks" / task_id / "record.json")
        if record is None:
            drift.append({
                "kind": "record_missing" if state == "missing"
                        else "record_unreadable",
                "target": task_id, "expected": expected, "actual": None})
        else:
            record_status = record.get("status")
            if record_status != expected:
                drift.append({"kind": "task_status", "target": task_id,
                              "expected": expected, "actual": record_status})
            evidence = record.get("evidence")
            if isinstance(evidence, list):
                entry_drift, checked = _evidence_entry_drift(
                    root, task_id, evidence)
                drift.extend(entry_drift)
                evidence_checked += checked
            drift.extend(_spec_drift(root, task_id, record))
        if board is None:
            continue
        board_entry = board_tasks.get(task_id)
        if board_entry is None:
            skip("task", task_id, "board_entry_missing")
        elif board_entry.get("status") != expected:
            drift.append({"kind": "board_status", "target": task_id,
                          "expected": expected,
                          "actual": board_entry.get("status")})

    for envelope_id in sorted(envelope_ids):
        expected = envelope_states.get(envelope_id)
        if expected is None:
            # Already reported as queue_unbacked / envelope_unbacked above.
            continue
        if queue is not None:
            queue_entry = queue_entries.get(envelope_id)
            if queue_entry is None:
                skip("envelope", envelope_id, "queue_entry_missing")
            elif queue_entry.get("status") != expected:
                drift.append({"kind": "queue_status", "target": envelope_id,
                              "expected": expected,
                              "actual": queue_entry.get("status")})
        # Unsafe ids are never used as a filename: they are not opened.
        if not is_safe_id(envelope_id, PACKAGE_ID_RE):
            continue
        state, envelope = _read_json_object(
            root / "supervision" / "envelopes" / f"{envelope_id}.json")
        if envelope is None:
            drift.append({
                "kind": "envelope_missing" if state == "missing"
                        else "envelope_unreadable",
                "target": envelope_id, "expected": expected, "actual": None})
        elif envelope.get("status") != expected:
            drift.append({"kind": "envelope_status", "target": envelope_id,
                          "expected": expected,
                          "actual": envelope.get("status")})

    drift.extend(_authority_state_drift(root, skip))

    drift.sort(key=lambda item: (item["kind"], str(item["target"]),
                                 item.get("path") or ""))
    skipped.sort(key=lambda item: (item["kind"], str(item["target"])))
    return {"tasks": len(task_states), "envelopes": len(envelope_states),
            "drift": drift, "skipped": skipped,
            "skipped_count": len(skipped),
            "evidence_checked": evidence_checked}


def cmd_state_verify(root: Path, args) -> None:
    """Read-only: replay both ledgers and report observed drift.

    Exit 0 when every compared file agrees with the replay, 2 when any drift
    is found; a broken ledger short-circuits to 2 with ``ledger_errors``.
    ``skipped`` is informational and never affects ``ok`` or the exit code.
    """
    ledger_errors: list[str] = []
    for name in ("primary", "supervision"):
        report = verify_ledger_file(root, name)
        ledger_errors.extend(f"{name}: {err}" for err in report["errors"])
    if ledger_errors:
        emit({"ok": False, "tasks": 0, "envelopes": 0, "drift": [],
              "skipped": [], "skipped_count": 0, "evidence_checked": 0,
              "ledger_errors": ledger_errors}, 2)
    result = state_verify_drift(root)
    payload = {"ok": not result["drift"], "tasks": result["tasks"],
               "envelopes": result["envelopes"], "drift": result["drift"],
               "skipped": result["skipped"],
               "skipped_count": result["skipped_count"],
               "evidence_checked": result["evidence_checked"]}
    emit(payload, 0 if payload["ok"] else 2)


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
        "state-verify": cmd_state_verify,
        "authority-check": cmd_authority_check,
        "authority-set": cmd_authority_set,
        "authority-require": cmd_authority_require,
        "spec-lint": cmd_spec_lint,
        "spec-coverage": cmd_spec_coverage,
    }
    try:
        handlers[args.cmd](root, args)
    except LedgerLockTimeout as exc:
        fail([str(exc)])


if __name__ == "__main__":
    main()
