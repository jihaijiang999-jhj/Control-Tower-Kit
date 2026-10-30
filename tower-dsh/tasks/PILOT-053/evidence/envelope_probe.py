#!/usr/bin/env python3
"""Envelope-recovery probe for PILOT-053 (old-code vs new-code comparison).

The probe builds throw-away towers and drives the CLI under test through
``subprocess``.  It is deliberately independent of the unit-test fixtures so it
can be pointed at *either* implementation::

    python scratch/envelope_probe.py --towerctl tower-dsh/tools/towerctl.py --label new
    python scratch/envelope_probe.py --towerctl scratch/old/towerctl.py --label old

Scenarios:

A. normal first envelope: envelope-new (DRAFT) -> queue-add -> merge.
B. failed PR merge (MERGE_BLOCKED) -> re-envelope -> second merge -> state-verify.
C. re-envelope of a still-DRAFT envelope -> merge.
D. re-envelope of a MERGED envelope.
E. replay unit: repeated ENVELOPE_NEW folding and illegal transitions.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TASK = "TEST-PROBE-001"
ENVELOPE = "ENV-TEST-PROBE-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BASE = "main"
BRANCH = "feature/probe"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}

# ``towerctl`` imports its sibling helpers (``spec_coverage``/``spec_lint``);
# both the subprocess runs and the replay import resolve them from here, so the
# probe can be pointed at a copy of the module outside ``tools/``.
TOWER_TOOLS = Path(__file__).resolve().parent.parent / "tower-dsh" / "tools"

GH_STUB = '''import sys
argv = sys.argv[1:]
if argv[:2] == ["auth", "status"]:
    raise SystemExit(0)
if argv[:2] == ["pr", "create"]:
    print("https://example.invalid/pull/7")
    raise SystemExit(0)
if argv[:2] == ["pr", "checks"]:
    print("tower gate\\tfail\\t1\\thttps://example.invalid/run/1")
    raise SystemExit(1)
raise SystemExit(0)
'''


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Tower:
    """One throw-away tower root plus the kit repository that contains it."""

    def __init__(self, base: Path, towerctl: Path) -> None:
        self.towerctl = towerctl.resolve()
        self.tmp = base
        self.kit = self.tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.origin = self.tmp / "origin.git"
        self.stub = self.tmp / "gh_stub.py"
        self.build()

    # -- git / tower helpers ---------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(["git", "-C", str(self.kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              env=env)

    def commit(self, message: str) -> str:
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        if cp.returncode != 0:
            raise SystemExit(f"probe fixture commit failed: {cp.stdout}{cp.stderr}")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def build(self) -> None:
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.stub.write_text(GH_STUB, encoding="utf-8")
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{TASK}", "incoming"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "PROBE", "primary": {"id": "ctl-probe"},
            "owner": {"name": "mac"}, "next_action": "probe"})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "PROBE",
            "supervisor": {"id": "sup-probe"}})
        write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1", "tasks": []})
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("probe proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": "probe",
            "status": "closed", "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                          "bytes": proof.stat().st_size}]})
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")

        self.kit.mkdir(parents=True, exist_ok=True)
        self.git("init")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        self.commit("base")
        self.git("checkout", "-b", BRANCH)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.git("add", "feature.txt")
        self.implementation_head = self.commit("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.git("add", ENVELOPE_PATH)
        self.envelope_head = self.commit("envelope")
        self.git("checkout", BASE)
        subprocess.run(["git", "init", "--bare", str(self.origin)],
                       capture_output=True, text=True, encoding="utf-8")
        self.git("remote", "add", "origin", str(self.origin).replace("\\", "/"))
        write_json(self.root / "incoming" / f"{ENVELOPE}.json", {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1, "tower_tests_baseline": 1})

    # -- CLI / state ------------------------------------------------------
    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["TOWERCTL_GH"] = f"{sys.executable} {self.stub}"
        env["PYTHONPATH"] = (str(TOWER_TOOLS) + os.pathsep
                             + env.get("PYTHONPATH", ""))
        return subprocess.run(
            [sys.executable, "-B", str(self.towerctl), "--root", str(self.root),
             *args], capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=120)

    def envelope_new(self) -> subprocess.CompletedProcess:
        return self.run("envelope-new", "--task", TASK, "--file",
                        str(self.root / "incoming" / f"{ENVELOPE}.json"))

    def queue_add(self) -> subprocess.CompletedProcess:
        return self.run("queue-add", "--envelope", ENVELOPE)

    def merge(self, *args: str) -> subprocess.CompletedProcess:
        return self.run("merge", "--envelope", ENVELOPE, "--role", "supervisor",
                        "--supervisor", "sup-probe", *args)

    def envelope(self) -> dict:
        return read_json(self.root / "supervision" / "envelopes"
                         / f"{ENVELOPE}.json")

    def queue_status(self) -> str:
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        return next(e["status"] for e in queue["entries"]
                    if e["envelope_id"] == ENVELOPE)

    def events(self, event_type: str | None = None) -> list[dict]:
        path = self.root / "ledger" / "supervision.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return [e for e in rows if event_type is None or e.get("type") == event_type]

    def drift(self) -> list[str]:
        cp = self.run("state-verify")
        return [row["kind"] for row in json.loads(cp.stdout)["drift"]]


def exit_json(label: str, out: str) -> None:
    try:
        payload = json.loads(out)
    except ValueError:
        return
    errors = payload.get("errors")
    if errors:
        first = errors[0]
        detail = first if isinstance(first, str) else first.get("detail", first)
        print(f"    {label} error: {detail}")


def scenario_a(towerctl: Path, base: Path) -> None:
    print("A. normal first envelope (DRAFT -> queue-add -> merge)")
    tower = Tower(base / "a", towerctl)
    cp = tower.envelope_new()
    print(f"    envelope-new exit={cp.returncode} status={tower.envelope()['status']}")
    cp = tower.queue_add()
    print(f"    queue-add exit={cp.returncode} envelope={tower.envelope()['status']} "
          f"queue={tower.queue_status()}")
    cp = tower.merge()
    print(f"    merge exit={cp.returncode} envelope={tower.envelope()['status']} "
          f"queue={tower.queue_status()}")
    exit_json("merge", cp.stdout)


def scenario_b(towerctl: Path, base: Path) -> None:
    print("B. failed PR merge -> re-envelope -> second merge")
    tower = Tower(base / "b", towerctl)
    tower.envelope_new()
    tower.queue_add()
    cp = tower.merge("--mode", "pr", "--check-timeout", "10", "--check-interval", "1")
    print(f"    first merge exit={cp.returncode} envelope={tower.envelope()['status']} "
          f"queue={tower.queue_status()} MERGE_BLOCKED={len(tower.events('MERGE_BLOCKED'))}")
    cp = tower.envelope_new()
    print(f"    re-envelope exit={cp.returncode} status={tower.envelope()['status']} "
          f"ENVELOPE_NEW={len(tower.events('ENVELOPE_NEW'))}")
    cp = tower.merge()
    print(f"    second merge exit={cp.returncode} envelope={tower.envelope()['status']}")
    exit_json("second merge", cp.stdout)
    print(f"    state-verify drift={tower.drift()}")


def scenario_c(towerctl: Path, base: Path) -> None:
    print("C. re-envelope of a still-DRAFT envelope -> merge")
    tower = Tower(base / "c", towerctl)
    tower.envelope_new()
    tower.queue_add()
    tower.envelope_new()
    starts = len(tower.events("MERGE_START"))
    print(f"    after re-envelope status={tower.envelope()['status']} "
          f"ENVELOPE_NEW={len(tower.events('ENVELOPE_NEW'))}")
    cp = tower.merge()
    print(f"    merge exit={cp.returncode} "
          f"MERGE_START delta={len(tower.events('MERGE_START')) - starts}")
    exit_json("merge", cp.stdout)
    print(f"    state-verify drift={tower.drift()}")


def scenario_d(towerctl: Path, base: Path) -> None:
    print("D. re-envelope of a MERGED envelope")
    tower = Tower(base / "d", towerctl)
    tower.envelope_new()
    tower.queue_add()
    tower.merge()
    print(f"    merged status={tower.envelope()['status']}")
    cp = tower.envelope_new()
    print(f"    re-envelope exit={cp.returncode} status={tower.envelope()['status']}")
    exit_json("re-envelope", cp.stdout)


def scenario_e(towerctl: Path, base: Path) -> None:
    print("E. replay unit (repeated ENVELOPE_NEW)")
    root = base / "e"
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    rows = [
        ("ENV-WAIT", "ENVELOPE_NEW"), ("ENV-WAIT", "QUEUE_ADD"),
        ("ENV-WAIT", "ENVELOPE_NEW"),
        ("ENV-CORR", "ENVELOPE_NEW"), ("ENV-CORR", "QUEUE_ADD"),
        ("ENV-CORR", "MERGE_START"), ("ENV-CORR", "MERGE_BLOCKED"),
        ("ENV-CORR", "ENVELOPE_NEW"),
        ("ENV-MERGED", "ENVELOPE_NEW"), ("ENV-MERGED", "QUEUE_ADD"),
        ("ENV-MERGED", "MERGE_START"), ("ENV-MERGED", "MERGE"),
        ("ENV-MERGED", "ENVELOPE_NEW"),
        ("ENV-NEW", "ENVELOPE_NEW"),
    ]
    (root / "ledger" / "supervision.jsonl").write_text(
        "".join(json.dumps({"seq": index, "type": event_type,
                            "payload": {"envelope": envelope}}) + "\n"
                for index, (envelope, event_type) in enumerate(rows, 1)),
        encoding="utf-8")
    spec = importlib.util.spec_from_file_location("probe_towerctl", str(towerctl))
    module = importlib.util.module_from_spec(spec)
    if str(TOWER_TOOLS) not in sys.path:
        sys.path.insert(0, str(TOWER_TOOLS))
    spec.loader.exec_module(module)
    transitions: list[dict] = []
    states = module.replay_envelope_statuses(root, transitions)
    print(f"    folded={json.dumps(states, sort_keys=True)}")
    print(f"    illegal={[(r['target'], r['event'], r['actual']) for r in transitions]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--towerctl", required=True,
                        help="towerctl.py under probe (old or new)")
    parser.add_argument("--label", default="probe")
    args = parser.parse_args(argv)
    towerctl = Path(args.towerctl)
    if not towerctl.is_file():
        raise SystemExit(f"towerctl not found: {towerctl}")
    print(f"PILOT-053 envelope probe [{args.label}] towerctl={towerctl}")
    base = Path(tempfile.mkdtemp(prefix=f"pilot053-{args.label}-"))
    try:
        for scenario in (scenario_a, scenario_b, scenario_c, scenario_d,
                         scenario_e):
            scenario(towerctl, base)
            print()
    finally:
        print(f"probe workspace: {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
