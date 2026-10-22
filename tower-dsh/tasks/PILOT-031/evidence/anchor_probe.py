"""Read-only probe: monotonic tower-baseline matrix on throw-away temp towers.

Every scenario builds a fresh tower kit under the OS temp directory (via the
existing ``test_post_merge`` fixture), seeds the supervision ledger with
``POST_MERGE_VERIFIED`` events carrying ``tower_tests_count``, runs the real
``towerctl.py post-merge`` CLI through ``subprocess`` and prints the observed
exit code, envelope status and the ``tower baseline >= last verified`` check.

Nothing here writes to a real tower.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER_ROOT = WORKTREE / "tower-dsh"
sys.path.insert(0, str(TOWER_ROOT / "tools" / "tests"))

import test_post_merge as fixture  # noqa: E402

# Keep the fixture's throw-away repos inside the tower's gitignored sandbox so
# the probe also works where %TEMP% ACLs are unusable.
SANDBOX = TOWER_ROOT / ".test-tmp"
SANDBOX.mkdir(parents=True, exist_ok=True)
for _name in ("TMPDIR", "TEMP", "TMP"):
    os.environ[_name] = str(SANDBOX)
tempfile.tempdir = None  # re-read the environment on the next call


def probe(label: str, *, anchor, baseline: int, suite: int) -> dict:
    case = fixture.PostMergeTestCase()
    case.setUp()
    try:
        case.write_envelope(status="MERGED", merge_commit=case.merge_commit,
                            tests_baseline=1, tower_tests_baseline=baseline)
        if anchor:
            case.seed_verified_events(*anchor)
        case.write_tower_suite(suite)
        cp = case.run_post_merge("PASS")
        payload = json.loads(cp.stdout)
        check = next((c for c in payload["checks"]
                      if c["name"] == "tower baseline >= last verified"), None)
        verified = [e for e in case.ledger_events()
                    if e["type"] == "POST_MERGE_VERIFIED"
                    and e["payload"].get("envelope") == fixture.ENVELOPE_ID]
        result = {
            "label": label,
            "anchor_events": list(anchor) if anchor else [],
            "baseline": baseline,
            "suite": suite,
            "exit": cp.returncode,
            "status": payload["status"],
            "check": check,
            "verified_events_for_envelope": len(verified),
        }
    finally:
        case.tearDown()
    print(f"[{label}]")
    print(f"  anchor_events={result['anchor_events']} baseline={baseline} "
          f"suite={suite}")
    print(f"  exit={result['exit']} status={result['status']} "
          f"verified_events_for_envelope={result['verified_events_for_envelope']}")
    if check is None:
        print("  anchor_check=<ABSENT>")
    else:
        print(f"  anchor_check ok={check['ok']} detail={check['detail']!r}")
    return result


results = [
    probe("block: baseline below verified", anchor=[10], baseline=5, suite=10),
    probe("pass: baseline equal to verified", anchor=[10], baseline=10, suite=10),
    probe("pass: baseline above verified", anchor=[10], baseline=12, suite=12),
    probe("legacy: no verified event", anchor=None, baseline=5, suite=10),
    probe("block: maximum wins over latest", anchor=[7, 10, 3], baseline=5, suite=10),
    probe("pass: invalid counts ignored", anchor=[True, "10", None, 7],
          baseline=7, suite=7),
]

expected_exits = [2, 0, 0, 0, 2, 0]
if [r["exit"] for r in results] != expected_exits:
    print("UNEXPECTED MATRIX: "
          f"got {[r['exit'] for r in results]}, expected {expected_exits}")
    raise SystemExit(1)
print("MATRIX OK")
