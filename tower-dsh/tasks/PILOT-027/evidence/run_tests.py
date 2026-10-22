#!/usr/bin/env python3
"""Run the tower suite with ``TMP``/``TEMP``/``TMPDIR`` in a repo-local sandbox.

Restricted DSH sandboxes break ``tempfile.mkdtemp`` because the inherited
``%TEMP%`` directory carries ACLs the child cannot write through.  This runner
creates one fresh directory per run under ``<tower>/.test-tmp`` and points all
three temporary-directory variables at it, so tests and the code they exercise
never touch the host temp directory.

    python tools/run_tests.py
    python tools/run_tests.py --suite tools/tests --pattern "test*.py"
    python tools/run_tests.py --suite <dir> --pattern test_smoke.py --tmp-root <dir>

The run directory is printed as ``TOWER_TEST_TMP=<dir>`` *before* the child
starts, so a failing run can point straight at its own sandbox.  Run
directories are never deleted (keeping them makes a red run debuggable); they
are gitignored via ``tower-dsh/.test-tmp/``.

The process exit code is the child's exit code.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ``tools/run_tests.py`` -> the tower root is the directory holding ``tools/``.
TOWER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = "tools/tests"
DEFAULT_PATTERN = "test*.py"
DEFAULT_TMP_ROOT = TOWER_ROOT / ".test-tmp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Run the tower unittest suite with a repo-local "
                     "TMP/TEMP/TMPDIR sandbox"))
    parser.add_argument(
        "--suite", default=DEFAULT_SUITE,
        help=f"test directory passed to unittest discover (default: {DEFAULT_SUITE})")
    parser.add_argument(
        "--pattern", default=DEFAULT_PATTERN,
        help=f"unittest discovery pattern (default: {DEFAULT_PATTERN})")
    parser.add_argument(
        "--tmp-root", default=str(DEFAULT_TMP_ROOT),
        help=("directory that holds each run sandbox "
              f"(default: {DEFAULT_TMP_ROOT})"))
    return parser


def new_run_dir(tmp_root: Path) -> Path:
    """Create and return ``<tmp-root>/run-YYYYmmdd-HHMMSS-<pid>``.

    Existing directories are reused rather than failed on: a same-pid,
    same-second rerun can only collide when the caller reuses a very stale
    sandbox root, and reusing it is harmless.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(tmp_root) / f"run-{stamp}-{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def child_env(run_dir: Path) -> dict[str, str]:
    """``os.environ`` with all three temp-dir variables pointed at ``run_dir``.

    The sandbox sits inside the verified repository, while several fixtures
    assume temporary directories are outside any git repository.  So the run
    directory is also quarantined (see :func:`quarantine_run_dir`) and git's
    ``core.longpaths`` is injected through ``GIT_CONFIG_*`` on Windows, because
    throw-away fixture repositories under a deep worktree exceed ``MAX_PATH``.
    Descendant git processes inherit both without touching global git config.
    """
    env = dict(os.environ)
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = str(run_dir)
    if os.name == "nt":
        _append_git_config(env, "core.longpaths", "true")
    return env


def _append_git_config(env: dict[str, str], key: str, value: str) -> None:
    """Add one ``GIT_CONFIG_*`` entry without clobbering existing ones."""
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    except ValueError:
        count = 0
    env[f"GIT_CONFIG_KEY_{count}"] = key
    env[f"GIT_CONFIG_VALUE_{count}"] = value
    env["GIT_CONFIG_COUNT"] = str(count + 1)


SANDBOX_GITFILE = "gitdir: ./.test-tmp-is-not-a-repository\n"


def quarantine_run_dir(run_dir: Path) -> None:
    """Stop git discovery from climbing out of the sandbox into the tower repo.

    The sandbox lives inside the verified repository (``<tower>/.test-tmp``),
    but the suite's fixtures assume a temporary directory is outside any git
    repository: a few assert ``authority_dirty is None`` or expect git paths
    to resolve to empty strings.  A gitfile in the run directory that points at
    a missing git dir produces exactly the old ``not a git repository`` result
    (exit 128) without changing any fixture.  Fixtures that run ``git init``
    below the run directory are unaffected: the nearest ``.git`` wins.
    """
    gitfile = run_dir / ".git"
    if not gitfile.exists():
        gitfile.write_text(SANDBOX_GITFILE, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tmp_root = Path(args.tmp_root)
    if not tmp_root.is_absolute():
        tmp_root = TOWER_ROOT / tmp_root
    run_dir = new_run_dir(tmp_root)
    quarantine_run_dir(run_dir)
    # Printed first and explicitly flushed: the child writes to the inherited
    # stdout/stderr, so this line must not be buffered behind its output.
    print(f"TOWER_TEST_TMP={run_dir}", flush=True)
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover",
         "-s", args.suite, "-p", args.pattern, "-v"],
        cwd=str(TOWER_ROOT),
        env=child_env(run_dir),
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
