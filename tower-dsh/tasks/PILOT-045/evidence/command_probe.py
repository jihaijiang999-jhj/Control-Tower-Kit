"""PILOT-045 probe: ``campaign-check`` / ``brief`` are read-only and wired.

Run from anywhere; paths are derived from this file::

    python -B scratch/command_probe.py        # writes scratch/probe.txt
    python -B scratch/command_probe.py old    # writes scratch/probe-old-code.txt

The ``old`` mode executes ``scratch/old/towerctl.py`` (byte copy of
``git show main:tower-dsh/tools/towerctl.py``) and records that the base tool
does not know the two new subcommands.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOWER = HERE.parent / "tower-dsh"
NEW = TOWER / "tools" / "towerctl.py"
OLD = HERE / "old" / "towerctl.py"


def snapshot() -> dict[str, str]:
    """SHA-256 of every record, the board, the state and both ledgers."""
    paths = sorted(TOWER.glob("tasks/*/record.json"))
    paths += [TOWER / "primary" / "TASK_BOARD.json",
              TOWER / "primary" / "CURRENT_STATE.json"]
    paths += sorted((TOWER / "ledger").glob("*.jsonl"))
    return {path.relative_to(TOWER).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def run(args: list[str], script: Path = NEW) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(TOWER / "tools")}
    return subprocess.run([sys.executable, "-B", str(script), *args], cwd=str(TOWER),
                          capture_output=True, text=True, encoding="utf-8", env=env)


def probe_new() -> tuple[list[str], bool]:
    before = snapshot()
    check = run(["campaign-check"])
    strict = run(["campaign-check", "--strict"])
    brief = run(["brief"])
    after = snapshot()
    lines = ["== new code: worktree tower =="]
    lines.append(f"campaign-check exit={check.returncode}")
    payload: dict = {}
    if check.stdout.strip():
        payload = json.loads(check.stdout)
        lines.append(f"  ok={payload['ok']} strategy={payload['strategy']} "
                     f"campaigns={payload['campaigns']} wip={payload['wip']}")
        lines.append(f"  errors={len(payload['errors'])} "
                     f"warnings={len(payload['warnings'])} "
                     f"warning_codes={sorted({w['code'] for w in payload['warnings']})}")
        for finding in payload["errors"][:5]:
            lines.append(f"  error {finding['code']} {finding['target']}: {finding['detail']}")
    lines.append(f"campaign-check --strict exit={strict.returncode} "
                 f"(W1 board backfill is still open, so strict is expected to fail)")
    brief_lines = brief.stdout.splitlines()
    lines.append(f"brief exit={brief.returncode} line_count={len(brief_lines)} "
                 f"(cap 60)")
    lines.append("  headers=" + ", ".join(line for line in brief_lines
                                          if line.startswith("## ")))
    lines.append(f"read-only: merged_files_hashed={len(before)} "
                 f"unchanged_after_both_commands={before == after}")
    ok = (check.returncode == 0 and brief.returncode == 0
          and before == after and len(brief_lines) <= 60 and not payload.get("errors"))
    lines.append(f"VERDICT: {'PASS' if ok else 'FAIL'}")
    return lines, ok


def probe_old() -> tuple[list[str], bool]:
    lines = ["== old code: git show main:tower-dsh/tools/towerctl.py ==",
             f"old tool bytes={OLD.stat().st_size} lines={len(OLD.read_text(encoding='utf-8').splitlines())}"]
    ok = True
    for command in ("campaign-check", "brief"):
        cp = run(["--root", str(TOWER), command], script=OLD)
        tail = (cp.stderr or cp.stdout).strip().splitlines()
        lines.append(f"{command}: exit={cp.returncode} stderr_last={tail[-1] if tail else ''}")
        ok = ok and cp.returncode == 2 and "invalid choice" in (cp.stderr or "")
    lines.append(f"VERDICT: {'PASS' if ok else 'FAIL'} "
                 "(base tool rejects both subcommands as invalid choices)")
    return lines, ok


def main() -> int:
    old_mode = len(sys.argv) > 1 and sys.argv[1] == "old"
    lines, ok = probe_old() if old_mode else probe_new()
    text = "\n".join(lines) + "\n"
    (HERE / ("probe-old-code.txt" if old_mode else "probe.txt")).write_text(
        text, encoding="utf-8")
    print(text, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
