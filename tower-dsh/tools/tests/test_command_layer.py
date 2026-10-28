"""Tests for the PILOT-045 command layer: ``campaign-check`` and ``brief``.

Every case builds its own throw-away tower root under the runner's ``TMP``
sandbox and drives the real CLI through ``subprocess``, so exit codes and
stdout are asserted exactly as a caller observes them::

    python -B tools/run_tests.py

The YAML-subset cases call the parser directly; the rest go through
``towerctl campaign-check`` / ``towerctl brief`` so the wiring is covered too.
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

TASK = "PILOT-045"
OTHER = "PILOT-046"
STRATEGY_REL = "command/STRATEGY.md"
CAMPAIGN_REL = "command/campaigns/C-2026-Q4-01.md"
HEADERS = ("## 战略一句话", "## 当前战役", "## 在飞（WIP）",
           "## 阻塞 / 返工", "## 下一步 3 件", "## 待决", "## 架构约束")


def day(offset: int) -> str:
    """An ISO date ``offset`` days from today, for review_by fixtures."""
    return (date.today() + timedelta(days=offset)).isoformat()


def strategy_text(review_by: str | None = None, extra_goals: str = "") -> str:
    """A strategy document that exercises every supported YAML shape."""
    return (
        "---\n"
        "# 测试用战略：覆盖标量 / 标量列表 / 映射列表 / 引号 / 整行注释\n"
        "schema: tower/strategy@1\n"
        "id: S-2026-Q4\n"
        "horizon: 2026-Q4\n"
        "owner: mac\n"
        "status: active\n"
        f"review_by: {review_by or day(60)}\n"
        'title: "测试战略：命令层"\n'
        "goals:\n"
        "  - id: G1\n"
        '    text: "可信交付：记录层缺口关闭"\n'
        '    metric: "0 个未关闭缺口；drift=0"\n'
        "  - id: G2\n"
        "    text: 全局指挥\n"
        '    metric: "campaign-check exit 0"\n'
        f"{extra_goals}"
        "non_goals:\n"
        "  - 多写者并行\n"
        '  - "生产接入"\n'
        "bets:\n"
        "  - 先把控制面做可信\n"
        "---\n"
        "# 战略正文\n"
    )


def campaign_text(task_forces: tuple[str, ...] = (TASK,), goal: str = "G2",
                  review_by: str | None = None, budget: str = "2 张卡 / 2 周",
                  campaign_id: str = "C-2026-Q4-01", status: str = "active",
                  wip_limit: int = 1) -> str:
    """A campaign document pointing at ``strategy_text`` goals."""
    forces = "".join(f"  - {task}\n" for task in task_forces)
    return (
        "---\n"
        "schema: tower/campaign@1\n"
        f"id: {campaign_id}\n"
        f"goal: {goal}\n"
        f"status: {status}\n"
        "owner: mac\n"
        'objective: "命令层 v1 落地"\n'
        "key_results:\n"
        '  - "campaign-check exit 0"\n'
        '  - "brief ≤60 行"\n'
        "task_forces:\n"
        f"{forces}"
        'sequence: "045 → 046；不并行"\n'
        "stop_conditions:\n"
        '  - "drift != 0 立即停"\n'
        '  - "连续 2 卡 FAIL 复盘"\n'
        f'budget: "{budget}"\n'
        f"wip_limit: {wip_limit}\n"
        f"review_by: {review_by or day(14)}\n"
        "---\n"
        "# 战役正文\n"
    )


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class CommandLayerCase(unittest.TestCase):
    """A minimal tower root: strategy, one campaign, board, state, one record."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-command-", ignore_cleanup_errors=True)
        self.tower = Path(self._tmp.name) / "tower"
        self.write_doc(STRATEGY_REL, strategy_text())
        self.write_doc(CAMPAIGN_REL, campaign_text())
        self.write_board()
        write_json(self.tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "owner": {"name": "mac"},
            "next_action": "跑 045", "blockers": []})
        self.write_record(TASK, "dispatched")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_doc(self, relpath: str, text: str) -> Path:
        path = self.tower / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_record(self, task_id: str, status: str,
                     verdict: str | None = None) -> None:
        write_json(self.tower / "tasks" / task_id / "record.json", {
            "schema": "tower/task@1", "id": task_id, "title": "夹具卡",
            "status": status, "next": "等待处理",
            "review": {"verdict": verdict} if verdict else None})

    def write_board(self, *task_ids: str) -> None:
        write_json(self.tower / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{"id": task_id, "status": "closed"} for task_id in task_ids]})

    def check(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "campaign-check", *args)

    def payload(self, *args: str) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.check(*args)
        return cp, json.loads(cp.stdout) if cp.stdout.strip() else {}

    def codes(self, payload: dict, key: str = "errors") -> list[str]:
        return [finding["code"] for finding in payload.get(key) or []]

    def snapshot(self) -> dict[str, str]:
        return {path.relative_to(self.tower).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.tower.rglob("*")) if path.is_file()}


