"""PILOT-058 probe: REVIEW.json shape and the merge-check staleness decision.

Runs the real CLI against throw-away tower roots and then calls the gate helper
directly, so the transcript shows exactly what ``checkback`` writes and how
``merge-check`` decides "fresh" vs "stale" vs "legacy".

    python -B scratch/review_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS = WORKTREE / "tower-dsh" / "tools"
TCLI = TOOLS / "towerctl.py"
sys.path.insert(0, str(TOOLS))
import towerctl  # noqa: E402  (the probe reads the gate helper it documents)

TASK = "T-PROBE-058"
BASE_SHA = "1" * 40
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_IDENTITY}
    return subprocess.run(list(args), cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def make_tower(base: Path) -> Path:
    root = base / "tower"
    worktree = root / f"pilot/worktrees/{TASK}"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(worktree), capture_output=True)
    (worktree / "reviewed.txt").write_text("reviewed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(worktree), capture_output=True)
    subprocess.run(["git", "-c", "user.name=Probe", "-c",
                    "user.email=probe@example.invalid", "commit", "-m", "impl"],
                   cwd=str(worktree), capture_output=True)
    write_json(root / "primary/CURRENT_STATE.json",
               {"schema": "tower/current-state@1", "role": "primary",
                "primary": {"id": "ctl-probe"}, "owner": {"name": "mac"}})
    write_json(root / "primary/TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    (root / "ledger").mkdir(parents=True)
    (root / "ledger/primary.jsonl").touch()
    write_json(root / f"tasks/{TASK}/record.json", {
        "schema": "tower/task@1", "id": TASK, "title": "probe", "status": "delivered",
        "executor": "exec-a", "worktree": f"pilot/worktrees/{TASK}",
        "dispatch": {"executor": "exec-a", "base_sha": BASE_SHA},
        "evidence": [], "review": None,
    })
    return root


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return run(root, sys.executable, "-B", str(TCLI), "--root", str(root), *args)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pilot-058-probe-") as tmp:
        root = make_tower(Path(tmp))
        head = subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=str(root / f"pilot/worktrees/{TASK}"),
                              capture_output=True, text=True).stdout.strip()
        print("worktree HEAD:", head)

        cp = cli(root, "checkback", "--task", TASK, "--reviewer", "rev-probe",
                 "--verdict", "PASS", "--scope", "tools/towerctl.py",
                 "--finding", "review bound at head", "--note", "probe")
        print("checkback exit:", cp.returncode)
        review_path = root / f"tasks/{TASK}/REVIEW.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        print("REVIEW.json:", json.dumps(review, ensure_ascii=False, indent=2))

        env = {"implementation_head_sha": head}
        print("fresh head ->", towerctl.review_binding_check(root, env, TASK))
        stale_env = {"implementation_head_sha": "f" * 40}
        print("stale head ->", towerctl.review_binding_check(root, stale_env, TASK))

        cp = cli(root, "checkback", "--task", TASK, "--reviewer", "rev-probe",
                 "--verdict", "FAIL", "--head", head, "--base", BASE_SHA)
        failed = json.loads(review_path.read_text(encoding="utf-8"))
        print("FAIL checkback exit:", cp.returncode,
              "verdict:", failed["verdict"])
        print("FAIL verdict ->", towerctl.review_binding_check(root, env, TASK))

        review["verdict"] = "PASS"
        write_json(review_path, review)
        review_path.unlink()
        print("missing ->", towerctl.review_binding_check(root, env, TASK))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
