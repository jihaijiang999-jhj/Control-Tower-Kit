"""Tests for PILOT-047: the dual-view position map (``where`` + injections).

Every case builds its own throw-away tower under the runner's ``TMP`` sandbox
and drives the real CLI through ``subprocess``, so exit codes and stdout are
observed exactly as a caller sees them::

    python -B tools/run_tests.py

The model cases mirror the live tower: ``PILOT-045``/``PILOT-046`` are closed,
``PILOT-047`` is the current card without a record and 048-050 are planned.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (TOOLS_DIR must be on sys.path first)

ROADMAP = ("PILOT-045", "PILOT-046", "PILOT-047",
           "PILOT-048", "PILOT-049", "PILOT-050")
CURRENT = "PILOT-047"
CAMPAIGN = "command/campaigns/C-2026-Q4-01.md"
STRATEGY = "command/STRATEGY.md"
STATUSES = {"done", "active", "blocked", "planned", "skipped"}
LABELS = ("为什么：", "交付：", "风险：", "建议：")


def day(offset: int) -> str:
    """An ISO date ``offset`` days from today, for review_by fixtures."""
    return (date.today() + timedelta(days=offset)).isoformat()


def strategy_text() -> str:
    """A minimal strategy carrying the campaign's goal."""
    return ("---\n"
            "schema: tower/strategy@1\n"
            "id: S-2026-Q4\n"
            "horizon: 2026-Q4\n"
            "owner: mac\n"
            "status: active\n"
            f"review_by: {day(60)}\n"
            "goals:\n"
            "  - id: G2\n"
            "    text: 全局指挥\n"
            "---\n"
            "# 战略正文\n")


def campaign_text(roadmap: tuple[str, ...] | None = ROADMAP,
                  current: str | None = CURRENT,
                  task_forces: tuple[str, ...] = ("PILOT-045", "PILOT-046",
                                                  "PILOT-047"),
                  goal: str = "G2", status: str = "active",
                  wip_limit: int = 1, budget: str = "3 张卡 / 2 周") -> str:
    """A campaign document; ``roadmap=None`` writes a pre-047 legacy campaign."""
    lines = ["---", "schema: tower/campaign@1", "id: C-2026-Q4-01",
             f"goal: {goal}", f"status: {status}", "owner: mac",
             'objective: "双视图位置图"', "key_results:", '  - "where exit 0"']
    if roadmap is not None:
        lines.append("roadmap:")
        lines += [f"  - {task_id}" for task_id in roadmap]
    if current is not None:
        lines.append(f"current: {current}")
    lines.append("task_forces:")
    lines += [f"  - {task_id}" for task_id in task_forces]
    lines += ['sequence: "045 → 050"', "stop_conditions:",
              '  - "drift != 0 立即停"', f'budget: "{budget}"',
              f"wip_limit: {wip_limit}", "review_by: 2026-12-31",
              "---", "# C-2026-Q4-01 — 双视图位置图", ""]
    return "\n".join(lines)


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