class CampaignCheckCase(CommandLayerCase):
    """E1–E6, W1/W2 and the --strict upgrade."""

    def test_valid_fixture_is_green(self) -> None:
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(data["strategy"], "S-2026-Q4")
        self.assertEqual(data["goals"], ["G1", "G2"])
        self.assertEqual(data["campaigns"], 1)
        self.assertEqual(data["wip"], {"in_flight": 1, "limit": 1,
                                       "campaigns": {"C-2026-Q4-01": 1}})
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["warnings"], [])

    def test_e1_missing_strategy(self) -> None:
        (self.tower / STRATEGY_REL).unlink()
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E1"])
        self.assertIn("missing", data["errors"][0]["detail"])

    def test_e1_malformed_front_matter_is_clean_exit_two(self) -> None:
        self.write_doc(STRATEGY_REL, "---\nid: S\ngoals: [G1]\n---\n")
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E1"])
        self.assertIn("unsupported scalar", data["errors"][0]["detail"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)

    def test_e1_campaign_front_matter_error(self) -> None:
        self.write_doc(CAMPAIGN_REL, "---\nid: C\ngoals:\n  - id: G1\n      text: 深\n---\n")
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E1"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)

    def test_e2_goal_not_in_strategy(self) -> None:
        self.write_doc(CAMPAIGN_REL, campaign_text(goal="G9"))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E2"])
        self.assertIn("G9", data["errors"][0]["detail"])

    def test_e3_active_campaign_past_review_by(self) -> None:
        self.write_doc(CAMPAIGN_REL, campaign_text(review_by=day(-1)))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E3"])

    def test_e3_strategy_past_review_by(self) -> None:
        self.write_doc(STRATEGY_REL, strategy_text(review_by=day(-2)))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E3"])
        self.assertEqual(data["errors"][0]["target"], "command/STRATEGY.md")

    def test_e4_wip_over_limit(self) -> None:
        self.write_record(OTHER, "delivered")
        self.write_doc(CAMPAIGN_REL, campaign_text(task_forces=(TASK, OTHER)))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E4"])
        self.assertEqual(data["wip"]["in_flight"], 2)

    def test_e5_unknown_task_force(self) -> None:
        self.write_doc(CAMPAIGN_REL, campaign_text(task_forces=(TASK, "PILOT-999")))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E5"])
        self.assertIn("PILOT-999", data["errors"][0]["detail"])

    def test_e5_pilot_spec_counts_as_existing(self) -> None:
        spec = self.tower / "pilot" / "PILOT-047.spec.json"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("{}\n", encoding="utf-8")
        self.write_doc(CAMPAIGN_REL, campaign_text(task_forces=(TASK, "PILOT-047")))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(data["errors"], [])

    def test_e6_duplicate_goal_id(self) -> None:
        self.write_doc(STRATEGY_REL, strategy_text(extra_goals="  - id: G1\n    text: 重复\n"))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E6"])
        self.assertIn("G1", data["errors"][0]["detail"])

    def test_e6_duplicate_campaign_id(self) -> None:
        self.write_doc("command/campaigns/C-2026-Q4-02.md", campaign_text())
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["E6"])
        self.assertIn("C-2026-Q4-01", data["errors"][0]["detail"])

    def test_w1_board_card_not_referenced(self) -> None:
        self.write_board("PILOT-001", "PILOT-002")
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data, "warnings"), ["W1", "W1"])
        self.assertEqual(data["errors"], [])

    def test_w1_upgrades_to_error_under_strict(self) -> None:
        self.write_board("PILOT-001")
        cp, data = self.payload("--strict")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data), ["W1"])
        self.assertEqual(data["warnings"], [])
        self.assertFalse(data["ok"])

    def test_w2_review_by_within_a_week(self) -> None:
        self.write_doc(CAMPAIGN_REL, campaign_text(review_by=day(3)))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(data, "warnings"), ["W2"])
        self.assertEqual(self.payload("--strict")[0].returncode, 2)

    def test_w2_task_forces_over_budget(self) -> None:
        self.write_doc(CAMPAIGN_REL, campaign_text(budget="0 张卡 / 1 周"))
        cp, data = self.payload()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("budget", data["warnings"][0]["detail"])


