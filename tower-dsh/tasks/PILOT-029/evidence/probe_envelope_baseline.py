"""PILOT-029 probe: reject envelope-new without both count baselines.

Builds a throwaway tower under %TEMP% (never the real tower), exercises the
rejection paths and the acceptance path, and prints the exact CLI output plus
proof that a rejected call left no trace.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TCLI = Path(sys.argv[1]).resolve()
TASK = "T-PROBE-029"
ENVELOPE = "ENV-PROBE-029"
BRANCH = "feature/probe"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def wj(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, **GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, **GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, "-B", str(TCLI), "--root", str(root),
                           *args], capture_output=True, text=True,
                          encoding="utf-8", env=env)


def ledger_text(root: Path) -> str:
    path = root / "ledger" / "supervision.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def snapshot(root: Path) -> dict:
    envelopes = root / "supervision" / "envelopes"
    return {
        "envelopes": sorted(p.name for p in envelopes.iterdir()),
        "supervision_ledger": ledger_text(root),
        "record": (root / "tasks" / TASK / "record.json").read_text(encoding="utf-8"),
        "queue": (root / "supervision" / "MERGE_QUEUE.json").read_text(encoding="utf-8"),
    }


def base_payload(head: str) -> dict:
    return {
        "schema": "tower/merge-envelope@1",
        "envelope_id": ENVELOPE,
        "task": TASK,
        "repository": "..",
        "branch": BRANCH,
        "base": "main",
        "envelope_path": ENVELOPE_PATH,
        "implementation_head_sha": head,
        "tests_baseline": 1,
        "tower_tests_baseline": 1,
    }


def reject_case(root: Path, label: str, payload: dict) -> bool:
    wj(root / "envelope.json", payload)
    before = snapshot(root)
    cp = cli(root, "envelope-new", "--task", TASK,
             "--file", str(root / "envelope.json"))
    after = snapshot(root)
    blob = cp.stdout + cp.stderr
    names_both = "tests_baseline" in blob and "tower_tests_baseline" in blob
    no_file = not (root / "supervision" / "envelopes" / f"{ENVELOPE}.json").exists()
    no_event = "ENVELOPE_NEW" not in ledger_text(root)
    unchanged = before == after
    print(f"\n### {label}")
    print(f"$ towerctl envelope-new --task {TASK} --file envelope.json")
    print(f"exit={cp.returncode}")
    print(cp.stdout.rstrip() or "(no stdout)")
    if cp.stderr.strip():
        print("stderr:", cp.stderr.strip())
    print(f"PROOF exit==2: {cp.returncode == 2}")
    print(f"PROOF error names both fields: {names_both}")
    print(f"PROOF no supervision/envelopes/{ENVELOPE}.json: {no_file}")
    print(f"PROOF ledger has no ENVELOPE_NEW: {no_event}")
    print(f"PROOF record/queue/ledger bytes unchanged: {unchanged}")
    return all([cp.returncode == 2, names_both, no_file, no_event, unchanged])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="pilot029-probe-"))
    kit = tmp / "kit"
    root = kit / "tower-dsh"
    for d in ("primary", "supervision/envelopes", "ledger", f"tasks/{TASK}/evidence"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    proof = root / "tasks" / TASK / "evidence" / "proof.txt"
    proof.write_text("proof\n", encoding="utf-8")
    wj(root / "tasks" / TASK / "record.json", {
        "schema": "tower/task@1", "id": TASK, "title": "probe",
        "status": "accepted", "executor": "exec-a",
        "review": {"reviewer": "rev-a", "verdict": "PASS"},
        "evidence": [{"id": "E-001", "path": f"tasks/{TASK}/evidence/proof.txt",
                      "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                      "bytes": proof.stat().st_size,
                      "at": "2026-10-22T00:00:00+08:00"}],
    })
    wj(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "primary": {"id": "ctl-probe"},
        "owner": {"name": "mac"}, "phase": "TEST"})
    wj(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "TEST", "supervisor": {"id": "sup-probe"}})
    wj(root / "supervision" / "MERGE_QUEUE.json",
       {"schema": "tower/merge-queue@1", "entries": []})
    kit.mkdir(parents=True, exist_ok=True)
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    (kit / "merge-envelopes").mkdir()
    commit(kit, "base")
    git(kit, "checkout", "-b", BRANCH)
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    head = commit(kit, "implementation")
    wj(kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
    commit(kit, "envelope")
    git(kit, "checkout", "main")

    print(f"TEMP TOWER: {root}")
    print(f"towerctl: {TCLI}")
    ok = True

    missing = base_payload(head)
    del missing["tests_baseline"]
    ok &= reject_case(root, "missing tests_baseline", missing)

    missing = base_payload(head)
    del missing["tower_tests_baseline"]
    ok &= reject_case(root, "missing tower_tests_baseline", missing)

    for field in ("tests_baseline", "tower_tests_baseline"):
        for bad in (0, -1, True, "2", 1.0):
            payload = base_payload(head)
            payload[field] = bad
            ok &= reject_case(root, f"{field} = {bad!r}", payload)

    # acceptance
    wj(root / "envelope.json", base_payload(head))
    before = ledger_text(root)
    cp = cli(root, "envelope-new", "--task", TASK,
             "--file", str(root / "envelope.json"))
    envelope = root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
    created = json.loads(envelope.read_text(encoding="utf-8")) if envelope.exists() else {}
    events = [json.loads(line) for line in ledger_text(root).splitlines() if line.strip()]
    new_events = [e for e in events if e.get("type") == "ENVELOPE_NEW"]
    print("\n### valid tests_baseline=1 / tower_tests_baseline=1")
    print(f"$ towerctl envelope-new --task {TASK} --file envelope.json")
    print(f"exit={cp.returncode}")
    print(cp.stdout.rstrip() or "(no stdout)")
    print(f"PROOF exit==0: {cp.returncode == 0}")
    print(f"PROOF DRAFT file written: {envelope.exists()} status={created.get('status')!r}")
    print(f"PROOF ENVELOPE_NEW events: {len(new_events)} "
          f"(envelope={[e['payload'].get('envelope') for e in new_events]})")
    ok &= cp.returncode == 0 and created.get("status") == "DRAFT" and len(new_events) == 1

    print(f"\nPROBE RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
