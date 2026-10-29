"""PILOT-047 probe: reproduce the position model, E8/E9 and the four injections.

Runs the real worktree tower plus throw-away fixtures and prints one PASS/FAIL
line per claim; exits 1 when any claim fails.

    python -B scratch/position_probe.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
TOWER = WORKTREE / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
ROADMAP = ("PILOT-045", "PILOT-046", "PILOT-047",
           "PILOT-048", "PILOT-049", "PILOT-050")
CURRENT = "PILOT-047"
CAMPAIGN = "command/campaigns/C-2026-Q4-01.md"
STATUSES = {"done", "active", "blocked", "planned", "skipped"}
RESULTS: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """Record and print one probe claim."""
    RESULTS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" :: {detail}" if detail else ""))


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data) -> None:
    write(path, json.dumps(data, ensure_ascii=False, indent=2))


def campaign_text(roadmap=ROADMAP, current=CURRENT,
                  task_forces=("PILOT-045", "PILOT-046", "PILOT-047")) -> str:
    lines = ["---", "schema: tower/campaign@1", "id: C-2026-Q4-01",
             "goal: G2", "status: active", "owner: mac",
             'objective: "双视图位置图"']
    if roadmap is not None:
        lines.append("roadmap:")
        lines += [f"  - {task_id}" for task_id in roadmap]
    if current is not None:
        lines.append(f"current: {current}")
    lines += ["task_forces:"] + [f"  - {task_id}" for task_id in task_forces]
    lines += ['sequence: "045 → 050"', "stop_conditions:",
              '  - "drift != 0 立即停"', 'budget: "3 张卡 / 2 周"',
              "wip_limit: 1", "review_by: 2026-12-31", "---",
              "# C-2026-Q4-01 — 双视图位置图", ""]
    return "\n".join(lines)


def fixture(tmp: str, campaign: str | None = None) -> Path:
    """A throw-away tower: 045/046 closed, 047 spec-only, 048-050 uncreated."""
    root = Path(tmp) / "tower"
    write(root / "command/STRATEGY.md",
          "---\nschema: tower/strategy@1\nid: S-2026-Q4\nowner: mac\n"
          "status: active\nreview_by: 2099-12-31\ngoals:\n  - id: G2\n"
          "    text: 全局指挥\n---\n# 战略\n")
    if campaign is not None:
        write(root / CAMPAIGN, campaign)
    write_json(root / "primary/TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "primary/CURRENT_STATE.json",
               {"schema": "tower/current-state@1", "owner": {"name": "mac"}})
    for task_id in ("PILOT-045", "PILOT-046"):
        write_json(root / "tasks" / task_id / "record.json", {
            "schema": "tower/task@1", "id": task_id, "title": f"{task_id} 卡",
            "status": "closed", "next": "", "review": {"verdict": "PASS"}})
    write_json(root / "pilot/PILOT-047.spec.json",
               {"id": CURRENT, "title": "双视图位置图"})
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    return root


def probe_live() -> None:
    """The real worktree: JSON/human/Markdown views and brief progress."""
    print("== live worktree: where / brief ==")
    cp = run(TOWER, "where", "--json")
    data = json.loads(cp.stdout)
    check("where --json exit 0", cp.returncode == 0, str(cp.returncode))
    check("schema tower/position@1", data.get("schema") == "tower/position@1")
    check("index=2 total=6", (data["index"], data["total"]) == (2, 6),
          f"{data['index']}/{data['total']}")
    check("current=next=PILOT-047",
          data["current"] == data["next"] == CURRENT,
          f"{data['current']} -> {data['next']}")
    check("nodes follow roadmap order",
          [node["id"] for node in data["nodes"]] == list(ROADMAP))
    check("statuses are enum values",
          {node["status"] for node in data["nodes"]} <= STATUSES,
          str([node["status"] for node in data["nodes"]]))
    check("keys are sorted", list(data.keys()) == sorted(data.keys()))
    human = run(TOWER, "where").stdout.splitlines()
    check("human <= 20 lines", len(human) <= 20, str(len(human)))
    check("human bar", "[✅045][✅046][▶047][ 048][ 049][ 050]" in human)
    check("human position line", "位置 2/6 · 下一站 047" in human)
    check("human five parts",
          all(any(line.startswith(label) for line in human)
              for label in ("为什么：", "交付：", "风险：", "建议：")))
    marked = run(TOWER, "where", "--md").stdout.splitlines()
    check("--md wraps the same content", marked[2:] == human)
    check("--md heading", marked[:2] == ["## 位置", ""])
    brief = run(TOWER, "brief").stdout
    check("brief progress 2/6", "2/6 closed" in brief)


def probe_validation() -> None:
    """E8: missing/empty/duplicate/outside current; E9: no active campaign."""
    print("== E8 / E9 ==")
    cases = {
        "roadmap missing": campaign_text(roadmap=None),
        "roadmap empty": campaign_text(roadmap=()),
        "roadmap duplicate": campaign_text(
            roadmap=("PILOT-045", "PILOT-045", "PILOT-047")),
        "current outside roadmap": campaign_text(current="PILOT-999"),
    }
    for label, text in cases.items():
        with tempfile.TemporaryDirectory(prefix="probe-e8-") as tmp:
            root = fixture(tmp, text)
            cp = run(root, "where", "--json")
            data = json.loads(cp.stdout)
            check(f"E8 {label}: exit 2", cp.returncode == 2, str(cp.returncode))
            check(f"E8 {label}: code",
                  any("E8" in error for error in data.get("errors", [])),
                  str(data.get("errors")))
            check(f"E8 {label}: no Traceback",
                  "Traceback" not in cp.stdout + cp.stderr)
    with tempfile.TemporaryDirectory(prefix="probe-e9-") as tmp:
        root = fixture(tmp, None)
        cp = run(root, "where", "--json")
        data = json.loads(cp.stdout)
        check("E9 no campaign: exit 2", cp.returncode == 2, str(cp.returncode))
        check("E9 no campaign: code",
              any("E9" in error for error in data.get("errors", [])))
        check("E9 no campaign: no Traceback",
              "Traceback" not in cp.stdout + cp.stderr)


def probe_injections() -> None:
    """checkback / status-snapshot / close / post-merge carry the position."""
    print("== injections ==")
    with tempfile.TemporaryDirectory(prefix="probe-inject-") as tmp:
        root = fixture(tmp, campaign_text())
        write_json(root / "tasks" / CURRENT / "record.json", {
            "schema": "tower/task@1", "id": CURRENT, "title": "位置图",
            "status": "delivered", "next": "", "review": None})
        cp = run(root, "checkback", "--task", CURRENT,
                 "--reviewer", "probe-reviewer", "--verdict", "PASS")
        data = json.loads(cp.stdout)
        review = (root / "tasks" / CURRENT / "REVIEW.md").read_text(
            encoding="utf-8")
        check("checkback position object", data.get("position", {}).get("index") == 2)
        check("checkback REVIEW ## Position", "## Position" in review)
        cp = run(root, "status-snapshot", "--task", CURRENT, "--event", "note",
                 "--at", "2026-10-29T10:00:00")
        text = (root / "status/2026-10-29.md").read_text(encoding="utf-8")
        check("status-snapshot position line", "- position: 2/6" in text)
        evidence = root / "delivery.md"
        write(evidence, "delivered\n")
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        write(root / "tasks" / CURRENT / "TASK.md", f"# {CURRENT} — 位置图\n")
        write_json(root / "tasks" / CURRENT / "record.json", {
            "schema": "tower/task@1", "id": CURRENT, "title": "位置图",
            "status": "accepted", "executor": "probe",
            "evidence": [{"path": "delivery.md", "sha256": digest}],
            "review": {"verdict": "PASS", "reviewer": "probe-reviewer"},
            "decision": {"id": "D-PROBE", "actor": "owner"}})
        cp = run(root, "close", "--task", CURRENT)
        data = json.loads(cp.stdout)
        check("close exit 0", cp.returncode == 0, cp.stderr)
        check("close position object", data.get("position", {}).get("total") == 6)
    with tempfile.TemporaryDirectory(prefix="probe-post-") as tmp:
        root = fixture(tmp, campaign_text())
        envelope = "ENV-PILOT-047"
        write_json(root / "supervision/envelopes" / f"{envelope}.json", {
            "schema": "tower/merge-envelope@1", "id": envelope,
            "status": "MERGED", "repository": ".", "base": "main",
            "implementation_head_sha": "0" * 40,
            "envelope_path": f"supervision/envelopes/{envelope}.json"})
        cp = run(root, "post-merge", "--envelope", envelope)
        data = json.loads(cp.stdout)
        check("post-merge position object",
              data.get("position", {}).get("current") == CURRENT)


def probe_legacy() -> None:
    """A roadmap-less campaign keeps the pre-047 output (no position key)."""
    print("== legacy compatibility ==")
    with tempfile.TemporaryDirectory(prefix="probe-legacy-") as tmp:
        root = fixture(tmp, campaign_text(roadmap=None, current=None,
                                          task_forces=("PILOT-045",)))
        write_json(root / "tasks" / CURRENT / "record.json", {
            "schema": "tower/task@1", "id": CURRENT, "title": "位置图",
            "status": "delivered", "next": "", "review": None})
        cp = run(root, "checkback", "--task", CURRENT,
                 "--reviewer", "probe-reviewer", "--verdict", "PASS")
        data = json.loads(cp.stdout)
        review = (root / "tasks" / CURRENT / "REVIEW.md").read_text(
            encoding="utf-8")
        check("legacy checkback has no position key", "position" not in data)
        check("legacy REVIEW has no ## Position", "## Position" not in review)
        brief = run(root, "brief").stdout
        check("legacy brief falls back to task_forces", "1/1 closed" in brief)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    probe_live()
    probe_validation()
    probe_injections()
    probe_legacy()
    failed = RESULTS.count(False)
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
