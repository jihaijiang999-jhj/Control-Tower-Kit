#!/usr/bin/env python3
"""PILOT-037 CLI-level probe: authority state, new code vs ``main`` code.

Builds throw-away tower fixtures under ``scratch/tmp`` and replays the ten
acceptance scenarios against the worktree ``towerctl.py``.  It also extracts the
``main`` version of the tool into ``scratch/old/towerctl.py`` and runs the three
regression comparisons on the *same* fixtures:

* ``merge --supervisor rogue`` on a configured tower;
* ``state-verify`` after tampering with ``state/AUTHORITY.json``;
* ``state-verify`` after deleting ``state/AUTHORITY.json``.

Outputs (all under ``scratch/``): ``probe.txt`` and ``probe-old-code.txt``.

    python -B scratch/authority_probe.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
SCRATCH = WORKTREE / "scratch"
OLD_DIR = SCRATCH / "old"
OLD_CLI = OLD_DIR / "towerctl.py"
TMP = SCRATCH / "tmp" / "probe"
PROBE_OUT = SCRATCH / "probe.txt"
OLD_OUT = SCRATCH / "probe-old-code.txt"

TASK = "T-PROBE-001"
ENVELOPE = "ENV-PROBE-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/probe"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
PRIMARY_ID = "ctl-probe-primary"
SUPERVISOR_ID = "sup-phase2-pilot"
AUTHORITY_FILE = "state/AUTHORITY.json"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def run_cli(cli: Path, root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # The extracted ``main`` tool imports ``spec_coverage``/``spec_lint`` from
    # ``tools/``; its own directory is not the tower tools directory.
    env["PYTHONPATH"] = str(TOWER / "tools") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-B", str(cli), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


def parse(cp: subprocess.CompletedProcess):
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return None


def build_kit(base: Path) -> tuple[Path, Path, dict]:
    """A git kit (repository + tower) with a valid legacy envelope commit."""
    kit = base / "kit"
    root = kit / "tower-dsh"
    for directory in ("primary", "supervision/envelopes", "ledger",
                      f"tasks/{TASK}/evidence"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    proof = root / "tasks" / TASK / "evidence" / "proof.txt"
    proof.write_text("proof\n", encoding="utf-8")
    write_json(root / "tasks" / TASK / "record.json", {
        "schema": "tower/task@1",
        "id": TASK,
        "title": "authority probe",
        "status": "accepted",
        "executor": "exec-a",
        "review": {"reviewer": "rev-a", "verdict": "PASS"},
        "evidence": [{
            "id": "E-001",
            "path": f"tasks/{TASK}/evidence/proof.txt",
            "sha256": sha256(proof.read_bytes()).hexdigest(),
            "bytes": proof.stat().st_size,
            "at": FIXED_TIME,
        }],
    })
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1",
        "tower_id": "tower-dsh",
        "role": "primary",
        "phase": "PROBE",
        "primary": {"id": PRIMARY_ID},
        "owner": {"name": "mac"},
        "next_action": "probe",
    })
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1",
        "role": "supervision",
        "phase": "PROBE",
        "supervisor": {"id": SUPERVISOR_ID},
    })
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})

    def git(*args: str) -> subprocess.CompletedProcess:
        return run_git(kit, *args)

    def commit_all(message: str) -> str:
        assert git("add", "-A").returncode == 0
        cp = git("-c", "commit.gpgsign=false", "commit", "-m", message)
        assert cp.returncode == 0, cp.stderr
        return git("rev-parse", "HEAD").stdout.strip()

    kit.mkdir(parents=True, exist_ok=True)
    assert git("init").returncode == 0
    assert git("symbolic-ref", "HEAD", "refs/heads/main").returncode == 0
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / "merge-envelopes").mkdir()
    commit_all("base")
    assert git("checkout", "-b", BRANCH).returncode == 0
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    implementation = commit_all("implementation")
    write_json(kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
    envelope_head = commit_all("envelope")
    assert git("checkout", "main").returncode == 0
    heads = {"implementation": implementation, "envelope": envelope_head}
    return kit, root, heads


def write_legacy_envelope(root: Path, heads: dict) -> None:
    write_json(root / "supervision" / "envelopes" / f"{ENVELOPE}.json", {
        "schema": "tower/merge-envelope@1",
        "envelope_id": ENVELOPE,
        "task": TASK,
        "repository": "..",
        "branch": BRANCH,
        "base": "main",
        "envelope_path": ENVELOPE_PATH,
        "implementation_head_sha": heads["implementation"],
        "envelope_head_sha": heads["envelope"],
        "status": "DRAFT",
    })


def queue_entry(root: Path) -> None:
    write_json(root / "supervision" / "MERGE_QUEUE.json", {
        "schema": "tower/merge-queue@1",
        "entries": [{
            "envelope_id": ENVELOPE, "task": TASK, "branch": BRANCH,
            "base": "main", "status": "WAITING", "added_at": FIXED_TIME,
        }],
    })


def authority_events(root: Path) -> list[dict]:
    path = root / "ledger" / "primary.jsonl"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [json.loads(line) for line in text.splitlines()
            if line.strip() and json.loads(line).get("type") == "AUTHORITY_SET"]


def supervision_ledger(root: Path) -> str:
    path = root / "ledger" / "supervision.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def forge_authority_event(root: Path) -> None:
    """Append an AUTHORITY_SET row with correct seq/prev but a wrong hash."""
    path = root / "ledger" / "primary.jsonl"
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = rows[-1]
    forged = {
        "seq": last["seq"] + 1,
        "at": FIXED_TIME,
        "type": "AUTHORITY_SET",
        "actor": "primary",
        "payload": last["payload"],
        "prev_hash": last.get("hash") or "GENESIS",
        "hash": "f" * 64,
    }
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")


def summarize(cp: subprocess.CompletedProcess) -> dict:
    payload = parse(cp)
    summary = {"exit": cp.returncode}
    if payload is None:
        summary["stdout"] = cp.stdout.strip()
        summary["stderr"] = cp.stderr.strip()
        return summary
    summary["ok"] = payload.get("ok")
    if "errors" in payload:
        summary["errors"] = payload["errors"]
    for key in ("status", "revision", "merge_authority", "path"):
        if key in payload:
            summary[key] = payload[key]
    if "checks" in payload:
        summary["failed_checks"] = [c for c in payload["checks"] if not c["ok"]]
        summary["authority_checks"] = [c for c in payload["checks"]
                                       if "authority" in c["name"].lower()]
    if "drift" in payload:
        summary["drift"] = payload["drift"]
        summary["skipped"] = payload.get("skipped")
    return summary


def fmt(summary: dict) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)


def fresh(name: str) -> Path:
    base = TMP / name
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    return base


def set_authority(root: Path) -> subprocess.CompletedProcess:
    return run_cli(TCLI, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                   "--decision", "D-PILOT-037", "--by", "mac")


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    OLD_DIR.mkdir(parents=True, exist_ok=True)

    new_lines: list[str] = []
    old_lines: list[str] = []

    def record(lines: list[str], title: str, cp: subprocess.CompletedProcess,
               extra: str = "") -> None:
        lines.append(f"== {title} ==")
        lines.append(f"cmd: {cp.args}")
        lines.append(fmt(summarize(cp)))
        if extra:
            lines.append(extra)
        lines.append("")

    # -- extract the main tool -------------------------------------------
    show = subprocess.run(
        ["git", "-C", str(WORKTREE), "show",
         "main:tower-dsh/tools/towerctl.py"],
        capture_output=True)
    if show.returncode != 0:
        print(show.stderr.decode("utf-8", "replace"), file=sys.stderr)
        return 1
    OLD_CLI.write_bytes(show.stdout)
    new_lines.append(f"new tool: {TCLI}")
    old_lines.append(f"old tool: git -C {WORKTREE} show "
                     f"main:tower-dsh/tools/towerctl.py -> {OLD_CLI} "
                     f"({len(show.stdout)} bytes, sha256="
                     f"{sha256(show.stdout).hexdigest()})")
    old_lines.append("")

    # -- 1. authority-set happy path --------------------------------------
    base = fresh("01-set")
    _, root, _ = build_kit(base)
    cp = set_authority(root)
    extra = (f"file={AUTHORITY_FILE} exists={(root / AUTHORITY_FILE).exists()} "
             f"revision={read_json(root / AUTHORITY_FILE)['revision']} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 1: authority-set happy path", cp, extra)
    record(new_lines, "probe 1b: authority-check configured",
           run_cli(TCLI, root, "authority-check"))

    # -- 2. --by is not the owner ----------------------------------------
    base = fresh("02-by")
    _, root, _ = build_kit(base)
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                 "--decision", "D-X", "--by", "mallory")
    extra = (f"file_exists={(root / AUTHORITY_FILE).exists()} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 2: authority-set --by mallory", cp, extra)

    # -- 3. supervisor == primary.id --------------------------------------
    base = fresh("03-primary")
    _, root, _ = build_kit(base)
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", PRIMARY_ID,
                 "--decision", "D-X", "--by", "mac")
    extra = (f"file_exists={(root / AUTHORITY_FILE).exists()} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 3: authority-set --supervisor <primary.id>", cp,
           extra)

    # -- 4. supervisor is not the registered supervisor -------------------
    base = fresh("04-sup")
    _, root, _ = build_kit(base)
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", "sup-rogue",
                 "--decision", "D-X", "--by", "mac")
    extra = (f"file_exists={(root / AUTHORITY_FILE).exists()} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 4: authority-set --supervisor sup-rogue", cp, extra)

    # -- 5. tampered file --------------------------------------------------
    base = fresh("05-tamper")
    _, root, _ = build_kit(base)
    set_authority(root)
    state = read_json(root / AUTHORITY_FILE)
    state["merge_authority"] = "sup-rogue"
    write_json(root / AUTHORITY_FILE, state)
    record(new_lines, "probe 5a: authority-check after tamper",
           run_cli(TCLI, root, "authority-check"))
    record(new_lines, "probe 5b: state-verify after tamper",
           run_cli(TCLI, root, "state-verify"))

    # -- 6. deleted file, event present ------------------------------------
    base = fresh("06-missing")
    _, root, _ = build_kit(base)
    set_authority(root)
    queue_entry(root)
    (root / AUTHORITY_FILE).unlink()
    record(new_lines, "probe 6a: authority-check after delete",
           run_cli(TCLI, root, "authority-check"))
    record(new_lines, "probe 6b: state-verify after delete",
           run_cli(TCLI, root, "state-verify"))
    cp = run_cli(TCLI, root, "merge", "--role", "supervisor",
                 "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE)
    entry = read_json(root / "supervision" / "MERGE_QUEUE.json")["entries"][0]
    extra = (f"queue_status={entry['status']} "
             f"MERGE_START={'MERGE_START' in supervision_ledger(root)}")
    record(new_lines, "probe 6c: merge with event but no file", cp, extra)

    # -- 7. file without event ---------------------------------------------
    base = fresh("07-unbacked")
    _, root, _ = build_kit(base)
    write_json(root / AUTHORITY_FILE, {
        "schema": "tower/authority-state@1",
        "tower_id": "tower-dsh",
        "owner": "mac",
        "primary": {"id": PRIMARY_ID},
        "supervision": {"id": SUPERVISOR_ID},
        "merge_authority": SUPERVISOR_ID,
        "revision": 1,
        "set_by": "mac",
        "decision": "D-X",
        "set_at": FIXED_TIME,
    })
    record(new_lines, "probe 7a: authority-check with file only",
           run_cli(TCLI, root, "authority-check"))
    record(new_lines, "probe 7b: state-verify with file only",
           run_cli(TCLI, root, "state-verify"))

    # -- 8. configured tower pins the merge identity ----------------------
    base = fresh("08-pin")
    _, root, heads = build_kit(base)
    set_authority(root)
    record(new_lines, "probe 8a: merge --supervisor rogue",
           run_cli(TCLI, root, "merge", "--role", "supervisor",
                   "--supervisor", "rogue", "--envelope", ENVELOPE))
    record(new_lines, "probe 8b: merge --supervisor <pin> (passes identity)",
           run_cli(TCLI, root, "merge", "--role", "supervisor",
                   "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE))
    write_legacy_envelope(root, heads)
    queue_entry(root)
    record(new_lines, "probe 8c: merge-check configured",
           run_cli(TCLI, root, "merge-check", "--envelope", ENVELOPE))

    # -- 9. legacy tower ---------------------------------------------------
    base = fresh("09-legacy")
    _, root, heads = build_kit(base)
    write_legacy_envelope(root, heads)
    queue_entry(root)
    record(new_lines, "probe 9a: merge-check legacy",
           run_cli(TCLI, root, "merge-check", "--envelope", ENVELOPE))
    record(new_lines, "probe 9b: authority-check legacy",
           run_cli(TCLI, root, "authority-check"))

    # -- 10. re-run repairs an event without a file -----------------------
    base = fresh("10-rerun")
    _, root, _ = build_kit(base)
    set_authority(root)
    (root / AUTHORITY_FILE).unlink()
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                 "--decision", "D-PILOT-037-RERUN", "--by", "mac")
    extra = (f"revision={read_json(root / AUTHORITY_FILE)['revision']} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 10a: authority-set re-run repair", cp, extra)
    record(new_lines, "probe 10b: authority-check after repair",
           run_cli(TCLI, root, "authority-check"))

    # -- 11. every field bound, not just the five ids ---------------------
    base = fresh("11-fields")
    _, root, _ = build_kit(base)
    assert set_authority(root).returncode == 0
    tampered = read_json(root / AUTHORITY_FILE)
    tampered["decision"] = "D-EVIL"
    write_json(root / AUTHORITY_FILE, tampered)
    record(new_lines, "probe 11a: authority-check after decision tamper",
           run_cli(TCLI, root, "authority-check"))
    record(new_lines, "probe 11b: state-verify after decision tamper",
           run_cli(TCLI, root, "state-verify"))
    tampered = read_json(root / AUTHORITY_FILE)
    tampered["decision"] = "D-PILOT-037"
    tampered["tower_id"] = "tower-evil"
    write_json(root / AUTHORITY_FILE, tampered)
    record(new_lines, "probe 11c: state-verify after tower_id tamper",
           run_cli(TCLI, root, "state-verify"))

    # -- 12. revision type hole (bool/float/str/negative) -----------------
    base = fresh("12-revision")
    _, root, _ = build_kit(base)
    assert set_authority(root).returncode == 0
    original = read_json(root / AUTHORITY_FILE)
    for index, value in enumerate((True, 1.0, "1", -1)):
        tampered = dict(original)
        tampered["revision"] = value
        write_json(root / AUTHORITY_FILE, tampered)
        record(new_lines, f"probe 12.{index + 1}: revision={value!r}",
               run_cli(TCLI, root, "authority-check"))
        record(new_lines, f"probe 12.{index + 1}b: state-verify revision="
                          f"{value!r}",
               run_cli(TCLI, root, "state-verify"))
    write_json(root / AUTHORITY_FILE, original)

    # -- 13. empty --decision ---------------------------------------------
    base = fresh("13-decision")
    _, root, _ = build_kit(base)
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                 "--decision", "", "--by", "mac")
    extra = (f"file_exists={(root / AUTHORITY_FILE).exists()} "
             f"authority_events={len(authority_events(root))}")
    record(new_lines, "probe 13: authority-set --decision ''", cp, extra)

    # -- 14. a write failure is one JSON, exit 2, and no event ------------
    base = fresh("14-writefail")
    _, root, _ = build_kit(base)
    (root / "state" / "AUTHORITY.json").mkdir(parents=True)
    cp = run_cli(TCLI, root, "authority-set", "--supervisor", SUPERVISOR_ID,
                 "--decision", "D-X", "--by", "mac")
    extra = (f"authority_events={len(authority_events(root))} "
             f"traceback={'Traceback' in (cp.stdout + cp.stderr)} "
             f"tmp_left={(root / 'state' / 'AUTHORITY.json.tmp').exists()}")
    record(new_lines, "probe 14: authority-set with a directory in the way",
           cp, extra)

    # -- 15. forged AUTHORITY_SET row + legacy envelope -------------------
    base = fresh("15-forged")
    _, root, heads = build_kit(base)
    assert set_authority(root).returncode == 0
    forge_authority_event(root)
    write_legacy_envelope(root, heads)
    queue_entry(root)
    record(new_lines, "probe 15a: authority-check on a forged chain",
           run_cli(TCLI, root, "authority-check"))
    cp = run_cli(TCLI, root, "merge", "--role", "supervisor",
                 "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE)
    entry = read_json(root / "supervision" / "MERGE_QUEUE.json")["entries"][0]
    extra = (f"queue_status={entry['status']} "
             f"MERGE_START={'MERGE_START' in supervision_ledger(root)}")
    record(new_lines, "probe 15b: merge legacy envelope on forged chain", cp,
           extra)

    # =====================================================================
    # old-code comparisons on the same configured fixtures
    # =====================================================================
    old_lines.append("All fixtures are the same bytes; only the tool differs.")
    old_lines.append("")

    # A. configured tower, merge --supervisor rogue
    base = fresh("old-a")
    _, root_a, _ = build_kit(base)
    assert set_authority(root_a).returncode == 0
    new_a = run_cli(TCLI, root_a, "merge", "--role", "supervisor",
                    "--supervisor", "rogue", "--envelope", ENVELOPE)
    old_a = run_cli(OLD_CLI, root_a, "merge", "--role", "supervisor",
                    "--supervisor", "rogue", "--envelope", ENVELOPE)
    old_lines.append("== A. configured tower: merge --supervisor rogue ==")
    old_lines.append(f"cmd: {old_a.args}")
    old_lines.append("--- old (main) ---")
    old_lines.append(fmt(summarize(old_a)))
    old_lines.append("--- new (worktree) ---")
    old_lines.append(fmt(summarize(new_a)))
    old_lines.append(
        "conclusion: old never mentions the registered merge authority; it "
        "continues to the envelope stage. new rejects with "
        "'merge authority mismatch' before reading the envelope.")
    old_lines.append("")

    # B. tampered state/AUTHORITY.json, state-verify
    base = fresh("old-b")
    _, root_b, _ = build_kit(base)
    assert set_authority(root_b).returncode == 0
    tampered = read_json(root_b / AUTHORITY_FILE)
    tampered["merge_authority"] = "sup-rogue"
    write_json(root_b / AUTHORITY_FILE, tampered)
    old_b = run_cli(OLD_CLI, root_b, "state-verify")
    new_b = run_cli(TCLI, root_b, "state-verify")
    old_lines.append("== B. tampered state/AUTHORITY.json: state-verify ==")
    old_lines.append(f"cmd: {old_b.args}")
    old_lines.append("--- old (main) ---")
    old_lines.append(fmt(summarize(old_b)))
    old_lines.append("--- new (worktree) ---")
    old_lines.append(fmt(summarize(new_b)))
    old_lines.append(
        "conclusion: old has no authority audit (drift []). new reports "
        "authority_mismatch with the pinned vs file merge_authority.")
    old_lines.append("")

    # C. deleted state/AUTHORITY.json, state-verify
    base = fresh("old-c")
    _, root_c, _ = build_kit(base)
    assert set_authority(root_c).returncode == 0
    (root_c / AUTHORITY_FILE).unlink()
    old_c = run_cli(OLD_CLI, root_c, "state-verify")
    new_c = run_cli(TCLI, root_c, "state-verify")
    old_lines.append("== C. deleted state/AUTHORITY.json (event present): "
                     "state-verify ==")
    old_lines.append(f"cmd: {old_c.args}")
    old_lines.append("--- old (main) ---")
    old_lines.append(fmt(summarize(old_c)))
    old_lines.append("--- new (worktree) ---")
    old_lines.append(fmt(summarize(new_c)))
    old_lines.append(
        "conclusion: old has no authority audit (drift []). new reports "
        "authority_missing, so an event without its file fails closed.")
    old_lines.append("")

    # D. forged AUTHORITY_SET row + legacy envelope, merge
    base = fresh("old-d")
    _, root_d_old, heads_d_old = build_kit(base)
    assert set_authority(root_d_old).returncode == 0
    forge_authority_event(root_d_old)
    write_legacy_envelope(root_d_old, heads_d_old)
    queue_entry(root_d_old)
    old_d = run_cli(OLD_CLI, root_d_old, "merge", "--role", "supervisor",
                    "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE)
    old_d_entry = read_json(
        root_d_old / "supervision" / "MERGE_QUEUE.json")["entries"][0]["status"]
    old_d_merged = "MERGE_START" in supervision_ledger(root_d_old)

    base = fresh("old-d-new")
    _, root_d_new, heads_d_new = build_kit(base)
    assert set_authority(root_d_new).returncode == 0
    forge_authority_event(root_d_new)
    write_legacy_envelope(root_d_new, heads_d_new)
    queue_entry(root_d_new)
    new_d = run_cli(TCLI, root_d_new, "merge", "--role", "supervisor",
                    "--supervisor", SUPERVISOR_ID, "--envelope", ENVELOPE)
    new_d_entry = read_json(
        root_d_new / "supervision" / "MERGE_QUEUE.json")["entries"][0]["status"]
    new_d_merged = "MERGE_START" in supervision_ledger(root_d_new)

    old_lines.append("== D. forged AUTHORITY_SET (bad hash) + legacy envelope: "
                     "merge ==")
    old_lines.append(f"cmd: {old_d.args}")
    old_lines.append("--- old (main) ---")
    old_lines.append(fmt(summarize(old_d)))
    old_lines.append(f"queue_status={old_d_entry} "
                     f"MERGE_START={old_d_merged}")
    old_lines.append("--- new (worktree) ---")
    old_lines.append(fmt(summarize(new_d)))
    old_lines.append(f"queue_status={new_d_entry} "
                     f"MERGE_START={new_d_merged}")
    old_lines.append(
        "conclusion: old trusts the forged AUTHORITY_SET row (no authority "
        "audit, legacy envelope skips the chain check) and merges. new "
        "verifies the primary chain for any AUTHORITY_SET and reports "
        "'primary ledger chain broken', leaving the entry WAITING with no "
        "MERGE_START.")

    PROBE_OUT.write_text("\n".join(new_lines) + "\n", encoding="utf-8",
                         newline="\n")
    OLD_OUT.write_text("\n".join(old_lines) + "\n", encoding="utf-8",
                       newline="\n")
    print(f"wrote {PROBE_OUT}")
    print(f"wrote {OLD_OUT}")
    print(f"wrote {OLD_CLI}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
