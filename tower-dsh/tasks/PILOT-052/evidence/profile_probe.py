#!/usr/bin/env python3
"""Evidence for PILOT-052: run each PROFILE fact's probe directly, then the gate.

Run from the tower root::

    python scratch/profile_probe.py
"""
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
PROFILE = TOWER / "state" / "PROFILE-TOWER-DSH.md"


def rows():
    lines = [line.strip() for line in PROFILE.read_text(encoding="utf-8").splitlines()
             if line.strip().startswith("|")]
    return [line.strip("|").split("|") for line in lines[2:]]


def run(argv):
    completed = subprocess.run(argv, cwd=str(TOWER), capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    return completed.returncode, completed.stdout, completed.stderr


def main():
    print(f"tower={TOWER}")
    print(f"profile={PROFILE.relative_to(TOWER).as_posix()}")
    print("id            probe                    exit  expect")
    failures = 0
    for cells in rows():
        ident, probe, expect = (cells[index].strip() for index in (0, 2, 3))
        code, _out, err = run([sys.executable, "-B", "tools/towerctl.py", *probe.split()])
        ok = code == 0 and not err
        failures += 0 if ok else 1
        print(f"{ident:<13} {probe:<24} {code}     {expect}  {'OK' if ok else 'FAIL'}")
    gate_code, gate_out, gate_err = run(
        [sys.executable, "-B", "tools/towerctl.py", "profile-check"])
    payload = json.loads(gate_out) if gate_out.strip() else {}
    print(f"profile-check exit={gate_code} ok={payload.get('ok')} "
          f"object={payload.get('object')} checked={payload.get('checked')} "
          f"findings={payload.get('findings')}")
    if gate_err:
        print(f"profile-check stderr={gate_err}", file=sys.stderr)
    return 0 if failures == 0 and gate_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
