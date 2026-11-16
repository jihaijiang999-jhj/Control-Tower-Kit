"""PILOT-078 evidence probe: recompute the doc numbers and prove 072 refusal.

Read-only except for one throw-away ``pilot/worktrees/PILOT-072`` directory that
is created and removed around the ``task-new`` refusal probe (the worktree gate
runs before the id-registry gate, so the directory has to exist to expose the
``void`` refusal).  No ledger/state byte is written: the primary ledger hash is
compared before and after.

Usage (from the tower root ``tower-dsh``):

    python scratch/docs_probe.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOWER = Path.cwd()
REPO = TOWER.parent
PY = sys.executable


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    lines: list[str] = []

    def say(text: str) -> None:
        print(text)
        lines.append(text)

    ids = json.loads((TOWER / "state" / "TASK_IDS.json").read_text(encoding="utf-8"))["ids"]
    cards = [p for p in (TOWER / "tasks").iterdir()
             if p.is_dir() and re.fullmatch(r"PILOT-\d{3}", p.name)]
    code_cards = sum(1 for p in cards if int(p.name.split("-")[1]) <= 77)
    envs = [json.loads(p.read_text(encoding="utf-8")) for p in
            sorted((TOWER / "supervision" / "envelopes").glob("ENV-PILOT-*.json"))]
    envelopes = sum(1 for env in envs if int(env["task"].split("-")[1]) <= 77)
    tests = json.loads((TOWER / "supervision" / "envelopes" / "ENV-PILOT-077.json")
                       .read_text(encoding="utf-8"))["tower_tests_baseline"]
    roadmap = re.search(r"(?m)^roadmap:\s*\n((?:  - PILOT-\d+\n)+)",
                        (TOWER / "command" / "campaigns" / "C-2026-Q4-04.md")
                        .read_text(encoding="utf-8")).group(1)
    nodes = re.findall(r"PILOT-\d+", roadmap)
    delivery = [n for n in nodes if n != "PILOT-078"]
    gates = len(json.loads((TOWER / "arch" / "GATES.json").read_text(encoding="utf-8"))["gates"])
    events = len(json.loads((TOWER / "EVENT_CATALOG.json").read_text(encoding="utf-8"))["events"])
    modules = len(glob.glob(str(TOWER / "tools" / "tower_*.py")))

    say(f"code_cards={code_cards} envelopes={envelopes} tests_baseline={tests} "
        f"delivery_cards={len(delivery)} campaign_nodes={len(nodes)}")
    say(f"arch: gates={gates} events={events} modules={modules}")

    entry = ids.get("PILOT-072") or {}
    say(f"TASK_IDS[PILOT-072]: status={entry.get('status')!r} "
        f"spec_path={entry.get('spec_path')!r}")

    next_window = (TOWER / "NEXT-WINDOW.md").read_text(encoding="utf-8")
    readme = (TOWER / "README.md").read_text(encoding="utf-8")
    reproduce = (TOWER / "REPRODUCE.md").read_text(encoding="utf-8")
    walkthrough_path = TOWER / "docs" / "WALKTHROUGH.md"
    walkthrough = walkthrough_path.read_text(encoding="utf-8")
    for needle in ("76 代码卡", "74 信封", "844", "16-16", "第 17 个 campaign 节点"):
        say(f"NEXT-WINDOW contains {needle!r}: {needle in next_window}")
    say(f"README contains 76 代码卡 / 16-16: "
        f"{('76 代码卡' in readme) and ('16-16' in readme)}")
    say(f"REPRODUCE: 844={('844' in reproduce)} 252_absent={('252' not in reproduce)} "
        f"fetch-depth_0={('fetch-depth: 0' in reproduce)} "
        f"walkthrough_link={'docs/WALKTHROUGH.md' in reproduce}")
    say(f"WALKTHROUGH exists={walkthrough_path.is_file()} bytes={len(walkthrough)}")

    # task-new refusal: create the throw-away worktree so the registry gate is reached.
    ledger = TOWER / "ledger" / "primary.jsonl"
    before = sha(ledger)
    temp_wt = TOWER / "pilot" / "worktrees" / "PILOT-072"
    created = not temp_wt.exists()
    temp_wt.mkdir(parents=True, exist_ok=True)
    try:
        cp = subprocess.run([PY, "-B", "tools/towerctl.py", "task-new",
                             "--spec", "pilot/PILOT-072.spec.json.parked"],
                            cwd=TOWER, capture_output=True, text=True, encoding="utf-8")
    finally:
        if created:
            temp_wt.rmdir()
    after = sha(ledger)
    blob = (cp.stdout or "") + (cp.stderr or "")
    say(f"task-new PILOT-072: exit={cp.returncode} "
        f"already_registered={'already registered' in blob} "
        f"void={'void' in blob}")
    say(f"primary ledger unchanged: {before == after} ({before[:12]})")

    ok = (code_cards == 76 and envelopes == 74 and tests == 844
          and len(delivery) == 16 and len(nodes) == 17
          and entry.get("status") == "void"
          and entry.get("spec_path") == "pilot/PILOT-072.spec.json.parked"
          and walkthrough_path.is_file()
          and cp.returncode == 2 and "already registered" in blob and "void" in blob
          and before == after)
    say(f"PROBE_RESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
