#!/usr/bin/env python3
"""PILOT-039 probe: drive one ``towerctl.py`` against throw-away fixtures.

The same script is run twice by the executor:

    python -B scratch/authority_hardening_probe.py \
        --tcli tower-dsh/tools/towerctl.py --label NEW > scratch/probe.txt
    PYTHONPATH=tower-dsh/tools python -B scratch/authority_hardening_probe.py \
        --tcli scratch/old/towerctl.py --label OLD > scratch/probe-old-code.txt

(``PYTHONPATH`` is only needed for the main-version copy: the old file imports
``spec_coverage`` from its sibling module directory, which the copy in
``scratch/old`` does not have.)

Sections:

A. policy <-> event isomorphism.  Build a required tower, then rewrite
   ``set_by`` in ``shared/AUTHORITY_POLICY.json`` and report what
   ``authority-check``, ``state-verify``, ``merge-check`` and ``merge`` do.
B. pre-merge chain.  Build a legacy (no baseline) envelope, queue it, append a
   fake primary row whose ``seq``/``prev_hash`` are legal and whose hash is
   wrong, then report ``verify-ledger``/``merge`` and the post-attempt queue,
   envelope and supervision ledger.
C. cross-lock.  Launch three concurrent ``authority-set`` writers and report
   the revisions, the AUTHORITY_SET count, ledger/check verdicts and residue.

Everything is created under ``scratch/probe-tmp`` and deleted afterwards; the
real tower is never touched.
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
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER_ROOT = WORKTREE / "tower-dsh"
DEFAULT_TCLI = TOWER_ROOT / "tools" / "towerctl.py"
PROBE_TMP = WORKTREE / "scratch" / "probe-tmp"

TASK = "T-PROBE-039"
ENVELOPE = "ENV-PROBE-039"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/probe-039"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
SUPERVISOR = "sup-A"

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


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


def short(value, limit: int = 320) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "..."


class Kit:
    def __init__(self, tcli: Path, label: str) -> None:
        self.tcli = tcli
        self.label = label
        PROBE_TMP.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.mkdtemp(prefix="kit-", dir=str(PROBE_TMP))
        self.kit = Path(self._tmp) / "kit"
        self.root = self.kit / "tower-dsh"
        self.build()

    def cleanup(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- fixture ---------------------------------------------------------
    def build(self) -> None:
        for directory in ("primary", "supervision/envelopes", "ledger",
                          "shared", f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": TASK,
            "status": "accepted", "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK}/evidence/proof.txt",
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "bytes": proof.stat().st_size, "at": FIXED_TIME,
            }],
        })
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "PROBE",
            "primary": {"id": "ctl-primary"}, "owner": {"name": "mac"},
            "next_action": "probe",
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "PROBE", "supervisor": {"id": SUPERVISOR},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.init_repo()

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        assert run_git(self.kit, "init").returncode == 0
        assert run_git(self.kit, "symbolic-ref", "HEAD",
                       "refs/heads/main").returncode == 0
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / "merge-envelopes").mkdir()
        self.commit_all("base")
        assert run_git(self.kit, "checkout", "-b", BRANCH).returncode == 0
        (self.kit / "feature.txt").write_text("implementation\n",
                                               encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.envelope_head = self.commit_all("envelope")
        assert run_git(self.kit, "checkout", "main").returncode == 0

    def commit_all(self, message: str) -> str:
        run_git(self.kit, "add", "-A")
        cp = run_git(self.kit, "-c", "commit.gpgsign=false", "commit",
                     "-m", message)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    # -- CLI -------------------------------------------------------------
    def env(self) -> dict:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(self.tcli), "--root", str(self.root),
             *args],
            capture_output=True, text=True, encoding="utf-8", env=self.env())

    def popen(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-B", str(self.tcli), "--root", str(self.root),
             *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=self.env())

    def cli_json(self, *args: str) -> tuple[int, dict | None, str]:
        cp = self.cli(*args)
        try:
            return cp.returncode, json.loads(cp.stdout), cp.stderr
        except json.JSONDecodeError:
            return cp.returncode, None, (cp.stdout + cp.stderr)[:400]

    # -- domain helpers --------------------------------------------------
    def set_ok(self) -> None:
        code, payload, err = self.cli_json("authority-set",
                                           "--supervisor", SUPERVISOR,
                                           "--decision", "D-X", "--by", "mac")
        print(f"  authority-set                 rc={code} revision="
              f"{(payload or {}).get('revision')} {short(err or '')}")

    def require_ok(self) -> None:
        code, payload, err = self.cli_json("authority-require", "--by", "mac",
                                           "--decision", "D-SET")
        print(f"  authority-require             rc={code} repaired="
              f"{(payload or {}).get('repaired')} {short(err or '')}")

    def policy_path(self) -> Path:
        return self.root / "shared" / "AUTHORITY_POLICY.json"

    def policy(self) -> dict:
        return read_json(self.policy_path())

    def write_policy(self, data: dict) -> None:
        write_json(self.policy_path(), data)

    def ledger_events(self, name: str = "primary") -> list[dict]:
        path = self.root / "ledger" / f"{name}.jsonl"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def write_legacy_envelope(self) -> None:
        write_json(self.root / "supervision" / "envelopes"
                   / f"{ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.envelope_head, "status": "DRAFT",
        })

    def write_new_style_envelope(self) -> None:
        self.write_legacy_envelope()
        path = self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
        data = read_json(path)
        data.update({"tests_baseline": 1, "tower_tests_baseline": 1})
        write_json(path, data)

    def write_waiting_entry(self) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE, "task": TASK,
                         "branch": BRANCH, "base": "main",
                         "status": "WAITING", "added_at": FIXED_TIME}],
        })

    def queue_status(self) -> str:
        entries = read_json(self.root / "supervision"
                            / "MERGE_QUEUE.json")["entries"]
        return entries[0]["status"] if entries else "(empty)"

    def envelope_status(self) -> str:
        path = self.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
        return read_json(path).get("status") if path.exists() else "(missing)"

    def supervision_ledger_text(self) -> str:
        path = self.root / "ledger" / "supervision.jsonl"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def forge_row(self, name: str = "primary") -> None:
        rows = self.ledger_events(name)
        seq = max((event.get("seq", 0) for event in rows), default=0) + 1
        prev = rows[-1]["hash"] if rows else "GENESIS"
        event = {"seq": seq, "at": FIXED_TIME, "type": "FORGED",
                 "actor": "forger", "payload": {"forged": True},
                 "prev_hash": prev, "hash": "0" * 64}
        with (self.root / "ledger" / f"{name}.jsonl").open(
                "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"  forged {name} row             seq={seq} prev_hash="
              f"{prev[:12]}... hash=000...000 (wrong)")


def header(label: str, section: str) -> None:
    print()
    print(f"=== [{label}] {section} ===")


def section_a(kit: Kit, label: str) -> None:
    header(label, "A. policy <-> event isomorphism")
    kit.set_ok()
    kit.require_ok()
    required = [event for event in kit.ledger_events()
                if event.get("type") == "AUTHORITY_REQUIRED"]
    print(f"  policy == last event payload  "
          f"{required and required[-1]['payload'] == kit.policy()}")
    for tag in ("intact", "tampered"):
        if tag == "tampered":
            data = dict(kit.policy())
            data["set_by"] = "mallory"
            kit.write_policy(data)
            print("  policy rewritten:            set_by 'mac' -> 'mallory'")
        code, check, err = kit.cli_json("authority-check")
        print(f"  authority-check [{tag}]        rc={code} ok="
              f"{(check or {}).get('ok')} status={(check or {}).get('status')}"
              f" {short(err or '')}")
        if check and not check.get("ok"):
            print(f"    check errors:              {short(check['checks'])}")
        code, state, err = kit.cli_json("state-verify")
        kinds = [item.get("kind") for item in (state or {}).get("drift", [])]
        print(f"  state-verify [{tag}]           rc={code} drift={kinds}"
              f" {short(err or '')}")

    kit.write_legacy_envelope()
    kit.write_waiting_entry()
    code, merge_check, err = kit.cli_json("merge-check", "--envelope", ENVELOPE)
    failed = [item.get("name") for item in (merge_check or {}).get("errors", [])]
    print(f"  merge-check (tampered)        rc={code} ok="
          f"{(merge_check or {}).get('ok')} failed={failed}")
    code, merged, err = kit.cli_json("merge", "--role", "supervisor",
                                     "--supervisor", SUPERVISOR, "--envelope",
                                     ENVELOPE)
    print(f"  merge (tampered)              rc={code} ok="
          f"{(merged or {}).get('ok')} errors="
          f"{short((merged or {}).get('errors', err))}")
    print(f"  queue / envelope after merge  {kit.queue_status()} / "
          f"{kit.envelope_status()}")

    data = dict(kit.policy())
    data["set_by"] = "mac"
    kit.write_policy(data)
    code, check, err = kit.cli_json("authority-check")
    print(f"  policy restored               authority-check rc={code} ok="
          f"{(check or {}).get('ok')}")


def section_b(kit: Kit, label: str) -> None:
    header(label, "B. merge precondition: forged primary row, legacy envelope")
    kit.write_legacy_envelope()
    kit.write_waiting_entry()
    kit.forge_row("primary")

    code, verify, err = kit.cli_json("verify-ledger")
    print(f"  verify-ledger                 rc={code} first_error="
          f"{short(((verify or {}).get('errors') or [''])[0])}")
    before_queue = read_json(kit.root / "supervision" / "MERGE_QUEUE.json")
    before_envelope = read_json(kit.root / "supervision" / "envelopes"
                                / f"{ENVELOPE}.json")
    code, merged, err = kit.cli_json("merge", "--role", "supervisor",
                                     "--supervisor", SUPERVISOR,
                                     "--envelope", ENVELOPE)
    print(f"  merge                         rc={code} ok="
          f"{(merged or {}).get('ok')} status="
          f"{(merged or {}).get('status')} errors="
          f"{short((merged or {}).get('errors', err))}")
    print(f"  queue status after attempt    {kit.queue_status()}")
    print(f"  envelope status after attempt {kit.envelope_status()}")
    print(f"  queue bytes unchanged         "
          f"{read_json(kit.root / 'supervision' / 'MERGE_QUEUE.json') == before_queue}")
    print(f"  envelope bytes unchanged      "
          f"{read_json(kit.root / 'supervision' / 'envelopes' / f'{ENVELOPE}.json') == before_envelope}")
    supervision = kit.supervision_ledger_text()
    print(f"  MERGE_START written           {'MERGE_START' in supervision}")
    print(f"  MERGING written               {'MERGING' in supervision}")


def section_c(kit: Kit, label: str) -> None:
    header(label, "C. cross-lock: 3 concurrent authority-set writers x 2 rounds")
    codes: list[int] = []
    tracebacks = 0
    for round_no in range(2):
        processes = [kit.popen("authority-set", "--supervisor", SUPERVISOR,
                               "--decision", "D-X", "--by", "mac")
                     for _ in range(3)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=180)
            codes.append(process.returncode)
            if "Traceback" in stdout + stderr:
                tracebacks += 1
            try:
                payload = json.loads(stdout)
                print(f"  round {round_no + 1} writer rc={process.returncode} "
                      f"ok={payload.get('ok')} revision="
                      f"{payload.get('revision')} errors="
                      f"{short(payload.get('errors'), 200)}")
            except json.JSONDecodeError:
                print(f"  round {round_no + 1} writer rc={process.returncode} "
                      f"non-JSON stdout={short(stdout)}")
    events = [event for event in kit.ledger_events()
              if event.get("type") == "AUTHORITY_SET"]
    revisions = [event.get("payload", {}).get("revision") for event in events]
    successes = sum(1 for code in codes if code == 0)
    print(f"  exit codes                    {codes}")
    print(f"  tracebacks                    {tracebacks}")
    print(f"  successes / events            {successes} / {len(events)}")
    print(f"  revisions in ledger order     {revisions}")
    print(f"  unique and increasing         "
          f"{revisions == list(range(1, len(revisions) + 1))}")
    code, report, err = kit.cli_json("verify-ledger")
    print(f"  verify-ledger                 rc={code} ok="
          f"{(report or {}).get('ok')} errors="
          f"{short((report or {}).get('errors', err))}")
    code, check, err = kit.cli_json("authority-check")
    print(f"  authority-check               rc={code} ok="
          f"{(check or {}).get('ok')}")
    lock = kit.root / "state" / ".authority.lock"
    tmp = sorted(path.name for path in kit.root.rglob("*.tmp"))
    print(f"  .authority.lock residue       {lock.exists()}")
    print(f"  .tmp residue                  {tmp}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tcli", default=str(DEFAULT_TCLI))
    parser.add_argument("--label", default="NEW")
    args = parser.parse_args(argv)
    tcli = Path(args.tcli)
    if not tcli.is_absolute():
        tcli = (WORKTREE / tcli).resolve()
    if not tcli.exists():
        print(f"towerctl not found: {tcli}", file=sys.stderr)
        return 2
    print(f"PROBE label={args.label}")
    print(f"towerctl={tcli}")
    print(f"worktree={WORKTREE}")
    kits = []
    try:
        for section in (section_a, section_b, section_c):
            kit = Kit(tcli, args.label)
            kits.append(kit)
            section(kit, args.label)
    finally:
        for kit in kits:
            kit.cleanup()
        shutil.rmtree(PROBE_TMP, ignore_errors=True)
    print()
    print("PROBE DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
