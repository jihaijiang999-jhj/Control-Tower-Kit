#!/usr/bin/env python3
"""PILOT-079 scratch probe: drive tools/ledger_guard.py through five PR shapes.

Not part of the suite (lives in the untracked ``scratch/`` directory).  Builds
one throw-away git kit per case and prints the guard's exit code plus the error
kinds, so the evidence file shows the guard is really wired to git history.

    python scratch/ledger_probe.py > scratch/probe.txt 2>&1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "tower-dsh" / "tools" / "ledger_guard.py"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def git(kit: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(kit), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def event(seq: int, kind: str, prev: str, payload: dict) -> dict:
    body = {"seq": seq, "at": "2026-11-20T00:00:00+08:00", "type": kind,
            "actor": "primary", "payload": payload, "prev_hash": prev}
    import hashlib
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    body["hash"] = hashlib.sha256(canonical).hexdigest()
    return body


def chain(n: int = 2) -> list[dict]:
    rows, prev = [], "GENESIS"
    for index in range(1, n + 1):
        row = event(index, f"SEED_{index}", prev, {"n": index})
        prev = row["hash"]
        rows.append(row)
    return rows


def encode(rows: list[dict]) -> bytes:
    return b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
                    for row in rows)


def make_kit(tmp: Path) -> tuple[Path, Path]:
    kit = tmp / "kit"
    root = kit / "tower-dsh"
    (root / "ledger").mkdir(parents=True)
    (kit / "README.md").write_text("kit\n", encoding="utf-8")
    git(kit, "init")
    git(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    git(kit, "add", "-A")
    git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "skeleton")
    for name in ("primary", "supervision"):
        rows = chain()
        (root / "ledger" / f"{name}.jsonl").write_bytes(encode(rows))
    git(kit, "add", "-A")
    git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "base ledger")
    git(kit, "checkout", "-b", "feature/probe")
    return kit, root


def guard(root: Path) -> tuple[int, dict]:
    env = dict(os.environ)
    env.update(GIT_IDENTITY, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    cp = subprocess.run([sys.executable, "-B", str(GUARD), "--root", str(root),
                         "--base", "main"], capture_output=True, text=True,
                        encoding="utf-8", env=env)
    return cp.returncode, json.loads(cp.stdout)


def case(label: str, mutate, expect: int, expect_kind: str | None) -> bool:
    with tempfile.TemporaryDirectory(prefix="ledger-probe-",
                                     ignore_cleanup_errors=True) as tmp:
        kit, root = make_kit(Path(tmp))
        mutate(kit, root)
        git(kit, "add", "-A")
        git(kit, "-c", "commit.gpgsign=false", "commit", "-m", "mutate")
        code, payload = guard(root)
        kinds = sorted({item["kind"] for item in payload["errors"]})
        ok = code == expect and (expect_kind is None or expect_kind in kinds)
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        print(f"      exit={code} expected={expect} kinds={kinds} "
              f"base_commit={payload.get('base_commit', '')[:12]}")
        for check in payload.get("checks", []):
            print(f"      {check['path']}: {check['detail']}")
        return ok


def main() -> int:
    results = []

    def append(kit, root):
        rows = chain() + [event(3, "APPEND", chain()[-1]["hash"], {"n": 3})]
        (root / "ledger" / "primary.jsonl").write_bytes(encode(rows))

    def rewrite(kit, root):
        rows = chain()
        rows[0]["payload"] = {"n": 999}
        rows[0]["hash"] = event(1, "SEED_1", "GENESIS", {"n": 999})["hash"]
        rows[1]["prev_hash"] = rows[0]["hash"]
        rows[1]["hash"] = event(2, "SEED_2", rows[1]["prev_hash"],
                                rows[1]["payload"])["hash"]
        (root / "ledger" / "primary.jsonl").write_bytes(encode(rows))

    def truncate(kit, root):
        path = root / "ledger" / "primary.jsonl"
        path.write_bytes(path.read_bytes().split(b"\n", 1)[0] + b"\n")

    def delete(kit, root):
        (root / "ledger" / "supervision.jsonl").unlink()

    def newfile(kit, root):
        (root / "ledger" / "extra.jsonl").write_bytes(encode(chain(1)))

    results.append(case("legal append", append, 0, None))
    results.append(case("rewritten history (re-hashed)", rewrite, 2, "history"))
    results.append(case("truncated history", truncate, 2, "history"))
    results.append(case("deleted ledger file", delete, 2, "deleted"))
    results.append(case("brand-new ledger file", newfile, 2, "new"))

    print()
    print(f"probe summary: {sum(results)}/{len(results)} cases behaved as expected")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
