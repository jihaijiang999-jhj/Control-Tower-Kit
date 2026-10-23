"""PILOT-034 probe: exercise the merged-gate matrix on throw-away towers.

Read-only with respect to the real tower: every scenario builds its own
temporary kit under the OS temp directory.  Each scenario asserts the expected
exit code / failing check / passing check, then a compact matrix is printed.

    python -B evidence/probe_merge_gate.py > evidence/merge-gate-probe.txt
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TCLI = WORKTREE / "tower-dsh" / "tools" / "towerctl.py"

TASK = "T-BASE-001"
ENVELOPE = "ENV-BASE-001"
LEGACY_ENVELOPE = "ENV-LEGACY-001"
COPY_ID = "ENV-COPY-001"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "feature/baseline"
FIXED_TIME = "2026-10-22T00:00:00+08:00"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Probe",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}
RESULTS: list[tuple[str, bool, str]] = []


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


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env)


class Kit:
    def __init__(self, base: Path) -> None:
        self.kit = base / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        (self.root / "ledger" / "supervision.jsonl").touch()
        proof = self.root / "tasks" / TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        write_json(self.root / "tasks" / TASK / "record.json", {
            "schema": "tower/task@1", "id": TASK, "title": "baseline gate",
            "status": "accepted", "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{"id": "E-001",
                          "path": f"tasks/{TASK}/evidence/proof.txt",
                          "sha256": sha256(proof.read_bytes()).hexdigest(),
                          "bytes": proof.stat().st_size, "at": FIXED_TIME}],
        })
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-primary"},
            "owner": {"name": "mac"}, "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "role": "supervision",
            "phase": "TEST", "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.init_repo()

    # -- git fixture -----------------------------------------------------
    def git(self, *args: str) -> subprocess.CompletedProcess:
        return run_git(self.kit, *args)

    def commit_all(self, message: str) -> str:
        self.git("add", "-A")
        commit = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        assert commit.returncode == 0, commit.stdout + commit.stderr
        return self.git("rev-parse", "HEAD").stdout.strip()

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

    # -- tower state helpers --------------------------------------------
    def payload(self, **overrides) -> dict:
        data = {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 1, "tower_tests_baseline": 1,
        }
        data.update(overrides)
        return data

    def write_envelope(self, env: dict, name: str = ENVELOPE) -> None:
        write_json(self.root / "supervision" / "envelopes" / f"{name}.json", env)

    def handwrite_queue(self, name: str = ENVELOPE) -> None:
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": name, "task": TASK,
                         "branch": BRANCH, "base": "main",
                         "status": "WAITING", "added_at": FIXED_TIME}],
        })

    def supervision_ledger(self) -> str:
        return (self.root / "ledger" / "supervision.jsonl").read_text(
            encoding="utf-8")

    def append_forged_queue_add(self, name: str = ENVELOPE) -> None:
        path = self.root / "ledger" / "supervision.jsonl"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        event = {
            "seq": (rows[-1].get("seq", 0) + 1) if rows else 1,
            "at": FIXED_TIME, "type": "QUEUE_ADD", "actor": "primary",
            "payload": {"envelope": name, "task": TASK},
            "prev_hash": (rows[-1].get("hash") if rows else None) or "GENESIS",
            "hash": "f" * 64,
        }
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def new_envelope(self) -> dict:
        env = self.payload()
        write_json(self.root / "envelope.json", env)
        return env


def parse(cp: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(cp.stdout)
    except ValueError:
        return {"raw": cp.stdout + cp.stderr}


def record(label: str, ok: bool, detail: str) -> None:
    RESULTS.append((label, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def scenario(name: str, fn) -> None:
    with tempfile.TemporaryDirectory(prefix=f"pilot034-{name}-") as tmp:
        try:
            fn(Kit(Path(tmp)))
        except AssertionError as exc:
            record(name, False, f"assertion failed: {exc}")


def sc_normal(kit: Kit) -> None:
    # Write the payload first, then drive the real CLI.
    kit.new_envelope()
    cp = run_cli(kit.root, "envelope-new", "--task", TASK,
                 "--file", str(kit.root / "envelope.json"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    cp = run_cli(kit.root, "queue-add", "--envelope", ENVELOPE)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    cp = run_cli(kit.root, "merge-check", "--envelope", ENVELOPE)
    payload = parse(cp)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    checks = {c["name"]: c for c in payload["checks"]}
    wanted = ("envelope identity matches request", "ledger chain intact",
              "envelope_new recorded", "queue entry backed by ledger")
    for label in wanted:
        assert label in checks and checks[label]["ok"], f"{label}: {checks.get(label)}"
    record("normal flow (envelope-new + queue-add)",
           True, "merge-check exit 0; identity/chain/envelope_new/queue all ok")


def sc_forged(kit: Kit) -> None:
    kit.new_envelope()
    cp = run_cli(kit.root, "envelope-new", "--task", TASK,
                 "--file", str(kit.root / "envelope.json"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    kit.handwrite_queue()
    kit.append_forged_queue_add()
    cp = run_cli(kit.root, "merge-check", "--envelope", ENVELOPE)
    payload = parse(cp)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    names = [c["name"] for c in payload["errors"]]
    assert names == ["ledger chain intact"], str(names)
    detail = payload["errors"][0]["detail"]
    assert detail.startswith("supervision: "), detail
    cp = run_cli(kit.root, "verify-ledger", "--ledger", "supervision")
    assert cp.returncode == 2, cp.stdout + cp.stderr
    record("forged QUEUE_ADD row (broken hash chain)", True,
           "merge-check exit 2; failing=ledger chain intact "
           f"({detail.split(': ', 1)[1]}); verify-ledger exit 2")


def sc_missing_new(kit: Kit) -> None:
    kit.write_envelope({**kit.payload(), "envelope_head_sha": kit.envelope_head,
                        "status": "DRAFT"})
    cp = run_cli(kit.root, "queue-add", "--envelope", ENVELOPE)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "QUEUE_ADD" in kit.supervision_ledger()
    assert "ENVELOPE_NEW" not in kit.supervision_ledger()
    cp = run_cli(kit.root, "merge-check", "--envelope", ENVELOPE)
    payload = parse(cp)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    names = [c["name"] for c in payload["errors"]]
    assert names == ["envelope_new recorded"], str(names)
    assert payload["errors"][0]["detail"] == "ENVELOPE_NEW event missing"
    record("QUEUE_ADD without ENVELOPE_NEW", True,
           "merge-check exit 2; failing=envelope_new recorded "
           "(ENVELOPE_NEW event missing)")


def sc_copied(kit: Kit) -> None:
    kit.new_envelope()
    cp = run_cli(kit.root, "envelope-new", "--task", TASK,
                 "--file", str(kit.root / "envelope.json"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    cp = run_cli(kit.root, "queue-add", "--envelope", ENVELOPE)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    source = kit.root / "supervision" / "envelopes" / f"{ENVELOPE}.json"
    kit.write_envelope(read_json(source), COPY_ID)
    queue = read_json(kit.root / "supervision" / "MERGE_QUEUE.json")
    queue["entries"].append({"envelope_id": COPY_ID, "task": TASK,
                             "branch": BRANCH, "base": "main",
                             "status": "WAITING", "added_at": FIXED_TIME})
    write_json(kit.root / "supervision" / "MERGE_QUEUE.json", queue)
    cp = run_cli(kit.root, "merge-check", "--envelope", COPY_ID)
    payload = parse(cp)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    blob = json.dumps(payload)
    assert "envelope identity matches request" in blob, blob
    assert ENVELOPE in blob and COPY_ID in blob, blob
    record("copied envelope content under a new id", True,
           "merge-check exit 2; failing=envelope identity matches request "
           f"(file declares {ENVELOPE}, request {COPY_ID})")


def sc_legacy(kit: Kit) -> None:
    kit.write_envelope({
        "schema": "tower/merge-envelope@1", "envelope_id": LEGACY_ENVELOPE,
        "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
        "envelope_path": ENVELOPE_PATH,
        "implementation_head_sha": kit.implementation_head,
        "envelope_head_sha": kit.envelope_head, "status": "DRAFT",
    }, LEGACY_ENVELOPE)
    kit.handwrite_queue(LEGACY_ENVELOPE)
    cp = run_cli(kit.root, "merge-check", "--envelope", LEGACY_ENVELOPE)
    payload = parse(cp)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    names = [c["name"] for c in payload["checks"]]
    for absent in ("ledger chain intact", "envelope_new recorded",
                   "queue entry backed by ledger"):
        assert absent not in names, names
    record("legacy envelope (no baselines)", True,
           "merge-check exit 0; the three new-style checks are absent")


def main() -> int:
    print("PILOT-034 merge-gate probe matrix (temp towers only)")
    print(f"tool={TCLI}")
    print()
    for name, fn in (("normal", sc_normal), ("forged", sc_forged),
                     ("missing-envelope-new", sc_missing_new),
                     ("copied-id", sc_copied), ("legacy", sc_legacy)):
        scenario(name, fn)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print()
    print(f"PROBE RESULT: {passed}/{len(RESULTS)} scenarios as expected")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
