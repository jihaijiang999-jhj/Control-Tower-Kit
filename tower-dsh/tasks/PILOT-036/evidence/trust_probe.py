#!/usr/bin/env python3
"""PILOT-036 CLI-level trust-boundary probe.

Builds throw-away towers and drives the *real* CLI of a chosen ``towerctl.py``
in a subprocess (never importing the tool under test).  Point ``--tool`` at the
pre-PILOT-036 ``main`` copy to show what the old code accepted:

    python -B scratch/trust_probe.py
    python -B scratch/trust_probe.py --tool scratch/old/towerctl.py

Scenarios (all "real" CLI runs):

1. missing ``ledger/supervision.jsonl``  -> verify-ledger, merge-check
2. empty ``ledger/supervision.jsonl``    -> verify-ledger
3. unreadable (directory) supervision    -> verify-ledger, merge-check
4. unreadable (directory) primary        -> verify-ledger, merge-check
5. integer ``envelope_id`` (42 vs "42")  -> merge-check, merge
6. ``ENVELOPE_NEW`` head mismatch        -> merge-check
7. ``ENVELOPE_NEW`` task mismatch        -> merge-check
8. valid tower                           -> merge-check (regression)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
DEFAULT_TOOL = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
TOOLS_DIR = WORKTREE / "tower-dsh" / "tools"

TASK = "T-TRUST-001"
ENVELOPE = "42"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/trust"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
GENESIS = "GENESIS"

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


def canonical_hash(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=env)


class Tower:
    """One isolated kit (git repo) + tower root, built like the real layout."""

    def __init__(self, base: Path, tool: Path):
        self.tool = tool
        self.kit = base / "kit"
        self.root = self.kit / "tower-dsh"
        self.envelope_file = self.root / "envelope.json"

    # -- build -----------------------------------------------------------
    def build(self) -> "Tower":
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        self.ledger_path().touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1",
            "id": TASK,
            "title": "trust boundary probe",
            "status": "accepted",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{TASK}/evidence/proof.txt",
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "bytes": proof.stat().st_size,
                "at": FIXED_TIME,
            }],
        })
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "primary": {"id": "ctl-primary"},
            "owner": {"name": "mac"},
            "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.init_repo()
        write_json(self.envelope_file, self.payload())
        return self

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        assert self.git("init").returncode == 0
        assert self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode == 0
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / "merge-envelopes").mkdir()
        self.commit_all("base")
        assert self.git("checkout", "-b", BRANCH).returncode == 0
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        write_json(self.kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        self.envelope_head = self.commit_all("envelope")
        assert self.git("checkout", "main").returncode == 0

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return git(self.kit, *args)

    def commit_all(self, message: str) -> str:
        add = self.git("add", "-A")
        assert add.returncode == 0, add.stderr
        commit = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        assert commit.returncode == 0, commit.stdout + commit.stderr
        return self.git("rev-parse", "HEAD").stdout.strip()

    def payload(self) -> dict:
        return {
            "schema": "tower/merge-envelope@1",
            "envelope_id": ENVELOPE,
            "task": TASK,
            "repository": "..",
            "branch": BRANCH,
            "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1,
            "tower_tests_baseline": 1,
        }

    # -- commands --------------------------------------------------------
    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # ``towerctl`` imports its sibling helpers (spec_lint/spec_coverage);
        # the probe may be pointed at a copy outside ``tools/``.
        env["PYTHONPATH"] = str(TOOLS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-B", str(self.tool), "--root", str(self.root),
             *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def create_valid(self) -> None:
        cp = self.run("envelope-new", "--task", TASK,
                      "--file", str(self.envelope_file))
        assert cp.returncode == 0, f"envelope-new: {cp.stdout}\n{cp.stderr}"
        cp = self.run("queue-add", "--envelope", ENVELOPE)
        assert cp.returncode == 0, f"queue-add: {cp.stdout}\n{cp.stderr}"

    # -- ledger helpers --------------------------------------------------
    def ledger_path(self) -> Path:
        return self.root / "ledger" / "supervision.jsonl"

    def ledger_events(self) -> list[dict]:
        text = self.ledger_path().read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def write_chain(self, events: list[dict]) -> None:
        previous = GENESIS
        lines = []
        for seq, event in enumerate(events, 1):
            event["seq"] = seq
            event["prev_hash"] = previous
            event["hash"] = canonical_hash(event)
            previous = event["hash"]
            lines.append(json.dumps(event, ensure_ascii=False) + "\n")
        self.ledger_path().write_text("".join(lines), encoding="utf-8",
                                      newline="\n")

    def queue_status(self) -> str:
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        entries = queue.get("entries") or []
        return entries[0]["status"] if entries else "no-entry"


# -- result rendering ----------------------------------------------------
def parse_stdout(cp: subprocess.CompletedProcess):
    text = (cp.stdout or "").strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def describe(cp: subprocess.CompletedProcess) -> str:
    payload = parse_stdout(cp)
    parts = [
        f"exit={cp.returncode}",
        f"traceback={'yes' if 'Traceback' in (cp.stderr or '') else 'no'}",
        f"one_json={'yes' if payload is not None else 'no'}",
    ]
    if payload is not None:
        parts.append(f"ok={payload.get('ok')}")
    return " ".join(parts)


def detail_lines(cp: subprocess.CompletedProcess) -> list[str]:
    payload = parse_stdout(cp)
    lines: list[str] = []
    if payload is not None:
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            if all(isinstance(error, str) for error in errors):
                lines.append("errors=" + json.dumps(errors, ensure_ascii=False))
                identity = [error for error in errors
                            if error.startswith("envelope identity matches request:")]
                if identity:
                    lines.append("command_level_identity=failed (plain string)")
            else:
                for error in errors:
                    if isinstance(error, dict):
                        lines.append(
                            f"error[{error.get('name')}] ok=false "
                            f"detail={error.get('detail')!r}")
                    else:
                        lines.append(f"error={error}")
                names = [error.get("name") for error in errors
                         if isinstance(error, dict)]
                if "envelope identity matches request" in names:
                    lines.append(
                        "command_level_identity=passed (caught later by "
                        "envelope_checks, errors are check dicts)")
        checks = payload.get("checks")
        if isinstance(checks, list):
            interesting = ("envelope identity matches request",
                           "ledger chain intact", "envelope_new recorded",
                           "queue entry backed by ledger")
            for name in interesting:
                check = next((c for c in checks if c.get("name") == name), None)
                if check is not None:
                    lines.append(
                        f"check[{name}] ok={check.get('ok')} "
                        f"detail={check.get('detail')!r}")
        if payload.get("status"):
            lines.append(f"status={payload['status']}")
        if payload.get("merge_commit"):
            lines.append(f"merge_commit={payload['merge_commit']}")
    if cp.stderr and cp.stderr.strip():
        last = cp.stderr.strip().splitlines()[-1]
        lines.append("stderr_last=" + last[:220])
    return lines


def report(label: str, cp: subprocess.CompletedProcess,
           extra: str | None = None) -> None:
    print(f"  {label}: {describe(cp)}")
    for line in detail_lines(cp):
        print(f"    {line}")
    if extra:
        print(f"    {extra}")


# -- scenarios -----------------------------------------------------------
def scenario_missing(tool: Path, base: Path) -> None:
    tower = Tower(base, tool).build()
    tower.create_valid()
    tower.ledger_path().unlink()
    print("[1] missing supervision ledger (valid tower, ledger/supervision.jsonl removed)")
    report("verify-ledger --ledger supervision",
           tower.run("verify-ledger", "--ledger", "supervision"))
    report("merge-check --envelope 42",
           tower.run("merge-check", "--envelope", ENVELOPE),
           f"queue_status={tower.queue_status()}")


def scenario_empty(tool: Path, base: Path) -> None:
    tower = Tower(base, tool).build()
    print("[2] empty supervision ledger (existing file, zero events)")
    report("verify-ledger",
           tower.run("verify-ledger"))
    report("verify-ledger --ledger supervision",
           tower.run("verify-ledger", "--ledger", "supervision"))


def scenario_unreadable(tool: Path, base: Path, name: str) -> None:
    tower = Tower(base, tool).build()
    tower.create_valid()
    path = tower.root / "ledger" / f"{name}.jsonl"
    path.unlink()
    path.mkdir()
    print(f"[{3 if name == 'supervision' else 4}] unreadable {name} ledger "
          f"(ledger/{name}.jsonl replaced by a directory)")
    report(f"verify-ledger --ledger {name}",
           tower.run("verify-ledger", "--ledger", name))
    report("merge-check --envelope 42",
           tower.run("merge-check", "--envelope", ENVELOPE),
           f"queue_status={tower.queue_status()}")


def scenario_integer_id(tool: Path, base: Path) -> None:
    tower = Tower(base, tool).build()
    tower.create_valid()
    record_path = tower.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
    record = read_json(record_path)
    record["envelope_id"] = 42
    write_json(record_path, record)
    print("[5] integer envelope_id 42, request '42' (str(42) == '42')")
    report("merge-check --envelope 42",
           tower.run("merge-check", "--envelope", ENVELOPE),
           f"queue_status={tower.queue_status()}")
    report("merge --role supervisor --supervisor sup-test --envelope 42",
           tower.run("merge", "--role", "supervisor",
                     "--supervisor", "sup-test", "--envelope", ENVELOPE),
           f"queue_status={tower.queue_status()}")
    # Control: put the string back; the identity gate must no longer fire.
    record["envelope_id"] = ENVELOPE
    write_json(record_path, record)
    report("merge-check --envelope 42 (id restored as string)",
           tower.run("merge-check", "--envelope", ENVELOPE))


def scenario_binding(tool: Path, base: Path, field: str) -> None:
    number = 6 if field == "head" else 7
    tower = Tower(base, tool).build()
    tower.create_valid()
    events = tower.ledger_events()
    created = next(event for event in events
                   if event.get("type") == "ENVELOPE_NEW")
    old = created["payload"].get(field)
    created["payload"][field] = ("a" * 40) if field == "head" else "T-OTHER-001"
    tower.write_chain(events)
    print(f"[{number}] ENVELOPE_NEW {field} mismatch "
          f"(event {field}={created['payload'][field]!r}, envelope {old!r})")
    report("merge-check --envelope 42",
           tower.run("merge-check", "--envelope", ENVELOPE))
    report("merge --role supervisor --supervisor sup-test --envelope 42",
           tower.run("merge", "--role", "supervisor",
                     "--supervisor", "sup-test", "--envelope", ENVELOPE),
           f"queue_status={tower.queue_status()}")


def scenario_valid(tool: Path, base: Path) -> None:
    tower = Tower(base, tool).build()
    tower.create_valid()
    print("[8] valid tower (envelope-new + queue-add, matching ENVELOPE_NEW)")
    report("merge-check --envelope 42",
           tower.run("merge-check", "--envelope", ENVELOPE))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", default=str(DEFAULT_TOOL),
                        help="towerctl.py under test (default: worktree tool)")
    args = parser.parse_args()
    tool = Path(args.tool)
    if not tool.is_absolute():
        tool = (WORKTREE / tool).resolve()
    if not tool.is_file():
        print(f"tool not found: {tool}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(tool.read_bytes()).hexdigest()

    print("=== PILOT-036 trust-boundary probe ===")
    print(f"tool     : {tool}")
    print(f"tool_sha : {digest}")
    print(f"python   : {sys.version.split()[0]}")
    print("")

    builders = [
        ("missing-ledger", scenario_missing),
        ("empty-ledger", scenario_empty),
        ("unreadable-supervision", lambda t, b: scenario_unreadable(t, b, "supervision")),
        ("unreadable-primary", lambda t, b: scenario_unreadable(t, b, "primary")),
        ("integer-envelope-id", scenario_integer_id),
        ("envelope-new-head", lambda t, b: scenario_binding(t, b, "head")),
        ("envelope-new-task", lambda t, b: scenario_binding(t, b, "task")),
        ("valid-tower", scenario_valid),
    ]

    with tempfile.TemporaryDirectory(
            prefix="tower-trust-probe-", ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        for index, (name, builder) in enumerate(builders, 1):
            print(f"--- scenario {name} ---")
            builder(tool, base / f"{index:02d}-{name}")
            print("")

    print("=== probe done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