class PositionTowerCase(unittest.TestCase):
    """A throw-away tower shaped like the live 045-050 roadmap."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-position-", ignore_cleanup_errors=True)
        self.tower = Path(self._tmp.name) / "tower"
        self.write_doc(STRATEGY, strategy_text())
        self.write_doc(CAMPAIGN, campaign_text())
        self.write_board("PILOT-045", "PILOT-046")
        self.write_json("primary/CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "owner": {"name": "mac"},
            "next_action": "跑 047", "blockers": []})
        self.write_record("PILOT-045", "closed", "PASS")
        self.write_record("PILOT-046", "closed", "PASS")
        self.write_doc("pilot/PILOT-047.spec.json",
                       json.dumps({"id": "PILOT-047", "title": "双视图位置图"}))
        (self.tower / "ledger").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_doc(self, relpath: str, text: str) -> Path:
        path = self.tower / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relpath: str, data) -> Path:
        return self.write_doc(relpath, json.dumps(data, ensure_ascii=False,
                                                  indent=2))

    def write_record(self, task_id: str, status: str,
                     verdict: str | None = None) -> None:
        self.write_json(f"tasks/{task_id}/record.json", {
            "schema": "tower/task@1", "id": task_id, "title": f"{task_id} 卡",
            "status": status, "next": "等待处理",
            "review": {"verdict": verdict} if verdict else None})

    def write_board(self, *task_ids: str) -> None:
        self.write_json("primary/TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{"id": task_id, "status": "closed"}
                      for task_id in task_ids]})

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(self.tower, *args)

    def where_json(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.cli("where", "--json")
        return cp, json.loads(cp.stdout) if cp.stdout.strip() else {}

    def hashes(self) -> dict[str, str]:
        return {path.relative_to(self.tower).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.tower.rglob("*")) if path.is_file()}


class PositionModelCase(PositionTowerCase):
    """The position model: statuses, index/total, next, wip and sources."""

    def test_live_shape_is_index_two_of_six(self) -> None:
        cp, data = self.where_json()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(data["schema"], "tower/position@1")
        self.assertEqual(data["campaign"], "C-2026-Q4-01")
        self.assertEqual(data["goal"], "G2")
        self.assertEqual(data["index"], 2)
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["current"], CURRENT)
        self.assertEqual(data["next"], CURRENT)
        self.assertEqual([node["id"] for node in data["nodes"]], list(ROADMAP))
        self.assertEqual([node["status"] for node in data["nodes"]],
                         ["done", "done", "active", "planned", "planned",
                          "planned"])
        self.assertEqual(data["blocked"], [])
        self.assertEqual(data["wip"], {"in_flight": 0, "limit": 1})
        self.assertEqual(data["stop_conditions"], ["drift != 0 立即停"])
        self.assertEqual(data["sources"],
                         [CAMPAIGN, "primary/TASK_BOARD.json", "tasks"])

    def test_status_enum_is_fixed_and_keys_are_sorted(self) -> None:
        cp, data = self.where_json()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue({node["status"] for node in data["nodes"]} <= STATUSES)
        self.assertEqual(list(data.keys()), sorted(data.keys()))
        self.assertNotIn("at", data)
        self.assertEqual(cp.stderr, "")

    def test_current_without_record_is_active(self) -> None:
        _, data = self.where_json()
        node = next(item for item in data["nodes"] if item["id"] == CURRENT)
        self.assertEqual(node["status"], "active")

    def test_planned_nodes_need_no_record(self) -> None:
        _, data = self.where_json()
        statuses = {node["id"]: node["status"] for node in data["nodes"]}
        for task_id in ("PILOT-048", "PILOT-049", "PILOT-050"):
            self.assertEqual(statuses[task_id], "planned")

    def test_rework_marks_node_blocked(self) -> None:
        self.write_record("PILOT-048", "rework", "FAIL")
        _, data = self.where_json()
        self.assertEqual(data["blocked"], ["PILOT-048"])
        statuses = {node["id"]: node["status"] for node in data["nodes"]}
        self.assertEqual(statuses["PILOT-048"], "blocked")
        human = self.cli("where")
        self.assertIn("风险：阻塞：PILOT-048", human.stdout)
        self.assertIn("建议：先处理阻塞", human.stdout)

    def test_all_done_sets_index_to_total_and_next_to_null(self) -> None:
        for task_id in ROADMAP:
            self.write_record(task_id, "closed", "PASS")
        _, data = self.where_json()
        self.assertEqual(data["index"], data["total"])
        self.assertIsNone(data["next"])
        self.assertTrue(all(node["status"] == "done"
                            for node in data["nodes"]))

    def test_wip_counts_the_whole_tower(self) -> None:
        self.write_record("PILOT-099", "delivered")
        _, data = self.where_json()
        self.assertEqual(data["wip"]["in_flight"], 1)
        self.assertEqual(data["wip"]["limit"], 1)


class WhereViewCase(PositionTowerCase):
    """The human view: <=20 lines, position bar, x/y, next station, five parts."""

    def test_human_view_has_bar_position_and_next(self) -> None:
        cp = self.cli("where")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        lines = cp.stdout.splitlines()
        self.assertLessEqual(len(lines), 20)
        self.assertIn("[✅045][✅046][▶047][ 048][ 049][ 050]", lines)
        self.assertIn("位置 2/6 · 下一站 047", lines)
        for label in LABELS:
            self.assertTrue(any(line.startswith(label) for line in lines),
                            msg=lines)
        self.assertNotIn("{", cp.stdout)

    def test_md_view_wraps_the_same_content(self) -> None:
        human = self.cli("where")
        marked = self.cli("where", "--md")
        self.assertEqual(marked.returncode, 0, msg=marked.stdout + marked.stderr)
        lines = marked.stdout.splitlines()
        self.assertEqual(lines[:2], ["## 位置", ""])
        self.assertEqual(lines[2:], human.stdout.splitlines())
        self.assertLessEqual(len(lines), 20)

    def test_where_and_views_write_nothing(self) -> None:
        before = self.hashes()
        self.assertEqual(self.cli("where").returncode, 0)
        self.assertEqual(self.cli("where", "--json").returncode, 0)
        self.assertEqual(self.cli("where", "--md").returncode, 0)
        self.assertEqual(self.hashes(), before)


class PositionValidationCase(PositionTowerCase):
    """E8 (invalid roadmap/current) and E9 (no active campaign) exit 2 cleanly."""

    def assert_unavailable(self, code: str) -> dict:
        cp, data = self.where_json()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertFalse(data["ok"])
        self.assertTrue(any(code in error for error in data["errors"]),
                        msg=data["errors"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        return data

    def test_e8_missing_roadmap(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(roadmap=None))
        self.assert_unavailable("E8")
        self.assertIn("missing", json.dumps(
            self.where_json()[1], ensure_ascii=False))

    def test_e8_empty_roadmap(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(roadmap=()))
        self.assert_unavailable("E8")

    def test_e8_duplicate_roadmap_id(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(
            roadmap=("PILOT-045", "PILOT-045", "PILOT-047")))
        self.assert_unavailable("E8")

    def test_e8_current_not_in_roadmap(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(current="PILOT-999"))
        self.assert_unavailable("E8")

    def test_e9_without_any_campaign(self) -> None:
        (self.tower / CAMPAIGN).unlink()
        self.assert_unavailable("E9")

    def test_e9_without_an_active_campaign(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(status="closed"))
        self.assert_unavailable("E9")

    def test_campaign_check_e8_for_duplicate_roadmap(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(
            roadmap=("PILOT-045", "PILOT-045", "PILOT-047")))
        cp = self.cli("campaign-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertIn("E8", [finding["code"] for finding in data["errors"]])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)

    def test_campaign_check_e8_for_outside_current(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(current="PILOT-999"))
        cp = self.cli("campaign-check")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertIn("E8", [finding["code"] for finding in data["errors"]])

    def test_campaign_check_w4_lists_uncreated_roadmap_nodes(self) -> None:
        cp = self.cli("campaign-check")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertEqual(data["errors"], [])
        gaps = [finding["detail"] for finding in data["warnings"]
                if finding["code"] == "W4"]
        self.assertEqual(len(gaps), 3, msg=gaps)
        for task_id in ("PILOT-048", "PILOT-049", "PILOT-050"):
            self.assertTrue(any(task_id in item for item in gaps), msg=gaps)
        self.assertEqual(self.cli("campaign-check", "--strict").returncode, 2)

    def test_campaign_check_legacy_campaign_without_roadmap_stays_green(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(roadmap=None, current=None))
        cp = self.cli("campaign-check")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertEqual(data["errors"], [])
        self.assertNotIn("E8", [finding["code"] for finding in data["errors"]])


class InjectionCase(PositionTowerCase):
    """checkback / close / post-merge borrow the position object."""

    def test_checkback_adds_position_and_review_section(self) -> None:
        self.write_record(CURRENT, "delivered")
        cp = self.cli("checkback", "--task", CURRENT,
                      "--reviewer", "independent-reviewer", "--verdict", "PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertEqual(data["position"]["index"], 2)
        self.assertEqual(data["position"]["total"], 6)
        review = (self.tower / "tasks" / CURRENT / "REVIEW.md").read_text(
            encoding="utf-8")
        self.assertIn("## Position", review)
        self.assertIn("- 位置：2/6", review)

    def test_close_adds_position(self) -> None:
        evidence = "delivery.md"
        self.write_doc(evidence, "delivered\n")
        digest = hashlib.sha256((self.tower / evidence).read_bytes()).hexdigest()
        self.write_doc(f"tasks/{CURRENT}/TASK.md", f"# {CURRENT} — 位置图\n")
        self.write_json(f"tasks/{CURRENT}/record.json", {
            "schema": "tower/task@1", "id": CURRENT, "title": "位置图",
            "status": "accepted", "executor": "exec", "next": "closeout",
            "evidence": [{"path": evidence, "sha256": digest}],
            "review": {"verdict": "PASS", "reviewer": "rev"},
            "decision": {"id": "D-047", "actor": "owner"}})
        cp = self.cli("close", "--task", CURRENT)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertEqual(data["status"], "closed")
        self.assertEqual(data["position"]["current"], CURRENT)
        self.assertEqual(data["position"]["next"], "PILOT-048")
        self.assertEqual(data["position"]["index"], 3)

    def test_post_merge_adds_position(self) -> None:
        envelope = "ENV-PILOT-047"
        self.write_json(f"supervision/envelopes/{envelope}.json", {
            "schema": "tower/merge-envelope@1", "id": envelope,
            "status": "MERGED", "repository": ".", "base": "main",
            "implementation_head_sha": "0" * 40,
            "envelope_path": f"supervision/envelopes/{envelope}.json"})
        cp = self.cli("post-merge", "--envelope", envelope)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        data = json.loads(cp.stdout)
        self.assertEqual(data["position"]["index"], 2)
        self.assertEqual(data["position"]["total"], 6)

    def test_legacy_campaign_keeps_checkback_output(self) -> None:
        self.write_record(CURRENT, "delivered")
        self.write_doc(CAMPAIGN, campaign_text(roadmap=None, current=None))
        cp = self.cli("checkback", "--task", CURRENT,
                      "--reviewer", "independent-reviewer", "--verdict", "PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertNotIn("position", json.loads(cp.stdout))
        review = (self.tower / "tasks" / CURRENT / "REVIEW.md").read_text(
            encoding="utf-8")
        self.assertNotIn("## Position", review)

    def test_no_campaign_keeps_checkback_output(self) -> None:
        self.write_record(CURRENT, "delivered")
        (self.tower / CAMPAIGN).unlink()
        cp = self.cli("checkback", "--task", CURRENT,
                      "--reviewer", "independent-reviewer", "--verdict", "PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertNotIn("position", json.loads(cp.stdout))


class StatusSnapshotCase(PositionTowerCase):
    """status-snapshot writes the position line; no roadmap writes ``-``."""

    def snapshot(self) -> subprocess.CompletedProcess:
        return self.cli("status-snapshot", "--task", CURRENT,
                        "--event", "dispatched", "--at", "2026-10-29T10:00:00",
                        "--note", "position map")

    def test_snapshot_has_position_line(self) -> None:
        cp = self.snapshot()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        text = (self.tower / "status/2026-10-29.md").read_text(encoding="utf-8")
        self.assertIn("- position: 2/6", text)
        self.assertIn("- note: position map", text)
        self.assertEqual(self.cli("status-index").returncode, 0)
        index = json.loads((self.tower / "status/index.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(index["schema"], "tower/status-index@1")

    def test_snapshot_placeholder_without_roadmap(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(roadmap=None, current=None))
        self.assertEqual(self.snapshot().returncode, 0)
        text = (self.tower / "status/2026-10-29.md").read_text(encoding="utf-8")
        self.assertIn("- position: -", text)

    def test_snapshot_does_not_touch_the_control_plane(self) -> None:
        before = self.hashes()
        self.assertEqual(self.snapshot().returncode, 0)
        after = self.hashes()
        changed = {path for path in set(before) | set(after)
                   if before.get(path) != after.get(path)}
        self.assertEqual(changed, {"status/2026-10-29.md"})


class BriefCase(PositionTowerCase):
    """brief takes its progress from the roadmap, falling back to task_forces."""

    def test_brief_progress_uses_the_roadmap(self) -> None:
        cp = self.cli("brief")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("2/6 closed", cp.stdout)
        self.assertNotIn("2/3 closed", cp.stdout)

    def test_brief_falls_back_to_task_forces(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(roadmap=None, current=None))
        cp = self.cli("brief")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("2/3 closed", cp.stdout)


class PositionUnitCase(unittest.TestCase):
    """The pure status mapping, exercised without a tower."""

    def test_position_status_maps_every_record_shape(self) -> None:
        self.assertEqual(towerctl.position_status(None, CURRENT, CURRENT),
                         "active")
        self.assertEqual(towerctl.position_status(None, "PILOT-048", CURRENT),
                         "planned")
        self.assertEqual(towerctl.position_status(
            {"status": "closed"}, "PILOT-045", CURRENT), "done")
        self.assertEqual(towerctl.position_status(
            {"status": "rework", "review": {"verdict": "FAIL"}},
            CURRENT, CURRENT), "blocked")
        self.assertEqual(towerctl.position_status(
            {"status": "delivered"}, CURRENT, CURRENT), "active")
        self.assertEqual(towerctl.position_status(
            {"status": "ready"}, CURRENT, CURRENT), "planned")


if __name__ == "__main__":
    unittest.main()
