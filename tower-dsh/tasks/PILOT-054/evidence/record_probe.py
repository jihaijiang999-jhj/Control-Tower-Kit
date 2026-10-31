#!/usr/bin/env python3
"""PILOT-054 record-layer probe (executor evidence, not part of the suite).

Rebuilds the PILOT-043 R1 attacks plus the two record-layer acceptance probes
against an arbitrary ``tools/towerctl.py``:

* deliver: record==DISPATCH(base_sha) delivers; a ``completion-add`` backed
  completion delivers with the expected ``scope_completions``; an out-of-scope
  commit hidden behind a record ``base_sha`` rewritten to HEAD is rejected with
  zero writes; a record ``base_sha`` with no DISPATCH event is rejected; a
  hand-written ``record.completions`` entry with no ``COMPLETION_ADDED`` is
  rejected.
* state-verify: a record ``base_sha`` that disagrees with its DISPATCH event is
  ``dispatch_base_mismatch``; a COMPLETION_ADDED for a task that does not exist
  is ``completion_orphan``.

Run the same script twice to get the before/after evidence (both transcripts in
``scratch/``; the shell redirect keeps the full transcript)::

    python -B scratch/record_probe.py --label new --tool tools/towerctl.py \
        > scratch/probe.txt 2>&1
    # main-version tool, with its sibling modules (unchanged in this branch):
    git show main:tower-dsh/tools/towerctl.py > scratch/.oldtool/towerctl.py
    copy tools/spec_coverage.py tools/spec_lint.py scratch/.oldtool/
    python -B scratch/record_probe.py --label old --tool scratch/.oldtool/towerctl.py \
        > scratch/probe-old-code.txt 2>&1

Exit code 0 means every observation matched the expectation recorded for the
label; 1 means at least one probe differed (the details are printed either way).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

TASK = "PROBE-054"
WORKTREE_REL = f"pilot/worktrees/{TASK}"
OWNER = "mac"
FIXED_TIME = "2026-10-20T00:00:00+08:00"
REASON = "6.11 authorized completion: helper needed by the probe"
DECISION = "D-054"
PROOF_REL = "work/proof.txt"
COMPLETION_PATH = f"{WORKTREE_REL}/tower-dsh/tools/helper.py"
BASE_SHA = "a" * 40
OTHER_SHA = "b" * 40
ORPHAN_TASK = "PROBE-054-ORPHAN"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}

EXPECTATIONS = {
    "new": {
        "deliver_matched": {"exit": 0, "record_status": "delivered",
                            "deliver_events": 1, "evidence_dir": True},
        "deliver_completion_backed": {
            "exit": 0, "record_status": "delivered", "deliver_events": 1,
            "evidence_dir": True,
            "scope_completions": ["tower-dsh/tools/helper.py"]},
        "deliver_out_of_scope_head": {"exit": 2, "record_status": "dispatched",
                                      "deliver_events": 0, "evidence_dir": False,
                                      "errors_contain": "dispatch base_sha does not match"},
        "deliver_record_sha_without_event": {
            "exit": 2, "record_status": "dispatched", "deliver_events": 0,
            "evidence_dir": False, "errors_contain": "not backed by a DISPATCH event"},
        "deliver_forged_completion": {
            "exit": 2, "record_status": "dispatched", "deliver_events": 0,
            "evidence_dir": False,
            "errors_contain": "completion not backed by COMPLETION_ADDED"},
        "verify_tampered_base_sha": {
            "exit": 2, "drift_kinds": ["dispatch_base_mismatch"]},
        "verify_orphan_completion": {
            "exit": 2, "drift_kinds": ["completion_orphan"]},
    },
    "old": {
        "deliver_matched": {"exit": 0, "record_status": "delivered",
                            "deliver_events": 1, "evidence_dir": True},
        "deliver_completion_backed": {
            "exit": 0, "record_status": "delivered", "deliver_events": 1,
            "evidence_dir": True,
            "scope_completions": ["tower-dsh/tools/helper.py"]},
        "deliver_out_of_scope_head": {"exit": 0, "record_status": "delivered",
                                      "deliver_events": 1, "evidence_dir": True},
        "deliver_record_sha_without_event": {
            "exit": 0, "record_status": "delivered", "deliver_events": 1,
            "evidence_dir": True},
        "deliver_forged_completion": {"exit": 0, "record_status": "delivered",
                                      "deliver_events": 1, "evidence_dir": True},
        "verify_tampered_base_sha": {"exit": 0, "drift_kinds": []},
        "verify_orphan_completion": {"exit": 0, "drift_kinds": []},
    },
}


def load_tool(path: Path):
    # ``towerctl`` imports its sibling ``spec_coverage``/``spec_lint`` modules.
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("probe_towerctl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def git_ok(cwd: Path, *args: str) -> str:
    done = git(cwd, *args)
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr}{done.stdout}")
    return done.stdout.strip()


def run_cli(tool: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(tool), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ledger_events(root: Path) -> list[dict]:
    path = root / "ledger" / "primary.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_state(root: Path) -> None:
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "primary": {"id": "ctl-probe"},
        "owner": {"name": OWNER}})
    write_json(root / "primary" / "TASK_BOARD.json", {
        "schema": "tower/task-board@1", "tower_id": "tower-dsh", "tasks": []})
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()


def task_record() -> dict:
    return {
        "schema": "tower/task@1", "id": TASK, "title": TASK,
        "status": "dispatched", "authority": "workspace_write",
        "worktree": WORKTREE_REL,
        "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
        "dispatch": {"executor": "probe-exec", "worktree": WORKTREE_REL,
                     "at": FIXED_TIME},
        "evidence": []}


def build_git_tower(base: Path) -> tuple[Path, Path]:
    kit = base / "kit"
    tower = kit / "tower-dsh"
    worktree = tower / WORKTREE_REL
    (kit / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / ".gitignore").write_text("tower-dsh/pilot/worktrees/\n", encoding="utf-8")
    (tower / "tools").mkdir(parents=True, exist_ok=True)
    (tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (tower / "pilot").mkdir(parents=True, exist_ok=True)
    (tower / "pilot" / f"{TASK}.spec.json").write_text("{}\n", encoding="utf-8")
    git_ok(kit, "init")
    git_ok(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    git_ok(kit, "add", "-A")
    git_ok(kit, "commit", "-m", "base")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git_ok(kit, "worktree", "add", str(worktree), "-b", f"pilot/{TASK}")
    write_state(tower)
    write_json(tower / "tasks" / TASK / "record.json", task_record())
    (tower / PROOF_REL).parent.mkdir(parents=True, exist_ok=True)
    (tower / PROOF_REL).write_text("proof of work\n", encoding="utf-8")
    return tower, worktree


def commit_file(worktree: Path, relpath: str, text: str, message: str) -> None:
    target = worktree / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git_ok(worktree, "add", "-A")
    git_ok(worktree, "commit", "-m", message)


def save_record(tower: Path, mutate) -> None:
    record = read_json(tower / "tasks" / TASK / "record.json")
    mutate(record)
    write_json(tower / "tasks" / TASK / "record.json", record)


def deliver_summary(cp: subprocess.CompletedProcess, tower: Path) -> dict:
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        payload = {}
    record = read_json(tower / "tasks" / TASK / "record.json")
    events = ledger_events(tower)
    return {
        "exit": cp.returncode,
        "ok": payload.get("ok"),
        "errors": payload.get("errors", []),
        "scope_files": payload.get("scope_files"),
        "scope_completions": payload.get("scope_completions"),
        "record_status": record.get("status"),
        "evidence_dir": (tower / "tasks" / TASK / "evidence").exists(),
        "deliver_events": sum(1 for e in events if e.get("type") == "DELIVER"),
    }


def probe_deliver(base: Path, tool: Path, towerctl, name: str,
                  setup) -> dict:
    tower, worktree = build_git_tower(base / name)
    setup(tower, worktree, towerctl)
    cp = run_cli(tool, tower, "deliver", "--task", TASK,
                 "--evidence", PROOF_REL)
    summary = deliver_summary(cp, tower)
    print(f"[deliver:{name}] exit={summary['exit']} "
          f"errors={summary['errors']} scope_completions={summary['scope_completions']} "
          f"status={summary['record_status']} evidence={summary['evidence_dir']} "
          f"deliver_events={summary['deliver_events']}")
    return summary


def probe_verify(base: Path, tool: Path, towerctl, name: str, *,
                 dispatch_sha: str | None, record_sha: str | None,
                 orphan: bool = False) -> dict:
    root = base / name
    write_state(root)
    (root / "supervision" / "envelopes").mkdir(parents=True, exist_ok=True)
    (root / "supervision" / "MERGE_QUEUE.json").write_text(
        '{"schema": "tower/merge-queue@1", "entries": []}\n', encoding="utf-8")
    write_json(root / "primary" / "TASK_BOARD.json", {
        "schema": "tower/task-board@1", "tower_id": "tower-dsh",
        "tasks": [{"id": TASK, "title": TASK, "status": "delivered"}]})
    towerctl.append_ledger(root, "TASK_NEW", "primary", {"task": TASK})
    dispatch = {"task": TASK}
    if dispatch_sha is not None:
        dispatch["base_sha"] = dispatch_sha
    towerctl.append_ledger(root, "DISPATCH", "primary", dispatch)
    towerctl.append_ledger(root, "DELIVER", "primary", {"task": TASK})
    if orphan:
        towerctl.append_ledger(root, "COMPLETION_ADDED", "primary", {
            "task": ORPHAN_TASK, "path": "pilot/orphan.py", "by": OWNER,
            "reason": REASON, "decision": DECISION, "at": FIXED_TIME})
    record = {"schema": "tower/task@1", "id": TASK, "title": TASK,
              "status": "delivered",
              "dispatch": {"executor": "probe-exec", "at": FIXED_TIME}}
    if record_sha is not None:
        record["dispatch"]["base_sha"] = record_sha
    write_json(root / "tasks" / TASK / "record.json", record)
    cp = run_cli(tool, root, "state-verify")
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        payload = {}
    kinds = sorted(row.get("kind") for row in payload.get("drift", []))
    summary = {"exit": cp.returncode, "drift_kinds": kinds,
               "drift": payload.get("drift", []),
               "errors": payload.get("errors", []),
               "stderr": cp.stderr.strip()}
    print(f"[verify:{name}] exit={summary['exit']} drift={kinds} "
          f"errors={summary['errors']} stderr={summary['stderr']!r}")
    return summary


def compare(name: str, result: dict, expected: dict) -> list[str]:
    problems: list[str] = []
    for key, want in expected.items():
        if key == "errors_contain":
            errors = "\n".join(result.get("errors") or [])
            if want not in errors:
                problems.append(f"{name}: errors missing {want!r}: {errors!r}")
        elif key == "drift_kinds":
            if result.get("drift_kinds") != want:
                problems.append(f"{name}: drift_kinds {result.get('drift_kinds')} != {want}")
        elif result.get(key) != want:
            problems.append(f"{name}: {key} {result.get(key)!r} != {want!r}")
    return problems


def force_rmtree(path: Path) -> None:
    """Remove a tree even when git left read-only object files (Windows)."""
    def onexc(func, target, exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onexc=onexc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, help="towerctl.py under test")
    parser.add_argument("--label", required=True, choices=sorted(EXPECTATIONS))
    parser.add_argument("--out", help="also write the transcript here")
    parser.add_argument("--keep", action="store_true", help="keep the sandbox")
    args = parser.parse_args()
    tool = Path(args.tool).resolve()
    towerctl = load_tool(tool)
    base = Path(__file__).resolve().parent / ".probe"
    if base.exists():
        force_rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    def matched(tower, worktree, mod):
        head = git_ok(worktree, "rev-parse", "HEAD")
        mod.append_ledger(tower, "DISPATCH", "primary",
                          {"task": TASK, "base_sha": head})
        save_record(tower, lambda r: r["dispatch"].update(base_sha=head))
        commit_file(worktree, "tower-dsh/tools/x.py", "x = 2\n", "in scope change")

    def out_of_scope_head(tower, worktree, mod):
        head = git_ok(worktree, "rev-parse", "HEAD")
        mod.append_ledger(tower, "DISPATCH", "primary",
                          {"task": TASK, "base_sha": head})
        save_record(tower, lambda r: r["dispatch"].update(base_sha=head))
        commit_file(worktree, "tower-dsh/pilot/other.json", '{"v": 2}\n',
                    "out of scope change")
        new_head = git_ok(worktree, "rev-parse", "HEAD")
        save_record(tower, lambda r: r["dispatch"].update(base_sha=new_head))

    def record_sha_without_event(tower, worktree, mod):
        head = git_ok(worktree, "rev-parse", "HEAD")
        save_record(tower, lambda r: r["dispatch"].update(base_sha=head))

    def forged_completion(tower, worktree, mod):
        entry = {"task": TASK, "path": COMPLETION_PATH, "by": OWNER,
                 "reason": REASON, "decision": DECISION, "at": FIXED_TIME}
        save_record(tower, lambda r: r.update(completions=[entry]))
        commit_file(worktree, "tower-dsh/tools/helper.py", "helper = 1\n",
                    "hand-written record completion")

    def completion_backed(tower, worktree, mod):
        done = run_cli(tool, tower, "completion-add", "--task", TASK,
                       "--path", COMPLETION_PATH, "--by", OWNER,
                       "--reason", REASON, "--decision", DECISION)
        if done.returncode != 0:
            raise SystemExit(f"completion-add failed: {done.stdout}{done.stderr}")
        commit_file(worktree, "tower-dsh/tools/helper.py", "helper = 1\n",
                    "owner-backed completion")

    results: dict[str, dict] = {}
    results["deliver_matched"] = probe_deliver(
        base, tool, towerctl, "deliver_matched", matched)
    results["deliver_completion_backed"] = probe_deliver(
        base, tool, towerctl, "deliver_completion_backed", completion_backed)
    results["deliver_out_of_scope_head"] = probe_deliver(
        base, tool, towerctl, "deliver_out_of_scope_head", out_of_scope_head)
    results["deliver_record_sha_without_event"] = probe_deliver(
        base, tool, towerctl, "deliver_record_sha_without_event",
        record_sha_without_event)
    results["deliver_forged_completion"] = probe_deliver(
        base, tool, towerctl, "deliver_forged_completion", forged_completion)
    results["verify_tampered_base_sha"] = probe_verify(
        base, tool, towerctl, "verify_tampered_base_sha",
        dispatch_sha=BASE_SHA, record_sha=OTHER_SHA)
    results["verify_orphan_completion"] = probe_verify(
        base, tool, towerctl, "verify_orphan_completion",
        dispatch_sha=BASE_SHA, record_sha=BASE_SHA, orphan=True)

    problems: list[str] = []
    for name, result in results.items():
        problems += compare(name, result, EXPECTATIONS[args.label][name])

    print()
    print(f"tool={tool}")
    print(f"label={args.label}")
    print(f"deviation in tower counts: spec says 53/52, real tower is 54/53; "
          f"numbering only (PILOT-043 kept closed without an envelope).")
    if problems:
        print("RESULT: MISMATCH")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print(f"RESULT: OK ({len(results)} probes matched the '{args.label}' expectations)")
    if args.out:
        Path(args.out).write_text(render(results, problems, args.label, tool),
                                  encoding="utf-8")
    if not args.keep and base.exists():
        force_rmtree(base)
    return 1 if problems else 0


def render(results: dict, problems: list[str], label: str, tool: Path) -> str:
    lines = [f"# PILOT-054 record-layer probe ({label})",
             f"tool: {tool}",
             f"label: {label}",
             f"deviation: spec 53/52 vs real tower 54/53 (numbering only; "
             f"PILOT-043 stays closed with no envelope)"]
    for name, result in results.items():
        redacted = {key: result[key] for key in
                    ("exit", "record_status", "evidence_dir", "deliver_events",
                     "drift_kinds") if key in result}
        if "errors" in result:
            redacted["errors"] = result["errors"]
        if "scope_completions" in result:
            redacted["scope_completions"] = result["scope_completions"]
        lines.append(f"{name}: {json.dumps(redacted, ensure_ascii=False)}")
    lines.append("RESULT: MISMATCH" if problems else
                 f"RESULT: OK ({len(results)} probes matched '{label}' expectations)")
    for problem in problems:
        lines.append(f"  - {problem}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

