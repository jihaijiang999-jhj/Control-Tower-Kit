"""PILOT-076 offline probe: the owner-approval rule matrix (no gh, no network).

Two halves, both driven through the real code paths:

* ``authority-check`` on throw-away tower roots, for the configured-login rules;
* :func:`tower_merge.owner_approval_gate` with its ``gh pr view`` call replaced
  by an in-process fake and the checker supplied exactly as ``tower_cli``
  supplies it, for the three merge refusals and the accept case -- nothing here
  spawns ``gh`` or touches GitHub.

    python -B scratch/owner_probe.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOOLS = WORKTREE / "tower-dsh" / "tools"
TCLI = TOOLS / "towerctl.py"
sys.path.insert(0, str(TOOLS))

import tower_cli  # noqa: E402  (TOOLS must lead sys.path)
import tower_merge  # noqa: E402
from tower_common import MergeBlocked  # noqa: E402

OWNER = "jihaijiang999-jhj"
PRIMARY = "tower-primary"
LOGINS = (OWNER, PRIMARY)

CHECKS: list[bool] = []


class FakeSubprocess:
    """Stands in for the ``subprocess`` module inside ``tower_merge``."""

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout

    def run(self, argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, self.stdout, "")


class Args:
    """The subset of the CLI namespace the merge gate reads."""

    def __init__(self, root: Path) -> None:
        self.root = str(root)
        self.owner_approval = lambda stdout: tower_cli.owner_approval_errors(
            LOGINS, stdout)


def write_state(root: Path, owner: str = "", primary: str = "") -> None:
    (root / "primary").mkdir(parents=True, exist_ok=True)
    (root / "primary" / "CURRENT_STATE.json").write_text(json.dumps({
        "schema": "tower/current-state@1", "tower_id": "tower-probe",
        "role": "primary", "primary": {"id": "ctl-076"},
        "owner": {"name": "mac"}}), encoding="utf-8")
    if owner or primary:
        path = root / "shared" / "AUTHORITY_MODEL.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": "tower/authority-model@1",
            "roles": {"owner": {"name": "mac", "github_login": owner},
                      "primary_control_tower": {"github_login": primary}},
        }, indent=2) + "\n", encoding="utf-8")


def authority_check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), "authority-check"],
        capture_output=True, text=True, encoding="utf-8")


def report(label: str, ok: bool, detail: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    CHECKS.append(ok)


def gate_payload(author: str, approvers: list[str]) -> str:
    return json.dumps({
        "author": {"login": author},
        "reviews": [{"author": {"login": login}, "state": "APPROVED"}
                    for login in approvers],
    })


def probe_gate(root: Path, label: str, task: str, author: str,
               approvers: list[str], expect: str) -> None:
    outcome, detail = "ACCEPT", "merged"
    with mock.patch.object(tower_merge, "subprocess",
                           FakeSubprocess(gate_payload(author, approvers))):
        try:
            tower_merge.owner_approval_gate(root, {"task": task}, 77,
                                            Args(root), 5)
        except MergeBlocked as exc:
            outcome, detail = "REFUSE", exc.detail
    report(label, outcome == expect, f"{outcome}: {detail}")


def probe_git_author(root: Path, label: str, git_name: str,
                     expect: str) -> None:
    """PILOT-076: the writer's git author must name the registered owner."""
    subprocess.run(["git", "-C", str(root), "init"],
                   capture_output=True, text=True, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "config", "user.name", git_name],
                   capture_output=True, text=True, encoding="utf-8")
    args = type("WriterArgs", (), {"cmd": "accept", "by": None})()
    outcome, detail = "ACCEPT", "stamped"
    try:
        tower_cli.stamp_authority_identity(root, args)
    except SystemExit as exc:
        outcome, detail = "REFUSE", f"exit {exc.code}"
    report(label, outcome == expect, f"{outcome}: {detail}")


def main() -> int:
    os.environ["TOWERCTL_GH"] = sys.executable
    with tempfile.TemporaryDirectory(prefix="owner-probe-") as tmp:
        root = Path(tmp) / "tower"
        write_state(root, OWNER, PRIMARY)
        print(f"owner={OWNER} primary={PRIMARY} gate_boundary=PILOT-077")

        probe_gate(root, "no owner APPROVED review", "PILOT-077",
                   "author-x", ["reviewer-y"], "REFUSE")
        probe_gate(root, "owner approves its own PR", "PILOT-077",
                   OWNER, [OWNER], "REFUSE")
        probe_gate(root, "primary tower login approves", "PILOT-077",
                   "author-x", [PRIMARY], "REFUSE")
        probe_gate(root, "owner APPROVED and distinct", "PILOT-077",
                   "author-x", [OWNER], "ACCEPT")
        probe_gate(root, "PILOT-076 legacy bootstrap", "PILOT-076",
                   "author-x", [], "ACCEPT")

        probe_git_author(root, "git author 'mac (jihaijiang999-jhj)'",
                         "mac (jihaijiang999-jhj)", "ACCEPT")
        probe_git_author(root, "git author 'mallory'", "mallory", "REFUSE")

        for label, owner, primary, expect in (
                ("valid owner/primary logins", OWNER, PRIMARY, 0),
                ("missing owner github_login", "", PRIMARY, 2),
                ("missing primary github_login", OWNER, "", 2),
                ("equal owner/primary logins", OWNER, OWNER, 2)):
            case = Path(tmp) / f"tower-{len(CHECKS)}"
            write_state(case, owner, primary)
            cp = authority_check(case)
            detail = " ".join(line.strip() for line in cp.stdout.splitlines()
                              if "github_login" in line) or "ok"
            report(label, cp.returncode == expect,
                   f"exit {cp.returncode} {detail}")

    passed = sum(1 for item in CHECKS if item)
    print(f"\n{passed}/{len(CHECKS)} probe checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