class BriefCase(CommandLayerCase):
    """The one-page brief: seven sections, line cap, and read-only behaviour."""

    def brief(self) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "brief")

    def test_brief_has_seven_sections_and_fits_sixty_lines(self) -> None:
        self.write_record(OTHER, "reviewed")
        cp = self.brief()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        lines = cp.stdout.splitlines()
        self.assertLessEqual(len(lines), 60)
        self.assertTrue(lines[0].startswith("# BRIEF — "))
        self.assertEqual([line for line in lines if line.startswith("## ")], list(HEADERS))
        self.assertIn("0/1 closed", cp.stdout)
        self.assertTrue(any(line.startswith(f"- {TASK}") for line in lines))
        self.assertTrue(any(line.startswith(f"- {OTHER}") for line in lines))

    def test_brief_lists_rework_and_blockers(self) -> None:
        self.write_record(OTHER, "rework", verdict="FAIL")
        cp = self.brief()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        blocked = cp.stdout.split("## 阻塞 / 返工")[1].split("## ")[0]
        self.assertIn(OTHER, blocked)

    def test_brief_caps_lists_but_keeps_all_sections(self) -> None:
        for index in range(10):
            self.write_record(f"PILOT-1{index:02d}", "dispatched")
        cp = self.brief()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        lines = cp.stdout.splitlines()
        self.assertLessEqual(len(lines), 60)
        self.assertEqual([line for line in lines if line.startswith("## ")], list(HEADERS))
        self.assertTrue(any("另有" in line for line in lines))

    def test_brief_and_campaign_check_write_nothing(self) -> None:
        before = self.snapshot()
        self.assertEqual(self.brief().returncode, 0)
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_brief_survives_missing_command_docs(self) -> None:
        (self.tower / STRATEGY_REL).unlink()
        (self.tower / CAMPAIGN_REL).unlink()
        cp = self.brief()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        lines = cp.stdout.splitlines()
        self.assertLessEqual(len(lines), 60)
        self.assertEqual([line for line in lines if line.startswith("## ")], list(HEADERS))


class YamlSubsetCase(unittest.TestCase):
    """The zero-dependency front-matter parser, exercised directly."""

    def parse(self, body: str) -> dict:
        return towerctl.parse_command_front_matter(body.splitlines())

    def test_scalars_lists_and_mapping_items(self) -> None:
        data = self.parse(
            "# 整行注释\n"
            'title: "含：冒号与中文"\n'
            "count: 3\n"
            "names:\n"
            "  - alpha\n"
            '  - "beta"\n'
            "goals:\n"
            "  - id: G1\n"
            '    text: "可信：交付"\n'
            "    metric: x=1\n")
        self.assertEqual(data["title"], "含：冒号与中文")
        self.assertEqual(data["count"], "3")
        self.assertEqual(data["names"], ["alpha", "beta"])
        self.assertEqual(data["goals"],
                         [{"id": "G1", "text": "可信：交付", "metric": "x=1"}])

    def test_front_matter_block_stops_at_the_fence(self) -> None:
        self.assertEqual(towerctl.front_matter_block("---\nid: S\n---\n# body\n"),
                         ["id: S"])

    def test_unsupported_structures_raise(self) -> None:
        for body in ("goals:\n  nested: x\n", "goals: [G1]\n", "just text\n",
                     "goals:\n  - id: G1\n      text: 深\n",
                     'title: "转义 \\" 引号"\n',
                     "items:\n  - plain\n  - id: G1\n"):
            with self.subTest(body=body):
                with self.assertRaises(towerctl.CommandDocError):
                    self.parse(body)

    def test_missing_or_unterminated_fence_raises(self) -> None:
        for body in ("id: S\n---\n", "---\nid: S\n"):
            with self.subTest(body=body):
                with self.assertRaises(towerctl.CommandDocError):
                    towerctl.front_matter_block(body)


if __name__ == "__main__":
    unittest.main()
