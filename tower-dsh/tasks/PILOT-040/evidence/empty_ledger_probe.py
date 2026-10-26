#!/usr/bin/env python3
"""PILOT-040 probe: configured tower + 0-byte supervision ledger + legacy merge.

Builds one throw-away kit and drives the *given* ``towerctl.py`` through the
exact attack fixture:

    configured tower            (authority-set -> state/AUTHORITY.json + event)
    legacy envelope file        (hand-written, no ENVELOPE_NEW/QUEUE_ADD event)
    MERGE_QUEUE.json entry      (hand-written WAITING row)
    ledger/supervision.jsonl    (exists, 0 bytes / 0 events)

Then it runs ``merge-check`` and ``merge`` and prints one JSON summary line per
command.  The old (main) tool accepts this merge; the 040 tool refuses at the
empty-ledger guard before reading the envelope/queue/git.

Usage::

    python scratch/empty_ledger_probe.py --tool <path-to-towerctl.py> [--keep]
    python scratch/empty_ledger_probe.py --tool scratch/old/towerctl.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TASK = "T-PROBE-040"
ENVELOPE = "ENV-PROBE-040"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/probe-040"
FIXED_TIME = "2026-10-23T00:00:00+08:00"
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"
GUARD_TEXT = "supervision ledger is empty but envelope/queue history exists"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    cp = subprocess.run(["git", "-C", str(repo), *args],
                        capture_output=True, text=True, encoding="utf-8",
                        env=env)
    if cp.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp


def run_tool(tool: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


def build_kit(work: Path, tool: Path) -> tuple[Path, Path]:
    kit = work / "kit"
    root = kit / "tower-dsh"
    for directory in ("primary", "supervision/envelopes", "supervision/registries",
                      "ledger", "shared", "state", f"tasks/{TASK}/evidence"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    proof = root / "tasks" / TASK / "evidence" / "proof.txt"
    proof.write_text("proof\n", encoding="utf-8")
    write_json(root / "tasks" / TASK / "record.json", {
        "schema": "tower/task@1", "id": TASK, "title": "probe",
        "status": "accepted", "executor": "exec-a",
        "review": {"reviewer": "rev-a", "verdict": "PASS"},
        "evidence": [{
            "id": "E-001",
            "path": f"tasks/{TASK}/evidence/proof.txt",
            "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
            "bytes": proof.stat().st_size, "at": FIXED_TIME,
        }],
    })
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "phase": "PROBE", "primary": {"id": PRIMARY_ID},
        "owner": {"name": "mac"}, "next_action": "probe",
    })
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "PROBE", "supervisor": {"id": SUPERVISOR_ID},
    })
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})

    run_git(kit, "init")
    run_git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / "merge-envelopes").mkdir()
    run_git(kit, "add", "-A")
    run_git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "base")
    run_git(kit, "checkout", "-b", BRANCH)
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    run_git(kit, "add", "-A")
    run_git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "implementation")
    implementation_head = run_git(kit, "rev-parse", "HEAD").stdout.strip()
    write_json(kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
    run_git(kit, "add", "-A")
    run_git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "envelope")
    envelope_head = run_git(kit, "rev-parse", "HEAD").stdout.strip()
    run_git(kit, "checkout", "main")

    # Configure authority with the tool under test (both implements 037).
    cp = run_tool(tool, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                  "--decision", "D-PROBE", "--by", "mac")
    if cp.returncode != 0:
        raise SystemExit(f"authority-set failed: {cp.stdout}{cp.stderr}")

    # The attack fixture: hand-written legacy envelope + queue row, and a
    # supervision ledger that exists but carries zero events (0 bytes).
    write_json(root / "supervision" / "envelopes" / f"{ENVELOPE}.json", {
        "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
        "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
        "envelope_path": ENVELOPE_PATH,
        "implementation_head_sha": implementation_head,
        "envelope_head_sha": envelope_head, "status": "DRAFT",
    })
    write_json(root / "supervision" / "MERGE_QUEUE.json", {
        "schema": "tower/merge-queue@1",
        "entries": [{"envelope_id": ENVELOPE, "task": TASK, "branch": BRANCH,
                     "base": "main", "status": "WAITING",
                     "added_at": FIXED_TIME}],
    })
    (root / "ledger" / "supervision.jsonl").write_bytes(b"")
    return kit, root


def summarize(label: str, cp: subprocess.CompletedProcess, root: Path,
              before_queue: bytes, before_ledger: bytes) -> dict:
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        payload = {"non_json_stdout": cp.stdout, "stderr": cp.stderr}
    ledger = (root / "ledger" / "supervision.jsonl")
    ledger_bytes = ledger.read_bytes() if ledger.exists() else None
    queue_bytes = (root / "supervision" / "MERGE_QUEUE.json").read_bytes()
    queue = json.loads(queue_bytes.decode("utf-8"))
    entry = queue["entries"][0] if queue.get("entries") else {}
    blob = json.dumps(payload, ensure_ascii=False)
    return {
        "command": label,
        "exit": cp.returncode,
        "ok": payload.get("ok"),
        "guard_text_present": GUARD_TEXT in blob,
        "payload": payload,
        "queue_status_after": entry.get("status"),
        "queue_unchanged": queue_bytes == before_queue,
        "supervision_ledger_bytes": (0 if ledger_bytes == b""
                                     else (None if ledger_bytes is None
                                           else len(ledger_bytes))),
        "supervision_ledger_unchanged": ledger_bytes == before_ledger,
        "merge_start_recorded": bool(ledger_bytes and b"MERGE_START" in ledger_bytes),
        "merging_recorded": bool(ledger_bytes and b"MERGING" in ledger_bytes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True,
                        help="towerctl.py to probe (new worktree copy or old main copy)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the probe kit directory (gitignored scratch)")
    args = parser.parse_args(argv)
    tool = Path(args.tool).resolve()
    if not tool.is_file():
        raise SystemExit(f"tool not found: {tool}")
    work = Path(tempfile.mkdtemp(prefix="pilot040-probe-",
                                 dir=str(Path(__file__).resolve().parent)))
    try:
        kit, root = build_kit(work, tool)
        before_queue = (root / "supervision" / "MERGE_QUEUE.json").read_bytes()
        before_ledger = (root / "ledger" / "supervision.jsonl").read_bytes()
        summary = {
            "tool": str(tool),
            "fixture": "configured + 0-byte supervision ledger + legacy envelope + queue row",
            "supervision_ledger_before_bytes": len(before_ledger),
        }
        print(json.dumps(summary, ensure_ascii=False))

        check = run_tool(tool, root, "merge-check", "--envelope", ENVELOPE)
        print(json.dumps(summarize("merge-check", check, root, before_queue,
                                   before_ledger), ensure_ascii=False))

        merge = run_tool(tool, root, "merge", "--role", "supervisor",
                        "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE)
        print(json.dumps(summarize("merge", merge, root, before_queue,
                                   before_ledger), ensure_ascii=False))

        envelope = json.loads(
            (root / "supervision" / "envelopes" / f"{ENVELOPE}.json")
            .read_text(encoding="utf-8"))
        print(json.dumps({"envelope_status_after": envelope.get("status")},
                         ensure_ascii=False))
        return 0
    finally:
        if args.keep:
            print(f"KEPT={work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
