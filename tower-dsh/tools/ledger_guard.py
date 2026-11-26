#!/usr/bin/env python3
"""PILOT-079: ``ledger/*.jsonl`` must stay a byte-prefix of the base commit.

``verify-ledger`` rebuilds the hash chain from the *current* files, so a
rewritten history that is re-hashed consistently looks perfectly valid: the
attacker edits row 1, recomputes every ``hash``/``prev_hash`` and the chain
verifier is happy.  The only witness that cannot be recomputed locally is git
history, which is what this guard compares against.

Contract
--------
Every ``ledger/*.jsonl`` file in the working tree must be a **byte-prefix
extension** of the blob at the same path in ``--base`` (default
``origin/main``)::

    current_bytes.startswith(base_bytes)

Consequences, all fail closed with exit 2:

* a historical byte was rewritten (even when the hash chain was re-derived);
* the file was truncated (including cut in the middle of a row);
* a ledger file present in the base was deleted;
* a ledger file exists locally that the base never had (a new ledger file is
  not an append, so the guard refuses it);
* the base ref/commit or one of its blobs cannot be read.

Exit 0 means every current ledger file is a pure append of its base file and no
ledger file was added.  ``state-verify``/``verify-ledger`` still run separately;
this guard neither parses nor re-implements the ledger chain.

Offline by construction: the base blobs come from the local git object
database (``git show <commit>:<path>``); no remote is contacted, ``gh`` is
never invoked and nothing is fetched.

Usage::

    python tools/ledger_guard.py --base origin/main
    python tools/ledger_guard.py --base origin/main --root <tower root>
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import subprocess
import sys
from pathlib import Path

# ``tools/ledger_guard.py`` -> the tower root is the directory holding ``tools/``.
TOWER_ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = "ledger"
LEDGER_SUFFIX = ".jsonl"
DEFAULT_BASE = "origin/main"
GIT_TIMEOUT = 120.0


class GuardError(RuntimeError):
    """A hard failure: the guard cannot prove the ledger is append-only."""


def _force_utf8_stdio() -> None:
    """Keep JSON output valid UTF-8 even on a non-UTF-8 console (cp1252/cp936)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def emit(data: dict, code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    """Run git against ``repo``; text mode for plumbing, bytes for blobs."""
    command = ["git", "-C", str(repo), *args]
    try:
        if text:
            return subprocess.run(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", timeout=GIT_TIMEOUT,
            )
        return subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardError(f"cannot run git: {exc}") from exc


def _stderr(cp: subprocess.CompletedProcess) -> str:
    raw = cp.stderr if isinstance(cp.stderr, str) else os.fsdecode(cp.stderr or b"")
    return (raw or "").strip()


def _require(cp: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if cp.returncode != 0:
        detail = _stderr(cp) or f"git exited {cp.returncode}"
        raise GuardError(f"{what}: {detail}")
    return cp


def _git_text(repo: Path, *args: str) -> str:
    return _require(_git(repo, *args), f"git {' '.join(args)}").stdout.strip()


def repository_root(tower_root: Path) -> Path:
    """The git worktree root that contains ``tower_root`` (fail closed)."""
    top = _git_text(tower_root, "rev-parse", "--show-toplevel")
    if not top:
        raise GuardError(f"not inside a git work tree: {tower_root}")
    return Path(top)


def repo_prefix(tower_root: Path) -> str:
    """``tower_root`` relative to the repository root, with a trailing slash."""
    prefix = _git_text(tower_root, "rev-parse", "--show-prefix")
    prefix = prefix.replace("\\", "/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def resolve_base(tower_root: Path, base: str) -> str:
    """Resolve ``base`` to a commit id, using local objects only."""
    cp = _git(tower_root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    commit = cp.stdout.strip() if cp.returncode == 0 else ""
    if not commit:
        raise GuardError(
            f"base ref cannot be resolved to a commit: {base!r} "
            "(fetch it first; the guard never contacts a remote)")
    return commit


def base_ledger_paths(repo_root: Path, base_commit: str,
                      ledger_rel: str) -> list[str]:
    """Base blobs under ``<prefix>ledger`` that are direct ``*.jsonl`` children."""
    cp = _require(
        _git(repo_root, "ls-tree", "-r", "-z", "--name-only", base_commit,
             "--", ledger_rel, text=False),
        f"git ls-tree {base_commit} -- {ledger_rel}")
    paths = []
    for raw in cp.stdout.split(b"\0"):
        if not raw:
            continue
        relpath = os.fsdecode(raw).replace("\\", "/")
        if posixpath.dirname(relpath) != ledger_rel:
            continue
        if not relpath.endswith(LEDGER_SUFFIX):
            continue
        paths.append(relpath)
    return sorted(paths)


def base_blob(repo_root: Path, base_commit: str, relpath: str) -> bytes:
    """Exact bytes of ``relpath`` at ``base_commit`` (``git show``, no filters)."""
    cp = _require(
        _git(repo_root, "show", f"{base_commit}:{relpath}", text=False),
        f"git show {base_commit}:{relpath} (base blob missing)")
    return cp.stdout


def current_ledger_paths(tower_root: Path) -> list[Path]:
    """Current ``ledger/*.jsonl`` files, sorted by name."""
    ledger_dir = tower_root / LEDGER_DIR
    if not ledger_dir.is_dir():
        return []
    return sorted(path for path in ledger_dir.glob(f"*{LEDGER_SUFFIX}")
                  if path.is_file())


def first_difference(base: bytes, current: bytes) -> int:
    """Offset of the first differing byte, or ``min(len(...))`` for a prefix."""
    limit = min(len(base), len(current))
    for index in range(limit):
        if base[index] != current[index]:
            return index
    return limit


def compare_ledger_file(relpath: str, base: bytes, current: bytes) -> dict:
    """One ledger file: byte-prefix check, with truncation called out."""
    check = {
        "path": relpath,
        "ok": current.startswith(base),
        "base_bytes": len(base),
        "current_bytes": len(current),
    }
    if check["ok"]:
        check["detail"] = (f"pure append (+{len(current) - len(base)} bytes)"
                           if len(current) > len(base) else "unchanged")
        return check
    offset = first_difference(base, current)
    if current and base.startswith(current):
        reason = "truncated"
    elif len(current) < len(base):
        reason = "rewritten or truncated"
    else:
        reason = "rewritten"
    check["detail"] = (
        f"{reason}: current file is not a byte-prefix extension of the base "
        f"blob (base={len(base)} bytes, current={len(current)} bytes, "
        f"first difference at byte {offset})")
    return check


def ledger_guard(root: Path, base: str) -> dict:
    """The full read-only verdict: base commit, per-file checks, errors."""
    tower_root = Path(root).resolve()
    repo_root = repository_root(tower_root)
    prefix = repo_prefix(tower_root)
    ledger_rel = f"{prefix}{LEDGER_DIR}"
    base_commit = resolve_base(tower_root, base)

    checks: list[dict] = []
    errors: list[dict] = []
    base_paths = base_ledger_paths(repo_root, base_commit, ledger_rel)
    current_paths = current_ledger_paths(tower_root)
    current_names = {path.name for path in current_paths}

    for relpath in base_paths:
        name = posixpath.basename(relpath)
        base_bytes = base_blob(repo_root, base_commit, relpath)
        if name not in current_names:
            errors.append({
                "path": relpath,
                "kind": "deleted",
                "detail": (f"ledger file deleted: {relpath} exists at base "
                           f"{base_commit[:12]} but not in the working tree"),
            })
            continue
        current_bytes = (tower_root / LEDGER_DIR / name).read_bytes()
        check = compare_ledger_file(relpath, base_bytes, current_bytes)
        checks.append(check)
        if not check["ok"]:
            errors.append({"path": relpath, "kind": "history",
                           "detail": check["detail"]})

    for path in current_paths:
        relpath = f"{ledger_rel}/{path.name}"
        if relpath in base_paths:
            continue
        errors.append({
            "path": relpath,
            "kind": "new",
            "detail": (f"new ledger file refused: {relpath} does not exist at "
                       f"base {base_commit[:12]}; ledger files are append-only"),
        })

    return {
        "ok": not errors,
        "base": base,
        "base_commit": base_commit,
        "ledger": ledger_rel,
        "checks": checks,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Fail closed unless every ledger/*.jsonl is a byte-prefix "
                     "extension of the same file at --base (append-only)."))
    parser.add_argument(
        "--base", default=DEFAULT_BASE,
        help=f"git ref the current ledger must extend (default: {DEFAULT_BASE})")
    parser.add_argument(
        "--root", default=str(TOWER_ROOT),
        help=("tower root holding ledger/ (default: the repository containing "
              "this script)"))
    return parser


def main(argv: list[str] | None = None) -> None:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        payload = ledger_guard(Path(args.root), args.base)
    except GuardError as exc:
        emit({"ok": False, "base": args.base, "errors": [
            {"path": str(args.root), "kind": "guard", "detail": str(exc)}]}, 2)
    emit(payload, 0 if payload["ok"] else 2)


if __name__ == "__main__":
    main()
