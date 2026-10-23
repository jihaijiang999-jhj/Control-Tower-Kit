"""PILOT-035 probe: half-written queue window repair against a temp tower.

Runs three scenarios with the worktree's ``tower-dsh/tools/towerctl.py``:

1. half-write (WAITING queue entry, no ``QUEUE_ADD``) -> repaired;
2. same half-write but the envelope lacks ``tower_tests_baseline`` -> rejected;
3. the repaired envelope queued again -> still "already queued".

The tower lives under ``evidence/_probe_work`` so nothing real is touched.
Writes only the report to stdout; the caller redirects it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
WORKTREE = EVIDENCE.parent
TCLI = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
WORK = EVIDENCE / "_probe_work"

TASK = "T-PROBE-001"
ENVELOPE = "ENV-PROBE-001"

lines: list[str] = []


def say(text: str = "") -> None:
    lines.append(text)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def fresh_tower(missing: str | None = None) -> Path:
    shutil.rmtree(WORK, ignore_errors=True)
    root = WORK / "tower-dsh"
    for directory in ("primary", "supervision/envelopes", "ledger"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    envelope = {
        "schema": "tower/merge-envelope@1",
        "envelope_id": ENVELOPE,
        "task": TASK,
        "repository": "..",
        "branch": "feature/probe",
        "base": "main",
        "envelope_path": f"merge-envelopes/{ENVELOPE}.json",
        "implementation_head_sha": "a" * 40,
        "envelope_head_sha": "b" * 40,
        "tests_baseline": 1,
        "tower_tests_baseline": 1,
        "status": "DRAFT",
    }
    if missing is not None:
        del envelope[missing]
    write_json(root / "supervision" / "envelopes" / f"{ENVELOPE}.json",
               envelope)
    write_json(root / "supervision" / "MERGE_QUEUE.json", {
        "schema": "tower/merge-queue@1",
        "entries": [{
            "envelope_id": ENVELOPE, "task": TASK,
            "branch": "feature/probe", "base": "main",
            "status": "WAITING", "added_at": "2026-10-23T00:00:00+08:00",
        }],
    })
    return root


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def ledger_events(root: Path, event_type: str) -> list[dict]:
    path = root / "ledger" / "supervision.jsonl"
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("type") == event_type]


def queue_entries(root: Path) -> list[dict]:
    return json.loads((root / "supervision" / "MERGE_QUEUE.json")
                      .read_text(encoding="utf-8"))["entries"]


def report_verify(label: str, root: Path) -> dict:
    cp = run(root, "state-verify")
    payload = json.loads(cp.stdout)
    unbacked = [row for row in payload["drift"]
                if row.get("kind") == "queue_unbacked"]
    say(f"{label}: state-verify rc={cp.returncode} "
        f"ok={payload['ok']} drift_count={len(payload['drift'])}")
    say(f"{label}: queue_unbacked={json.dumps(unbacked, ensure_ascii=False)}")
    return payload


say("== PILOT-035 half-written queue window probe ==")
say(f"towerctl={TCLI}")
say()

# -- 1. half-write repair -------------------------------------------------
say("== CASE 1: half-write (queue entry, no QUEUE_ADD) -> repair ==")
root = fresh_tower()
say(f"precondition QUEUE_ADD count={len(ledger_events(root, 'QUEUE_ADD'))}")
before = report_verify("before repair", root)
assert [row["kind"] for row in before["drift"]].count("queue_unbacked") == 1, \
    "precondition must be queue_unbacked"

cp = run(root, "queue-add", "--envelope", ENVELOPE)
say(f"queue-add rc={cp.returncode}")
say(f"queue-add stdout={cp.stdout.strip()}")
say(f"queue-add stderr={cp.stderr.strip()}")
payload = json.loads(cp.stdout)
assert cp.returncode == 0, cp.stdout + cp.stderr
assert payload == {"ok": True, "envelope": ENVELOPE, "status": "WAITING",
                   "repaired": True}, payload
events = ledger_events(root, "QUEUE_ADD")
say(f"QUEUE_ADD count after={len(events)}")
say("QUEUE_ADD payloads=" + json.dumps(
    [e.get("payload") for e in events], ensure_ascii=False))
assert len(events) == 1, events
entries = queue_entries(root)
say(f"queue entries after={json.dumps(entries, ensure_ascii=False)}")
assert len(entries) == 1 and entries[0]["status"] == "WAITING", entries
after = report_verify("after repair", root)
assert not [row for row in after["drift"]
            if row.get("kind") == "queue_unbacked"], after["drift"]
say("CASE 1: PASS")
say()

# -- 2. baseline gate still protects the repair path ----------------------
say("== CASE 2: half-write with missing tower_tests_baseline -> reject ==")
root = fresh_tower(missing="tower_tests_baseline")
queue_before = (root / "supervision" / "MERGE_QUEUE.json").read_bytes()
ledger_before = (root / "ledger" / "supervision.jsonl").read_bytes()
cp = run(root, "queue-add", "--envelope", ENVELOPE)
say(f"queue-add rc={cp.returncode}")
say(f"queue-add stdout={cp.stdout.strip()}")
say(f"queue-add stderr={cp.stderr.strip()}")
assert cp.returncode == 2, cp.stdout + cp.stderr
assert "tower_tests_baseline" in cp.stdout + cp.stderr
assert (root / "supervision" / "MERGE_QUEUE.json").read_bytes() == queue_before
assert (root / "ledger" / "supervision.jsonl").read_bytes() == ledger_before
assert ledger_events(root, "QUEUE_ADD") == []
entries = queue_entries(root)
say(f"queue bytes unchanged=True; entries={json.dumps(entries, ensure_ascii=False)}")
assert len(entries) == 1 and entries[0]["status"] == "WAITING"
say("CASE 2: PASS")
say()

# -- 3. ledger-backed duplicate is still rejected -------------------------
say("== CASE 3: already-properly-queued retry -> duplicate ==")
root = fresh_tower()
cp = run(root, "queue-add", "--envelope", ENVELOPE)
assert cp.returncode == 0, cp.stdout + cp.stderr
assert len(ledger_events(root, "QUEUE_ADD")) == 1
queue_before = (root / "supervision" / "MERGE_QUEUE.json").read_bytes()
ledger_before = (root / "ledger" / "supervision.jsonl").read_bytes()
cp = run(root, "queue-add", "--envelope", ENVELOPE)
say(f"queue-add rc={cp.returncode}")
say(f"queue-add stdout={cp.stdout.strip()}")
assert cp.returncode == 2, cp.stdout + cp.stderr
assert "already queued" in cp.stdout + cp.stderr
assert (root / "supervision" / "MERGE_QUEUE.json").read_bytes() == queue_before
assert (root / "ledger" / "supervision.jsonl").read_bytes() == ledger_before
say(f"QUEUE_ADD count unchanged={len(ledger_events(root, 'QUEUE_ADD'))}")
say(f"entry count unchanged={len(queue_entries(root))}")
say("CASE 3: PASS")
say()
say("PROBE OK (3/3 scenarios)")

shutil.rmtree(WORK, ignore_errors=True)
print("\n".join(lines))
