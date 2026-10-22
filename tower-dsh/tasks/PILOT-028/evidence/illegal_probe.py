#!/usr/bin/env python3
"""Build a throw-away tower with illegal transitions and print state-verify.

The tower lives under the system temp directory (never the real tower), its
ledgers are appended through the real towerctl helpers, and every record /
board / queue / envelope agrees with the last-writer-wins fold so the only
drift in the output is the new ``illegal_transition`` kind.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOWER = Path(__file__).resolve().parents[1] / "tower-dsh"
sys.path.insert(0, str(TOWER / "tools"))
import towerctl  # noqa: E402


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="towerctl-illegal-probe-",
                                     ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        for directory in ("ledger", "primary", "tasks",
                          "supervision", "supervision/envelopes"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "ledger" / "primary.jsonl").touch()
        (root / "ledger" / "supervision.jsonl").touch()

        # Task jump: TASK_NEW -> CLOSEOUT, skipping the whole lifecycle.
        towerctl.append_ledger(root, "TASK_NEW", "primary", {"task": "T-JUMP"})
        towerctl.append_ledger(root, "CLOSEOUT", "primary", {"task": "T-JUMP"})
        # ACCEPT with no reviewed CHECKBACK.
        for event_type in ("TASK_NEW", "DISPATCH", "DELIVER", "ACCEPT"):
            towerctl.append_ledger(root, event_type, "primary",
                                   {"task": "T-ACCEPT"})
        # MERGE without MERGE_START.
        for event_type in ("ENVELOPE_NEW", "QUEUE_ADD"):
            towerctl.append_supervision_ledger(
                root, event_type, "supervision", {"envelope": "ENV-MERGE"})
        towerctl.append_supervision_ledger(
            root, "MERGE", "supervision", {"envelope": "ENV-MERGE"})
        # POST_MERGE_VERIFIED while the envelope is still WAITING.
        for event_type in ("ENVELOPE_NEW", "QUEUE_ADD"):
            towerctl.append_supervision_ledger(
                root, event_type, "supervision", {"envelope": "ENV-VERIFY"})
        towerctl.append_supervision_ledger(
            root, "POST_MERGE_VERIFIED", "supervision",
            {"envelope": "ENV-VERIFY"})

        # Everything outside the new check agrees with the fold.
        write_json(root / "tasks" / "T-JUMP" / "record.json",
                   {"schema": "tower/task@1", "id": "T-JUMP",
                    "title": "T-JUMP", "status": "closed"})
        write_json(root / "tasks" / "T-ACCEPT" / "record.json",
                   {"schema": "tower/task@1", "id": "T-ACCEPT",
                    "title": "T-ACCEPT", "status": "accepted"})
        write_json(root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tower_id": "tower-dsh",
                    "tasks": [{"id": "T-JUMP", "title": "T-JUMP",
                               "status": "closed"},
                              {"id": "T-ACCEPT", "title": "T-ACCEPT",
                               "status": "accepted"}]})
        write_json(root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1",
                    "entries": [
                        {"envelope_id": "ENV-MERGE", "task": "T-JUMP",
                         "status": "MERGED"},
                        {"envelope_id": "ENV-VERIFY", "task": "T-ACCEPT",
                         "status": "POST_MERGE_VERIFIED"}]})
        for envelope_id, status in (("ENV-MERGE", "MERGED"),
                                    ("ENV-VERIFY", "POST_MERGE_VERIFIED")):
            write_json(root / "supervision" / "envelopes" /
                       f"{envelope_id}.json",
                       {"schema": "tower/merge-envelope@1",
                        "envelope_id": envelope_id, "status": status})

        proc = subprocess.run(
            [sys.executable, "-B", str(TOWER / "tools" / "towerctl.py"),
             "--root", str(root), "state-verify"],
            capture_output=True, text=True, encoding="utf-8")
        print(proc.stdout, end="")
        if proc.returncode != 2:
            print(f"unexpected exit code: {proc.returncode}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
