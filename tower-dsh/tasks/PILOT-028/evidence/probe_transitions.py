#!/usr/bin/env python3
"""Read-only probe: every observed (event, from, to) transition in a tower.

Folds the real ledgers with the same parsing helpers as towerctl, but keeps
its own state machines so the observed table is derived from the ledgers, not
from the legal tables under test.  Writes nothing to the tower.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

TOWER_TOOLS = Path(__file__).resolve().parents[1] / "tower-dsh" / "tools"
sys.path.insert(0, str(TOWER_TOOLS))
import towerctl  # noqa: E402

TASK_STATUS = {
    "TASK_NEW": "ready",
    "DISPATCH": "dispatched",
    "DELIVER": "delivered",
    "ACCEPT": "accepted",
    "CLOSEOUT": "closed",
}
ENVELOPE_STATUS = {
    "ENVELOPE_NEW": "DRAFT",
    "QUEUE_ADD": "WAITING",
    "MERGE": "MERGED",
    "POST_MERGE_VERIFIED": "POST_MERGE_VERIFIED",
}


def transitions(root: Path, ledger: str, id_key: str, status_map: dict,
                correction_events: set, merge_start: str | None):
    rows: collections.Counter = collections.Counter()
    examples: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    internal: dict[str, str] = {}
    for event in towerctl.ledger_events_in_seq_order(root, ledger):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        entity = payload.get(id_key)
        if not isinstance(entity, str) or not entity:
            continue
        event_type = event.get("type")
        before = internal.get(entity)
        if event_type == "CHECKBACK":
            after = "reviewed" if payload.get("verdict") == "PASS" else "rework"
        elif merge_start is not None and event_type == merge_start:
            after = "MERGING"
        elif event_type in status_map:
            after = status_map[event_type]
        elif event_type in correction_events:
            after = "CORRECTION_REQUIRED"
        else:
            continue
        pair = (event_type, before, after)
        rows[pair] += 1
        if pair not in examples:
            examples[pair] = []
            order.append(pair)
        if len(examples[pair]) < 3:
            examples[pair].append(entity)
        internal[entity] = after
    return order, rows, examples, internal


def main() -> None:
    root = Path(sys.argv[1])
    print(f"# read-only transition probe: {root}")
    print(f"# ledger rows: primary="
          f"{sum(1 for _ in (root / 'ledger' / 'primary.jsonl').open(encoding='utf-8'))} "
          f"supervision="
          f"{sum(1 for _ in (root / 'ledger' / 'supervision.jsonl').open(encoding='utf-8'))}")
    for label, ledger, id_key, statuses, corrections, merge_start in (
        ("TASK", "primary", "task", TASK_STATUS, set(), None),
        ("ENVELOPE", "supervision", "envelope", ENVELOPE_STATUS,
         {"MERGE_BLOCKED", "POST_MERGE_FAILED"}, "MERGE_START"),
    ):
        order, rows, examples, internal = transitions(
            root, ledger, id_key, statuses, corrections, merge_start)
        print(f"\n## {label} transitions ({len(order)} distinct "
              f"(event, from, to) pairs, {sum(rows.values())} events, "
              f"{len(internal)} entities)")
        print(f"{'event':22} {'from':22} {'to':22} {'count':>5}  examples")
        for pair in sorted(order, key=lambda p: (p[0], str(p[1]), p[2])):
            event_type, before, after = pair
            print(f"{event_type:22} {str(before):22} {after:22} "
                  f"{rows[pair]:>5}  {', '.join(examples[pair])}")


if __name__ == "__main__":
    main()
