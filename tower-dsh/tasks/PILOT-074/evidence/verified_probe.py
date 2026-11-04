"""PILOT-074 evidence probe: verified needs a MERGE fact, backfill and drift.

Two modes, chosen from the state it finds:

* pre-backfill (worktree still has 065--068 verified without a merge fact): the
  probe copies ``tower-dsh`` to a disposable ``probe-tower`` next to it, runs
  the four ``envelope-recover --historical`` calls there (the copy's
  ``repository: ".."`` still resolves to the worktree repository, whose
  ``origin/main`` carries the merge commits), proves the copy's drift is 0 and
  removes the copy.  The real tower state is never written.
* post-backfill (the worktree itself is backfilled): read-only verification of
  the envelopes, the MERGE_HISTORICAL events and the commit parentage.

    python -B scratch/verified_probe.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
PROBE = WORKTREE / "probe-tower"
CLI = TOWER / "tools" / "towerctl.py"

BACKFILL = {
    "ENV-PILOT-065": "c1999284712d12a680c9956e9f08ac93c4961742",
    "ENV-PILOT-066": "713d7098b1d97af4ca818be3045a320d7d3d4081",
    "ENV-PILOT-067": "eba7ed3f5c485bd52dcef4c6e17ed42debe83a1e",
    "ENV-PILOT-068": "969acdb6c9f3aebb5ceb1182ef00f895c639e323",
}


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(CLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300)


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                        text=True, encoding="utf-8")
    assert cp.returncode == 0, (args, cp.stdout, cp.stderr)
    return cp.stdout.strip()


def state_verify(root: Path) -> dict:
    cp = cli(root, "state-verify")
    return {"exit": cp.returncode, "payload": json.loads(cp.stdout)}


def record(root: Path, envelope: str) -> dict:
    path = root / "supervision" / "envelopes" / f"{envelope}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def events(root: Path, event_type: str, envelope: str) -> list[dict]:
    rows = [json.loads(line) for line in
            (root / "ledger" / "supervision.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]
    return [row for row in rows if row["type"] == event_type
            and row["payload"].get("envelope") == envelope]


def verify_facts(root: Path) -> None:
    """The four backfilled envelopes, the events and the commit parentage."""
    for envelope, commit in BACKFILL.items():
        envelope_record = record(root, envelope)
        assert envelope_record["status"] == "POST_MERGE_VERIFIED", envelope_record
        assert envelope_record["merge_commit"] == commit, envelope_record
        assert "admin" not in envelope_record, envelope_record
        assert events(root, "MERGE", envelope) == [], envelope
        historical = events(root, "MERGE_HISTORICAL", envelope)
        assert len(historical) == 1, historical
        payload = historical[0]["payload"]
        assert payload["merge_commit"] == commit, payload
        assert payload["historical"] is True, payload
        assert payload["recovered"] is True, payload
        assert payload["by"] == "sup-phase2-pilot", payload
        implementation = envelope_record["implementation_head_sha"]
        parents = git(WORKTREE, "rev-list", "--parents", "-n", "1", commit).split()
        assert len(parents) >= 3 and parents[2] == implementation, parents
        git(WORKTREE, "merge-base", "--is-ancestor", commit,
            "refs/remotes/origin/main")
        print(f"{envelope}: status=POST_MERGE_VERIFIED merge_commit={commit[:7]} "
              f"second_parent={implementation[:7]} on_origin_main=yes "
              f"historical=yes")


def main() -> int:
    before = state_verify(TOWER)
    drift = [item for item in before["payload"]["drift"]
             if item["kind"] == "verified_without_merge"]
    print(f"worktree state-verify exit={before['exit']} "
          f"verified_without_merge={sorted(item['target'] for item in drift)}")
    if not drift:
        print("mode=post-backfill (read-only)")
        assert before["exit"] == 0, before
        verify_facts(TOWER)
        print("PROBE PASS")
        return 0

    print("mode=pre-backfill (backfill on a disposable copy)")
    assert before["exit"] == 2, before
    assert sorted(item["target"] for item in drift) == sorted(BACKFILL)
    if PROBE.exists():
        shutil.rmtree(PROBE)
    shutil.copytree(TOWER, PROBE,
                    ignore=shutil.ignore_patterns(".test-tmp", "__pycache__"))
    try:
        for envelope, commit in BACKFILL.items():
            cp = cli(PROBE, "envelope-recover", "--historical",
                     "--envelope", envelope, "--merge-commit", commit,
                     "--reason", "PILOT-074 historical backfill")
            print(f"historical {envelope}: exit={cp.returncode}")
            assert cp.returncode == 0, (envelope, cp.stdout, cp.stderr)
        verify_facts(PROBE)
        after = state_verify(PROBE)
        assert after["exit"] == 0, after
        print(f"post-backfill state-verify exit={after['exit']} "
              f"drift={after['payload']['drift']}")
    finally:
        shutil.rmtree(PROBE, ignore_errors=True)
    print("PROBE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
