"""Shared primitives: JSON/IO, path safety, git/gh helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]


TASK_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,40}$")


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


def _norm_tower_rel(root: Path, raw) -> tuple[str | None, str | None]:
    """Normalise one tower-root-relative path; return ``(posix, error)``.

    Lexical only: the file does not have to exist yet -- a completion is
    recorded before the work lands and may name a brand-new file.  Absolute
    paths and any ``..`` are rejected before a filesystem call, and the
    normalised path is checked to stay inside ``root``.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, "path must be a non-empty string"
    text = raw.strip().replace("\\", "/")
    if "\x00" in text:
        return None, "path must not contain NUL"
    if os.path.isabs(text) or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None, f"path must be tower-root-relative, not absolute: {raw}"
    if ".." in text:
        return None, f"path must not contain '..': {raw}"
    root_abs = os.path.abspath(root)
    try:
        lexical = os.path.normpath(os.path.join(root_abs, text))
    except (OSError, ValueError, RuntimeError):
        return None, f"path cannot be normalised: {raw}"
    if lexical != root_abs and not lexical.startswith(root_abs + os.sep):
        return None, f"path outside tower root: {raw}"
    display = os.path.relpath(lexical, root_abs).replace(os.sep, "/")
    if display in ("", "."):
        return None, "path must name something inside the tower root"
    return display, None


def allowed_repo_path(allowed: str, worktree_rel: str, tower_rel: str) -> str | None:
    """Map one tower-relative ``allowed_paths`` entry to a worktree-relative path.

    The diff collected by :func:`deliver_scope` is relative to the *worktree*
    repository root (a ``git worktree`` checkout whose root is that repository
    root).  ``allowed_paths`` entries, on the other hand, are relative to the
    tower root.  Two shapes exist:

    * ``pilot/worktrees/<ID>/tower-dsh/tools/x.py`` — inside the task worktree.
      The worktree root *is* the repository root, so dropping the
      ``<worktree_rel>/`` prefix already yields the worktree-relative path.
      ``<tower_rel>`` must not be prepended again (the v1 mapping bug fixed in
      PILOT-041 v2: it produced ``tower-dsh/tower-dsh/tools/x.py``).
    * ``pilot/<ID>.spec.json`` — elsewhere in the tower.  Its worktree-relative
      path is ``<tower_rel>/pilot/<ID>.spec.json``; ``<tower_rel>`` is empty
      when the tower root is the repository root.
    """
    worktree_rel = str(worktree_rel or "").replace("\\", "/").strip().strip("/")
    tower_rel = str(tower_rel or "").replace("\\", "/").strip().strip("/")
    text = str(allowed or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    if not text:
        return None
    if worktree_rel:
        prefix = worktree_rel + "/"
        if text == worktree_rel:
            return None
        if text.startswith(prefix):
            return text[len(prefix):] or None
    return f"{tower_rel}/{text}" if tower_rel else text


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


COMMAND_ARCHIVE_SUFFIX = "-VOID"


TASK_BOARD_REL = "primary/TASK_BOARD.json"


def emit_sorted(data: dict, code: int = 0) -> None:
    """Emit canonical JSON (sorted keys) and exit; stdout carries nothing else."""
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(code)
