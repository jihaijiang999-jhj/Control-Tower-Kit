"""PILOT-063 base-side envelope probe (offline, throw-away repositories).

Builds a repository whose main branch carries the envelope commit and whose
implementation branch carries only code, then drives the real ``towerctl``:

1. checkback -> accept -> envelope-new --base-side -> queue-add -> merge-check
   must all exit 0 (the envelope is on base, the branch head is the
   implementation, review.head is the implementation);
2. a new implementation-branch commit makes merge-check exit 2 on
   ``branch head == implementation head`` (MERGED is never written).

Prints one observation per line; ``probe.txt`` is this script's output.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOWER = Path(__file__).resolve().parents[1] / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
TASK = "PILOT-063"
ENVELOPE = "ENV-PILOT-063"
ENVELOPE_PATH = f"merge-envelopes/{ENVELOPE}.json"
BRANCH = "pilot/PILOT-063"
NOW = "2026-11-02T00:00:00+08:00"
GIT_ID = {
    "GIT_AUTHOR_NAME": "Tower Probe", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run(cmd: list[str], cwd: Path,
        extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_ID, "PYTHONIOENCODING": "utf-8"}
    env.update(extra or {})
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", env=env)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args], repo)


def git_ok(repo: Path, *args: str) -> str:
    cp = git(repo, *args)
    if cp.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {cp.stderr}")
    return cp.stdout.strip()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return run([sys.executable, "-B", str(TCLI), "--root", str(root), *args],
               TOWER)


def build(kit: Path, root: Path) -> tuple[str, str, str]:
    """main: base -> envelope; pilot branch: implementation only."""
    kit.mkdir(parents=True, exist_ok=True)
    git_ok(kit, "init")
    git_ok(kit, "symbolic-ref", "HEAD", "refs/heads/main")
    (kit / "README.md").write_text("base\n", encoding="utf-8")
    git_ok(kit, "add", "--", "README.md")
    git_ok(kit, "-c", "commit.gpgsign=false", "commit", "-m", "base")
    base = git_ok(kit, "rev-parse", "HEAD")
    git_ok(kit, "checkout", "-b", BRANCH)
    (kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
    git_ok(kit, "add", "--", "feature.txt")
    git_ok(kit, "-c", "commit.gpgsign=false", "commit", "-m", "implementation")
    impl = git_ok(kit, "rev-parse", "HEAD")
    git_ok(kit, "checkout", "main")
    write_json(kit / ENVELOPE_PATH, {"envelope_id": ENVELOPE})
    git_ok(kit, "add", "--", ENVELOPE_PATH)
    git_ok(kit, "-c", "commit.gpgsign=false", "commit", "-m", "envelope on main")
    envelope_head = git_ok(kit, "rev-parse", "HEAD")
    evidence = root / "tasks" / TASK / "evidence"
    evidence.mkdir(parents=True)
    proof = evidence / "proof.txt"
    proof.write_text("probe evidence\n", encoding="utf-8")
    write_json(root / "tasks" / TASK / "ACCEPTANCE.json", {
        "schema": "tower/acceptance@1",
        "items": [{"id": "A-01", "kind": "auto", "status": "passed",
                   "note": "probe"}]})
    write_json(root / "tasks" / TASK / "record.json", {
        "schema": "tower/task@1", "id": TASK, "title": "base-side probe",
        "status": "delivered", "authority": "workspace_write",
        "scope": ["probe"], "allowed_paths": ["tools/towerctl.py"],
        "forbidden": ["merge"], "acceptance": ["probe"], "depends_on": [],
        "worktree": f"pilot/worktrees/{TASK}", "executor": "exec-probe",
        "dispatch": {"executor": "exec-probe",
                     "worktree": f"pilot/worktrees/{TASK}",
                     "base_sha": base, "at": NOW},
        "evidence": [{"id": "E-001",
                      "path": f"tasks/{TASK}/evidence/proof.txt",
                      "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                      "bytes": proof.stat().st_size, "at": NOW}],
        "review": None, "decision": None, "closeout": None,
        "created_at": NOW, "updated_at": NOW, "next": "probe"})
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "role": "primary",
        "primary": {"id": "ctl-probe"}, "owner": {"name": "mac"},
        "phase": "PROBE"})
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "PROBE", "supervisor": {"id": "sup-probe"}})
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})
    return base, impl, envelope_head


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pilot063-probe-") as tmp:
        kit = Path(tmp) / "kit"
        root = kit / "tower-dsh"
        base, impl, envelope_head = build(kit, root)
        steps = []

        def step(label: str, cp: subprocess.CompletedProcess) -> None:
            steps.append((label, cp.returncode, cp))
            print(f"{label}: exit {cp.returncode}")

        step("checkback", cli(root, "checkback", "--task", TASK,
                              "--reviewer", "rev-probe", "--verdict", "PASS",
                              "--head", impl, "--base", base))
        step("accept", cli(root, "accept", "--task", TASK,
                           "--decision", "D-PROBE"))
        write_json(root / "envelope.json", {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE,
            "task": TASK, "repository": "..", "branch": BRANCH, "base": "main",
            "envelope_path": ENVELOPE_PATH,
            "implementation_head_sha": impl,
            "tests_baseline": 1, "tower_tests_baseline": 1})
        step("envelope-new --base-side", cli(
            root, "envelope-new", "--task", TASK,
            "--file", str(root / "envelope.json"), "--base-side"))
        step("queue-add", cli(root, "queue-add", "--envelope", ENVELOPE))
        clean = cli(root, "merge-check", "--envelope", ENVELOPE)
        step("merge-check (base-side)", clean)
        envelope = json.loads(
            (root / "supervision" / "envelopes" / f"{ENVELOPE}.json").read_text(
                encoding="utf-8"))
        print("record: head == envelope commit:",
              envelope.get("head") == envelope_head,
              "| base_side:", envelope.get("base_side"),
              "| impl == branch head:", envelope.get("implementation_head_sha") == impl)
        if clean.returncode == 0:
            failing = [c["name"] for c in json.loads(clean.stdout)["checks"]
                       if not c["ok"]]
            print("merge-check failing checks:", failing)
        moved = git(kit, "checkout", BRANCH)
        (kit / "feature.txt").write_text("moved\n", encoding="utf-8")
        git_ok(kit, "add", "--", "feature.txt")
        git_ok(kit, "-c", "commit.gpgsign=false", "commit", "-m", "extra")
        moved_head = git_ok(kit, "rev-parse", "HEAD")
        git_ok(kit, "checkout", "main")
        refused = cli(root, "merge-check", "--envelope", ENVELOPE)
        step("merge-check after branch head moved", refused)
        details = [c["detail"] for c in json.loads(refused.stdout)["errors"]
                   if c["name"] == "branch head == implementation head"]
        print("branch head moved:", moved_head, "| impl:", impl,
              "| refusal detail:", details[0] if details else "(none)")
        merged = "MERGED" in (refused.stdout + refused.stderr)
        print("zero MERGED after refusal:", not merged,
              "| git checkout:", moved.returncode == 0)
        ok = (all(code == 0 for _, code, _ in steps[:5])
              and clean.returncode == 0 and refused.returncode == 2 and not merged)
        print("PROBE:", "PASS" if ok else "FAIL")
        return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
