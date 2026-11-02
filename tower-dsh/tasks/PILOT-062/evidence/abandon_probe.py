"""PILOT-062 evidence probe: the ``envelope-abandon`` state machine, end to end.

Builds a throw-away tower under a temporary directory, seeds one envelope that
folds to WAITING, and shows: the supervisor tombstone (envelope + queue +
ledger), a clean ``state-verify``, a refused terminal envelope with byte-equal
files, and an idempotent repeat.  Every command is the real CLI; no network,
no git repository, no tower state is touched.

    python -B scratch/abandon_probe.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TCLI = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"
if str(TCLI.parent) not in sys.path:
    sys.path.insert(0, str(TCLI.parent))

import towerctl  # noqa: E402  (tools/ on sys.path)

TASK = "PILOT-062"
ENVELOPE = "ENV-PILOT-062"
SUPERVISOR = "sup-062"
ABANDON = "ENVELOPE_ABANDON"


def dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120)


def seed_waiting(root: Path) -> None:
    for event in ("ENVELOPE_NEW", "QUEUE_ADD"):
        towerctl.append_supervision_ledger(
            root, event, "primary", {"envelope": ENVELOPE, "task": TASK})
    dump(root / "supervision" / "envelopes" / f"{ENVELOPE}.json",
         {"envelope_id": ENVELOPE, "task": TASK, "status": "WAITING"})
    dump(root / "supervision" / "MERGE_QUEUE.json",
         {"schema": "tower/merge-queue@1", "entries": [{
             "envelope_id": ENVELOPE, "task": TASK, "status": "WAITING"}]})


def snapshot(root: Path) -> tuple[bytes, bytes, bytes]:
    return (root.joinpath("supervision", "envelopes", f"{ENVELOPE}.json").read_bytes(),
            root.joinpath("supervision", "MERGE_QUEUE.json").read_bytes(),
            root.joinpath("ledger", "supervision.jsonl").read_bytes())


def report(label: str, cp: subprocess.CompletedProcess) -> None:
    print(f"== {label}: exit {cp.returncode}")
    print(cp.stdout.strip())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tower-abandon-probe-") as tmp:
        root = Path(tmp) / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        dump(root / "primary" / "CURRENT_STATE.json", {
            "tower_id": "tower-dsh", "owner": {"name": "mac"},
            "primary": {"id": "ctl-062"}})
        dump(root / "supervision" / "CURRENT_STATE.json", {
            "tower_id": "tower-dsh", "supervisor": {"id": SUPERVISOR}})
        dump(root / "primary" / "TASK_BOARD.json",
             {"schema": "tower/task-board@1", "tasks": []})
        for name in ("primary.jsonl", "supervision.jsonl"):
            (root / "ledger" / name).write_text("", encoding="utf-8")
        seed_waiting(root)
        report("state-verify before", cli(root, "state-verify"))

        report("abandon waiting envelope", cli(
            root, "envelope-abandon", "--envelope", ENVELOPE,
            "--reason", "043 is a failed envelope, tombstone it",
            "--by", SUPERVISOR))
        envelope = load(root / "supervision" / "envelopes" / f"{ENVELOPE}.json")
        queue = load(root / "supervision" / "MERGE_QUEUE.json")
        print("envelope.status =", envelope["status"])
        print("queue.status    =", queue["entries"][0]["status"])
        events = [json.loads(line) for line in
                  root.joinpath("ledger", "supervision.jsonl").read_text(
                      encoding="utf-8").splitlines() if line.strip()]
        print("event types     =", [row["type"] for row in events])
        print("payload         =", events[-1]["payload"])
        report("state-verify after", cli(root, "state-verify"))
        before = snapshot(root)
        report("repeat abandon", cli(root, "envelope-abandon", "--envelope",
                                     ENVELOPE, "--reason", "again", "--by",
                                     SUPERVISOR))
        print("repeat wrote nothing =", snapshot(root) == before)

        seed = root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
        dump(seed, {"envelope_id": ENVELOPE, "task": TASK, "status": "MERGED"})
        dump(root / "supervision" / "MERGE_QUEUE.json",
             {"schema": "tower/merge-queue@1", "entries": [{
                 "envelope_id": ENVELOPE, "task": TASK, "status": "MERGED"}]})
        before = snapshot(root)
        report("abandon merged envelope", cli(
            root, "envelope-abandon", "--envelope", ENVELOPE,
            "--reason", "illegal", "--by", SUPERVISOR))
        print("merged wrote nothing =", snapshot(root) == before)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
