"""PILOT-060 probe: compare the old and new MERGE_START from-states.

Runs the real tower ledger and one synthetic retry through the shipped
``replay_envelope_statuses`` fold twice: once with the pre-060 transition
table and once with the table from the working tree.  No files are written
outside the temporary directory.

    python -B scratch/retry_probe.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE.parents[2]
TOOLS = WORKTREE / "tower-dsh" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import tower_ledger_replay as replay  # noqa: E402

OLD = frozenset({"WAITING", "CORRECTION_REQUIRED"})
NEW = replay.ENVELOPE_TRANSITIONS["MERGE_START"]


def illegal_for(root: Path, envelope: str, table) -> list[dict]:
    saved = replay.ENVELOPE_TRANSITIONS["MERGE_START"]
    replay.ENVELOPE_TRANSITIONS["MERGE_START"] = table
    rows: list[dict] = []
    try:
        replay.replay_envelope_statuses(root, rows)
    finally:
        replay.ENVELOPE_TRANSITIONS["MERGE_START"] = saved
    return [row for row in rows
            if row["kind"] == "illegal_transition" and row["target"] == envelope]


def synthetic_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="pilot060-probe-"))
    (root / "ledger").mkdir(parents=True)
    (root / "ledger" / "primary.jsonl").touch()
    rows = [
        ("ENV-PROBE-RETRY", "ENVELOPE_NEW"),
        ("ENV-PROBE-RETRY", "QUEUE_ADD"),
        ("ENV-PROBE-RETRY", "MERGE_START"),
        ("ENV-PROBE-RETRY", "MERGE_START"),
        ("ENV-PROBE-DRAFT", "ENVELOPE_NEW"),
        ("ENV-PROBE-DRAFT", "MERGE_START"),
        ("ENV-PROBE-MERGED", "ENVELOPE_NEW"),
        ("ENV-PROBE-MERGED", "QUEUE_ADD"),
        ("ENV-PROBE-MERGED", "MERGE_START"),
        ("ENV-PROBE-MERGED", "MERGE"),
        ("ENV-PROBE-MERGED", "MERGE_START"),
        ("ENV-PROBE-VERIFIED", "ENVELOPE_NEW"),
        ("ENV-PROBE-VERIFIED", "QUEUE_ADD"),
        ("ENV-PROBE-VERIFIED", "MERGE_START"),
        ("ENV-PROBE-VERIFIED", "MERGE"),
        ("ENV-PROBE-VERIFIED", "POST_MERGE_VERIFIED"),
        ("ENV-PROBE-VERIFIED", "MERGE_START"),
    ]
    (root / "ledger" / "supervision.jsonl").write_text("".join(
        json.dumps({"seq": index, "type": event_type,
                    "payload": {"envelope": envelope}}) + "\n"
        for index, (envelope, event_type) in enumerate(rows, 1)),
        encoding="utf-8")
    return root


def main() -> int:
    print("old MERGE_START =", sorted(OLD))
    print("new MERGE_START =", sorted(NEW))
    for label, table in (("old", OLD), ("new", NEW)):
        rows = illegal_for(TOWER, "ENV-PILOT-056", table)
        print(f"real tower ENV-PILOT-056 ({label} table): "
              f"{len(rows)} illegal_transition", json.dumps(rows, sort_keys=True))
    starts = [event for event in replay.ledger_events_in_seq_order(
        TOWER, "supervision")
        if event.get("type") == "MERGE_START"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("envelope") == "ENV-PILOT-056"]
    print("real tower ENV-PILOT-056 MERGE_START events:", len(starts))

    root = synthetic_root()
    for envelope in ("ENV-PROBE-RETRY", "ENV-PROBE-DRAFT",
                     "ENV-PROBE-MERGED", "ENV-PROBE-VERIFIED"):
        old = illegal_for(root, envelope, OLD)
        new = illegal_for(root, envelope, NEW)
        print(f"synthetic {envelope}: old={len(old)} new={len(new)} "
              f"new_actual={[row['actual'] for row in new]}")
    states = replay.replay_envelope_statuses(root)
    print("synthetic folded states:", json.dumps(states, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
