#!/usr/bin/env python3
"""PILOT-038 probe: the required marker on the new code, and old-vs-new.

Builds a throw-away kit (a git repository with a tower inside) under
``scratch/probe/``, uses the *new* ``towerctl.py`` to create a genuinely
required tower (``authority-require`` + ``authority-set``), then reproduces the
exact downgrade attack from the task card:

    删掉 state/AUTHORITY.json 并移除尾部唯一 AUTHORITY_SET（保留合法前缀）

and drives ``state-verify`` / ``authority-check`` / ``merge-check`` /
``merge --supervisor rogue`` against it with both the new tool and the ``main``
version extracted into ``scratch/old/towerctl.py``.

It also probes the ledger-append failure (``ledger/primary.jsonl`` replaced by
a directory) for ``authority-set`` and ``authority-require``.

Writes ``scratch/probe.txt`` (new code detail) and ``scratch/probe-old-code.txt``
(old vs new).  Read-only with respect to the real tower: every fixture lives
under ``scratch/``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
NEW_TOOL = TOWER / "tools" / "towerctl.py"
OLD_TOOL = WORKTREE / "scratch" / "old" / "towerctl.py"
SCRATCH = WORKTREE / "scratch"
PROBE_ROOT = SCRATCH / "probe"
TASK = "T-AUTH-001"
ENVELOPE = "ENV-AUTH-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/authority"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
AUTHORITY_FILE = "state/AUTHORITY.json"
POLICY_FILE = "shared/AUTHORITY_POLICY.json"
PRIMARY_ID = "ctl-primary"
SUPERVISOR_ID = "sup-A"

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


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def force_rmtree(path: Path) -> None:
    """Remove a tree that contains read-only git objects (Windows)."""
    if not path.exists():
        return

    def onexc(func, target, exc):
        os.chmod(target, 0o700)
        func(target)

    shutil.rmtree(path, onexc=onexc)


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TOWER / "tools"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def run_cli(tool: Path, root: Path, *args: str) -> dict:
    cp = run([sys.executable, "-B", str(tool), "--root", str(root), *args])
    payload = None
    if cp.stdout.strip():
        try:
            payload = json.loads(cp.stdout)
        except json.JSONDecodeError:
            payload = None
    return {"args": list(args), "exit": cp.returncode,
            "stdout": cp.stdout.strip(), "stderr": cp.stderr.strip(),
            "json": payload, "traceback": "Traceback" in (cp.stdout + cp.stderr)}


# ---------------------------------------------------------------- fixture ---
def git(kit: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(kit), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def build_fixture(dest: Path) -> Path:
    """A tower with one primary/supervision state and a merge branch."""
    force_rmtree(dest)
    kit = dest / "kit"
    root = kit / "tower-dsh"
    for directory in ("primary", "supervision/envelopes", "ledger", "shared",
                      f"tasks/{TASK}/evidence"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    proof = root / "tasks" / TASK / "evidence" / "proof.txt"
    proof.write_text("proof\n", encoding="utf-8")
    write_json(root / "tasks" / TASK / "record.json", {
        "schema": "tower/task@1", "id": TASK, "title": "authority required",
        "status": "accepted", "executor": "exec-a",
        "review": {"reviewer": "rev-a", "verdict": "PASS"},
        "evidence": [{"id": "E-001",
                      "path": f"tasks/{TASK}/evidence/proof.txt",
                      "sha256": sha256(proof.read_bytes()).hexdigest(),
                      "bytes": proof.stat().st_size, "at": FIXED_TIME}]})
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "phase": "TEST",
        "primary": {"id": PRIMARY_ID}, "owner": {"name": "mac"},
        "next_action": "probe"})
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "TEST", "supervisor": {"id": SUPERVISOR_ID}})
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})

    kit.mkdir(parents=True, exist_ok=True)
    assert git(kit, "init").returncode == 0
    assert git(kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode == 0
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / "merge-envelopes").mkdir()
    git(kit, "add", "-A")
    git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "base")
    git(kit, "checkout", "-b", BRANCH)
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    git(kit, "add", "-A")
    git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "implementation")
    implementation_head = git(kit, "rev-parse", "HEAD").stdout.strip()
    write_json(kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
    git(kit, "add", "-A")
    git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "envelope")
    git(kit, "checkout", "main")
    return root


def add_merge_files(root: Path) -> None:
    """Add the legacy envelope + WAITING queue entry used by merge-check/merge.

    Deliberately no lifecycle events: a pre-baseline envelope, exactly like
    037's merge-check fixture.  ``state-verify`` therefore reports it as
    ``envelope_unbacked``/``queue_unbacked``, which is why the downgrade probe
    runs ``state-verify`` *before* these files exist: the only authority drift
    left there is the one under test.
    """
    kit = root.parent
    implementation_head = git(kit, "rev-parse", f"{BRANCH}~1").stdout.strip()
    envelope_head = git(kit, "rev-parse", BRANCH).stdout.strip()
    write_json(root / "supervision" / "envelopes" / f"{ENVELOPE}.json", {
        "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
        "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
        "envelope_path": ENVELOPE_PATH,
        "implementation_head_sha": implementation_head,
        "envelope_head_sha": envelope_head, "status": "DRAFT"})
    write_json(root / "supervision" / "MERGE_QUEUE.json", {
        "schema": "tower/merge-queue@1",
        "entries": [{"envelope_id": ENVELOPE, "task": TASK, "branch": BRANCH,
                     "base": "main", "status": "WAITING",
                     "added_at": FIXED_TIME}]})


def drop_last_ledger_row(root: Path) -> dict:
    path = root / "ledger" / "primary.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    dropped = json.loads(rows[-1])
    body = "\n".join(rows[:-1])
    path.write_text(body + "\n" if body else "", encoding="utf-8")
    return dropped


def make_required_fixture(dest: Path) -> tuple[Path, dict]:
    """New tool creates a required tower, then both halves are removed."""
    root = build_fixture(dest)
    created = {
        "require": run_cli(NEW_TOOL, root, "authority-require", "--by", "mac",
                           "--decision", "D-PROBE"),
        "set": run_cli(NEW_TOOL, root, "authority-set", "--supervisor",
                       SUPERVISOR_ID, "--decision", "D-PROBE", "--by", "mac"),
    }
    # Force AUTHORITY_REQUIRED first, AUTHORITY_SET last, so dropping the tail
    # leaves a legal prefix chain (verify-ledger must stay at 0).
    (root / AUTHORITY_FILE).unlink()
    dropped = drop_last_ledger_row(root)
    assert dropped["type"] == "AUTHORITY_SET", dropped
    created["policy"] = read_json(root / POLICY_FILE)
    created["required_events"] = sum(
        1 for line in (root / "ledger" / "primary.jsonl")
        .read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("type") == "AUTHORITY_REQUIRED")
    return root, created


def make_ledger_dir_fixture(dest: Path) -> tuple[Path, bytes]:
    root = build_fixture(dest)
    ledger = root / "ledger" / "primary.jsonl"
    original = ledger.read_bytes()
    ledger.unlink()
    ledger.mkdir()
    return root, original


def summarise(result: dict, keys: tuple[str, ...]) -> dict:
    payload = result["json"] or {}
    out = {"exit": result["exit"], "traceback": result["traceback"],
           "single_json": bool(payload) and result["stdout"].startswith("{")}
    for key in keys:
        if key in payload:
            out[key] = payload[key]
    if payload.get("errors"):
        out["errors"] = payload["errors"][:3]
    return out


def merge_state(root: Path) -> dict:
    queue = read_json(root / "supervision" / "MERGE_QUEUE.json")
    ledger = root / "ledger" / "supervision.jsonl"
    text = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
    return {"queue_status": queue["entries"][0]["status"],
            "merge_start": "MERGE_START" in text,
            "merging": "MERGING" in text}


def drift_kinds(payload: dict) -> list[str]:
    return [item["kind"] for item in payload.get("drift", [])]


def main() -> int:
    for tool in (NEW_TOOL, OLD_TOOL):
        if not tool.is_file():
            print(f"missing tool: {tool}", file=sys.stderr)
            return 1
    force_rmtree(PROBE_ROOT)
    PROBE_ROOT.mkdir(parents=True)
    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text)
        lines.append(text)

    # ---------------------------------------------------------- new code ---
    say("PILOT-038 probe: new code (required marker, downgrade attack)")
    say(f"tool={NEW_TOOL}")
    required, created = make_required_fixture(PROBE_ROOT / "new-required")
    say(f"fixture: authority-require exit={created['require']['exit']} "
        f"already={created['require']['json'].get('already')} "
        f"repaired={created['require']['json'].get('repaired')}")
    say(f"fixture: authority-set exit={created['set']['exit']} "
        f"revision={created['set']['json'].get('revision')}")
    say(f"fixture: policy={json.dumps(created['policy'], ensure_ascii=False)}")
    say(f"fixture: AUTHORITY_REQUIRED events after truncation="
        f"{created['required_events']}")
    say("fixture: state/AUTHORITY.json deleted; trailing AUTHORITY_SET dropped")

    for report in (("verify-ledger", run_cli(NEW_TOOL, required, "verify-ledger")),
                   ("authority-check", run_cli(NEW_TOOL, required,
                                               "authority-check")),
                   ("state-verify", run_cli(NEW_TOOL, required, "state-verify"))):
        name, result = report
        payload = result["json"] or {}
        say(f"\nnew {name}: exit={result['exit']} traceback={result['traceback']}")
        if name == "authority-check":
            failed = [c for c in payload.get("checks", []) if not c["ok"]]
            say(f"  ok={payload.get('ok')} status={payload.get('status')} "
                f"requirement={payload.get('requirement')}")
            say(f"  failed_checks={json.dumps([c['name'] for c in failed])}")
            say(f"  detail={json.dumps([c['detail'] for c in failed], ensure_ascii=False)}")
        elif name == "state-verify":
            say(f"  ok={payload.get('ok')} drift={json.dumps(drift_kinds(payload))}")
            say(f"  skipped={json.dumps([s['reason'] for s in payload.get('skipped', [])])}")
        else:
            say(f"  errors={json.dumps(payload.get('errors'), ensure_ascii=False)}")

    add_merge_files(required)
    merge_check = run_cli(NEW_TOOL, required, "merge-check",
                          "--envelope", ENVELOPE)
    payload = merge_check["json"] or {}
    failed = payload.get("errors") or []
    say(f"\nnew merge-check: exit={merge_check['exit']} "
        f"traceback={merge_check['traceback']}")
    say(f"  ok={payload.get('ok')} failed_checks="
        f"{json.dumps([c['name'] for c in failed])}")
    say(f"  detail={json.dumps([c['detail'] for c in failed], ensure_ascii=False)}")

    merged = run_cli(NEW_TOOL, required, "merge", "--role", "supervisor",
                     "--supervisor", "rogue", "--envelope", ENVELOPE)
    say(f"\nnew merge --supervisor rogue: exit={merged['exit']} "
        f"traceback={merged['traceback']}")
    say(f"  errors={json.dumps((merged['json'] or {}).get('errors'), ensure_ascii=False)}")
    say(f"  {json.dumps(merge_state(required))}")

    # -------------------------------------------------- new append failure ---
    say("\nnew code: ledger/primary.jsonl replaced by a directory")
    append_root, original = make_ledger_dir_fixture(
        PROBE_ROOT / "new-append")
    set_fail = run_cli(NEW_TOOL, append_root, "authority-set", "--supervisor",
                       SUPERVISOR_ID, "--decision", "D-APPEND", "--by", "mac")
    check_after = run_cli(NEW_TOOL, append_root, "authority-check")
    say(f"authority-set: exit={set_fail['exit']} "
        f"traceback={set_fail['traceback']} "
        f"single_json={set_fail['stdout'].startswith('{')}")
    say(f"  errors={json.dumps((set_fail['json'] or {}).get('errors'), ensure_ascii=False)}")
    after_json = check_after["json"] or {}
    after_failed = [c["name"] for c in after_json.get("checks", []) if not c["ok"]]
    say(f"authority-check after failure: exit={check_after['exit']} "
        f"ok={after_json.get('ok')} status={after_json.get('status')} "
        f"failed_checks={json.dumps(after_failed)}")
    require_fail = run_cli(NEW_TOOL, append_root, "authority-require",
                           "--by", "mac", "--decision", "D-APPEND")
    check_after = run_cli(NEW_TOOL, append_root, "authority-check")
    say(f"authority-require: exit={require_fail['exit']} "
        f"traceback={require_fail['traceback']} "
        f"single_json={require_fail['stdout'].startswith('{')}")
    say(f"  errors={json.dumps((require_fail['json'] or {}).get('errors'), ensure_ascii=False)}")
    after_json = check_after["json"] or {}
    after_failed = [c["name"] for c in after_json.get("checks", []) if not c["ok"]]
    say(f"authority-check after failure: exit={check_after['exit']} "
        f"ok={after_json.get('ok')} status={after_json.get('status')} "
        f"failed_checks={json.dumps(after_failed)}")
    (append_root / "ledger" / "primary.jsonl").rmdir()
    (append_root / "ledger" / "primary.jsonl").write_bytes(original)
    repair_set = run_cli(NEW_TOOL, append_root, "authority-set", "--supervisor",
                         SUPERVISOR_ID, "--decision", "D-REPAIR", "--by", "mac")
    repair_require = run_cli(NEW_TOOL, append_root, "authority-require",
                             "--by", "mac", "--decision", "D-REPAIR")
    check_repaired = run_cli(NEW_TOOL, append_root, "authority-check")
    say(f"repair: authority-set exit={repair_set['exit']} "
        f"authority-require exit={repair_require['exit']} "
        f"authority-check exit={check_repaired['exit']} "
        f"ok={(check_repaired['json'] or {}).get('ok')} "
        f"status={(check_repaired['json'] or {}).get('status')} "
        f"requirement={(check_repaired['json'] or {}).get('requirement')}")

    (SCRATCH / "probe.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------------------------------------------- old vs new table ---
    old_lines: list[str] = []

    def old_say(text: str = "") -> None:
        print(text)
        old_lines.append(text)

    old_root, _ = make_required_fixture(PROBE_ROOT / "old-required")
    new_root = PROBE_ROOT / "new-required-compare"
    force_rmtree(new_root)
    # Rebuild a second identical required fixture so both tools start equal.
    new_root, _ = make_required_fixture(new_root)

    old_say("PILOT-038 old-vs-new probe")
    old_say(f"old tool={OLD_TOOL} (extracted from main)")
    old_say(f"new tool={NEW_TOOL}")
    old_say("fixture: required tower (authority-require + authority-set), then")
    old_say("         rm state/AUTHORITY.json + drop trailing AUTHORITY_SET")
    old_say("")

    # Phase 1 runs before the envelope/queue exist, so state-verify has no
    # unrelated unbacked-envelope drift and the authority row is the whole
    # difference between the two tools.
    state_commands = [
        ("verify-ledger", ("verify-ledger",), ("ok",)),
        ("authority-check", ("authority-check",), ("ok", "status")),
        ("state-verify", ("state-verify",), ("ok",)),
    ]
    for label, args, keys in state_commands:
        old_say(f"$ {label}")
        for name, tool, root in (("old", OLD_TOOL, old_root),
                                 ("new", NEW_TOOL, new_root)):
            result = run_cli(tool, root, *args)
            payload = result["json"] or {}
            entry = summarise(result, keys)
            if label == "state-verify":
                entry["drift"] = drift_kinds(payload)
                entry["skipped"] = [s["reason"] for s in payload.get("skipped", [])]
            old_say(f"  {name}: {json.dumps(entry, ensure_ascii=False)}")
        old_say("")

    add_merge_files(old_root)
    add_merge_files(new_root)
    merge_commands = [
        ("merge-check", ("merge-check", "--envelope", ENVELOPE), ("ok",)),
        ("merge --supervisor rogue", ("merge", "--role", "supervisor",
                                      "--supervisor", "rogue", "--envelope",
                                      ENVELOPE), ("ok", "status")),
    ]
    for label, args, keys in merge_commands:
        old_say(f"$ {label}")
        for name, tool, root in (("old", OLD_TOOL, old_root),
                                 ("new", NEW_TOOL, new_root)):
            result = run_cli(tool, root, *args)
            payload = result["json"] or {}
            entry = summarise(result, keys)
            if label == "merge-check":
                candidates = payload.get("errors") or payload.get("checks") or []
                entry["authority_checks"] = [
                    {"name": c["name"], "ok": c["ok"],
                     "detail": c.get("detail")}
                    for c in candidates if "authority" in c["name"]]
            if label.startswith("merge "):
                state = merge_state(root)
                entry["queue_status"] = state["queue_status"]
                entry["MERGE_START"] = state["merge_start"]
                entry["MERGING"] = state["merging"]
            old_say(f"  {name}: {json.dumps(entry, ensure_ascii=False)}")
        old_say("")

    # The old tool has authority-set but no authority-require: compare the
    # append failure for authority-set, and state that require is new.
    old_say("append failure: ledger/primary.jsonl replaced by a directory")
    for name, tool in (("old", OLD_TOOL), ("new", NEW_TOOL)):
        root, _ = make_ledger_dir_fixture(PROBE_ROOT / f"{name}-append-compare")
        result = run_cli(tool, root, "authority-set", "--supervisor",
                         SUPERVISOR_ID, "--decision", "D-APPEND", "--by", "mac")
        after = run_cli(tool, root, "authority-check")
        old_say(f"  {name} authority-set: exit={result['exit']} "
                f"traceback={result['traceback']} "
                f"single_json={result['stdout'].startswith('{')}")
        old_say(f"    stdout_head={result['stdout'][:160]!r}")
        old_say(f"    stderr_tail={result['stderr'].splitlines()[-3:]!r}")
        old_say(f"    authority-check: exit={after['exit']} "
                f"ok={(after['json'] or {}).get('ok')} "
                f"status={(after['json'] or {}).get('status')}")
    old_say("  old authority-require: command does not exist (PILOT-038 only)")
    old_say("  new authority-require on a directory ledger: covered above in "
            "probe.txt (clean exit 2, single JSON, required_unconfigured)")

    (SCRATCH / "probe-old-code.txt").write_text("\n".join(old_lines) + "\n",
                                                encoding="utf-8")
    print(f"\nwrote {SCRATCH / 'probe.txt'}")
    print(f"wrote {SCRATCH / 'probe-old-code.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
