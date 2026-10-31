"""PILOT-055 CI probe: read the workflow text and report the gate contract.

Read-only.  Parses repo-root ``.github/workflows/tower-gate.yml`` the same way
``tools/tests/test_ci_gate.py`` does (per-step blocks starting at ``- name:``),
prints the run commands in order, and re-checks the 8-step contract:

  * exactly 8 steps carry a ``run:`` command (7 gates + status),
  * ``shape-check`` is after ``campaign-check`` and before ``status``,
  * ``status`` is unique and the last step,
  * ``continue-on-error`` does not appear anywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tower-gate.yml"
STEP_RE = re.compile(r"(?m)^\s*-\s+name:")
RUN_RE = re.compile(r"(?m)^\s+run:\s*(\S.*)$")

text = WORKFLOW.read_text(encoding="utf-8")
starts = [m.start() for m in STEP_RE.finditer(text)]
blocks = [text[s:starts[i + 1] if i + 1 < len(starts) else len(text)]
          for i, s in enumerate(starts)]

steps = []
for block in blocks:
    name = re.search(r"(?m)^\s*-\s+name:\s*(.+?)\s*$", block).group(1)
    run = RUN_RE.search(block)
    steps.append((name, run.group(1).strip() if run else None))

runs = [run for _, run in steps if run]
shape = "python tools/towerctl.py shape-check"
campaign = "python tools/towerctl.py campaign-check"
status = "python tools/towerctl.py status"

print(f"workflow: {WORKFLOW}")
print(f"steps (name -> run):")
for index, (name, run) in enumerate(steps, 1):
    print(f"  {index:2d}. {name:<26} {run or '(uses:)'}")
print()
print(f"gate steps with run: {len(runs)} (expected 8)")
print(f"status blocks: {sum(1 for _, run in steps if run == status)} (expected 1)")
print(f"continue-on-error count: {text.count('continue-on-error')} (expected 0)")
print(f"shape-check occurrences: {text.count(shape)} (expected 1)")
print(f"shape after campaign: {text.index(campaign) < text.index(shape)}")
print(f"shape before status:  {text.index(shape) < text.index(status)}")
print(f"status is last step:  {steps[-1][1] == status}")
print(f"run order: {runs}")
print()
ok = (
    len(runs) == 8
    and sum(1 for _, run in steps if run == status) == 1
    and text.count("continue-on-error") == 0
    and text.count(shape) == 1
    and text.index(campaign) < text.index(shape) < text.index(status)
    and steps[-1][1] == status
)
print(f"RESULT: {'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
