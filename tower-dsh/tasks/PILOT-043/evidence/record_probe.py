#!/usr/bin/env python3
"""PILOT-043 probe: forged completion, record-vs-event base_sha, tampered sha.

Run against the new tool and against ``scratch/old/towerctl.py`` (main's copy):
the old code accepts a hand-written completion (exit 0), trusts a record
base_sha rewritten to HEAD (empty diff, exit 0) and ignores a base_sha that
disagrees with the DISPATCH event (state-verify drift []); the new code rejects
all three.

    python -B scratch/record_probe.py --tool tools/towerctl.py
    python -B scratch/record_probe.py --tool scratch/old/towerctl.py

Both fixtures are throw-away towers under a temporary directory; nothing in the
real tower is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE_ROOT = Path(__file__).resolve().parents[1] / "tower-dsh"
TOOLS = PROBE_ROOT / "tools"
TASK = "PROBE-043"
WORKTREE_REL = f"pilot/worktrees/{TASK}"
BASE_SHA = "a" * 40
TAMPERED_SHA = "b" * 40
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def run_tool(tool: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TOOLS)
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


def tower_state(root: Path) -> None:
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "primary": {"id": "ctl-probe"},
        "owner": {"name": "mac"},
    })
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()


def forged_delivery_probe(tool: Path) -> dict:
    """A record-only COMPLETION entry authorises a path: old 0, new 2."""
    with tempfile.TemporaryDirectory(prefix="tower-probe-deliver-",
                                     ignore_cleanup_errors=True) as tmp:
        kit = Path(tmp) / "kit"
        root = kit / "tower-dsh"
        worktree = root / WORKTREE_REL
        kit.mkdir(parents=True, exist_ok=True)
        (kit / "README.md").write_text("base\n", encoding="utf-8")
        (kit / ".gitignore").write_text("tower-dsh/pilot/worktrees/\n",
                                        encoding="utf-8")
        (root / "tools").mkdir(parents=True, exist_ok=True)
        (root / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        tower_state(root)
        write_json(root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": TASK,
            "status": "dispatched", "authority": "workspace_write",
            "worktree": WORKTREE_REL,
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "dispatch": {"executor": "exec-probe", "worktree": WORKTREE_REL},
            "evidence": [],
            "completions": [{
                "task": TASK,
                "path": f"{WORKTREE_REL}/tower-dsh/tools/forged.py",
                "by": "mac", "reason": "forged", "decision": "D-FORGED",
                "at": "2026-10-20T00:00:00+08:00",
            }],
        })
        run_git(kit, "init")
        run_git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
        run_git(kit, "add", "-A")
        run_git(kit, "commit", "-m", "base")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        run_git(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK}")
        (worktree / "tower-dsh" / "tools" / "forged.py").write_text(
            "forged = 1\n", encoding="utf-8")
        run_git(worktree, "add", "-A")
        run_git(worktree, "commit", "-m", "forged completion path")
        proof = root / "work" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("probe\n", encoding="utf-8")

        cp = run_tool(tool, root, "deliver", "--task", TASK,
                      "--evidence", "work/proof.txt")
        record = json.loads((root / "tasks" / TASK / "record.json")
                            .read_text(encoding="utf-8"))
        events = [json.loads(line) for line in
                  (root / "ledger" / "primary.jsonl").read_text(
                      encoding="utf-8").splitlines() if line.strip()]
        return {
            "case": "forged completion delivery",
            "exit": cp.returncode,
            "record_status": record.get("status"),
            "evidence_written": (root / "tasks" / TASK / "evidence").exists(),
            "deliver_events": sum(1 for event in events
                                  if event.get("type") == "DELIVER"),
            "errors": json.loads(cp.stdout).get("errors", [])
            if cp.returncode == 2 else [],
        }


def dispatch_base_bypass_probe(tool: Path) -> dict:
    """Record base_sha rewritten to HEAD while DISPATCH keeps the old sha.

    Old code trusts the record, so the diff becomes empty and an out-of-scope
    file on the branch delivers.  New code takes the diff base from the
    DISPATCH event and rejects the inequality before computing the diff.
    """
    with tempfile.TemporaryDirectory(prefix="tower-probe-r1-",
                                     ignore_cleanup_errors=True) as tmp:
        kit = Path(tmp) / "kit"
        root = kit / "tower-dsh"
        worktree = root / WORKTREE_REL
        kit.mkdir(parents=True, exist_ok=True)
        (kit / "README.md").write_text("base\n", encoding="utf-8")
        (kit / ".gitignore").write_text("tower-dsh/pilot/worktrees/\n",
                                        encoding="utf-8")
        (root / "tools").mkdir(parents=True, exist_ok=True)
        (root / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        tower_state(root)
        record_path = root / "tasks" / TASK / "record.json"
        write_json(record_path, {
            "schema": "tower/task@1", "id": TASK, "title": TASK,
            "status": "dispatched", "authority": "workspace_write",
            "worktree": WORKTREE_REL,
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "dispatch": {"executor": "exec-probe", "worktree": WORKTREE_REL},
            "evidence": [],
        })
        run_git(kit, "init")
        run_git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
        run_git(kit, "add", "-A")
        run_git(kit, "commit", "-m", "base")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        run_git(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK}")
        base = run_git(kit, "rev-parse", "main").stdout.strip()

        sys.path.insert(0, str(TOOLS))
        import towerctl  # noqa: E402  (only for ledger appends)
        towerctl.append_ledger(root, "DISPATCH", "primary",
                               {"task": TASK, "base_sha": base})
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["dispatch"]["base_sha"] = base
        write_json(record_path, record)

        (worktree / "tower-dsh" / "pilot").mkdir(parents=True, exist_ok=True)
        (worktree / "tower-dsh" / "pilot" / "other.json").write_text(
            '{"v": 2}\n', encoding="utf-8")
        run_git(worktree, "add", "-A")
        run_git(worktree, "commit", "-m", "out of scope change")
        head = run_git(worktree, "rev-parse", "HEAD").stdout.strip()
        record["dispatch"]["base_sha"] = head
        write_json(record_path, record)
        proof = root / "work" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("probe\n", encoding="utf-8")

        cp = run_tool(tool, root, "deliver", "--task", TASK,
                      "--evidence", "work/proof.txt")
        current = json.loads(record_path.read_text(encoding="utf-8"))
        events = [json.loads(line) for line in
                  (root / "ledger" / "primary.jsonl").read_text(
                      encoding="utf-8").splitlines() if line.strip()]
        return {
            "case": "record base_sha rewritten to HEAD (DISPATCH unchanged)",
            "dispatch_event_base_sha": base,
            "record_base_sha": head,
            "exit": cp.returncode,
            "record_status": current.get("status"),
            "evidence_written": (root / "tasks" / TASK / "evidence").exists(),
            "deliver_events": sum(1 for event in events
                                  if event.get("type") == "DELIVER"),
            "errors": json.loads(cp.stdout).get("errors", [])
            if cp.returncode == 2 else [],
        }


def base_sha_probe(tool: Path) -> dict:
    """A record base_sha disagreeing with DISPATCH: old 0 drift, new drift."""
    with tempfile.TemporaryDirectory(prefix="tower-probe-base-",
                                     ignore_cleanup_errors=True) as tmp:
        root = Path(tmp) / "tower-dsh"
        tower_state(root)
        write_json(root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        write_json(root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{"id": TASK, "title": TASK, "status": "delivered"}]})
        sys.path.insert(0, str(TOOLS))
        import towerctl  # noqa: E402  (only for ledger appends)
        towerctl.append_ledger(root, "TASK_NEW", "primary", {"task": TASK})
        towerctl.append_ledger(root, "DISPATCH", "primary",
                               {"task": TASK, "base_sha": BASE_SHA})
        towerctl.append_ledger(root, "DELIVER", "primary", {"task": TASK})
        write_json(root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": TASK,
            "status": "delivered",
            "dispatch": {"executor": "exec-probe", "at": "2026-10-20T00:00:00+08:00",
                         "base_sha": TAMPERED_SHA},
        })
        cp = run_tool(tool, root, "state-verify")
        payload = json.loads(cp.stdout)
        return {
            "case": "tampered dispatch base_sha",
            "exit": cp.returncode,
            "drift_kinds": [row["kind"] for row in payload.get("drift", [])],
            "drift": payload.get("drift", []),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default=str(TOOLS / "towerctl.py"),
                        help="towerctl.py to probe (default: the worktree copy)")
    parser.add_argument("--label", default="new")
    args = parser.parse_args()
    tool = Path(args.tool).resolve()
    result = {
        "label": args.label,
        "tool": str(tool),
        "forged_completion": forged_delivery_probe(tool),
        "dispatch_base_bypass": dispatch_base_bypass_probe(tool),
        "tampered_base_sha": base_sha_probe(tool),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
