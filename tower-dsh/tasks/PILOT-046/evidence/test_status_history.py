"""Tests for PILOT-046: append-only status history and the R2-R5/W3 hardening.

Every case builds its own throw-away tower under the runner's ``TMP`` sandbox
and drives the real CLI through ``subprocess``, so exit codes and bytes are
asserted exactly as a caller observes them::

    python -B tools/run_tests.py

The status commands must write only ``status/``; the control-plane hash case
pins that.  The hardening cases (E7/R3/R4/R5/W3) go through
``towerctl campaign-check`` so the wiring is covered too.
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

CARD = "PILOT-046"
CLOSED = "PILOT-045"
STRATEGY = "command/STRATEGY.md"
CAMPAIGN = "command/campaigns/C-2026-Q4-01.md"
DAY = "2026-10-28"
WEEK = "2026-W44"


def day(offset: int) -> str:
    """An ISO date ``offset`` days from today, for relative fixtures."""
    return (date.today() + timedelta(days=offset)).isoformat()


def strategy_text() -> str:
    """A minimal valid strategy document."""
    return ("---\n"
            "schema: tower/strategy@1\n"
            "id: S-2026-Q4\n"
            "horizon: 2026-Q4\n"
            "owner: mac\n"
            "status: active\n"
            f"review_by: {day(30)}\n"
            "goals:\n"
            "  - id: G1\n"
            "    text: 可信交付\n"
            "non_goals:\n"
            "  - 多写者并行\n"
            "---\n"
            "# 战略正文\n")


def campaign_text(task_forces: tuple[str, ...] = (CLOSED,), goal: str = "G1",
                  budget: str = "2 张卡 / 2 周", wip_limit: int = 1,
                  forces_block: str | None = None,
                  started: str | None = None) -> str:
    """A minimal campaign document; ``forces_block`` replaces ``task_forces``."""
    block = forces_block if forces_block is not None else (
        "task_forces:\n" + "".join(f"  - {task}\n" for task in task_forces))
    started_line = f"started: {started}\n" if started else ""
    return ("---\n"
            "schema: tower/campaign@1\n"
            "id: C-2026-Q4-01\n"
            f"goal: {goal}\n"
            "status: active\n"
            "owner: mac\n"
            'objective: "状态历史"\n'
            f"{block}"
            f"{started_line}"
            'sequence: "046"\n'
            f'budget: "{budget}"\n'
            f"wip_limit: {wip_limit}\n"
            f"review_by: {day(30)}\n"
            "---\n"
            "# 战役正文\n")


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plane_hashes(root: Path) -> dict[str, str]:
    """Content hashes of the control-plane trees these commands must not write."""
    return {path.relative_to(root).as_posix(): sha(path)
            for name in ("primary", "supervision", "ledger", "tasks")
            for path in sorted((root / name).rglob("*")) if path.is_file()}


class StatusTowerCase(unittest.TestCase):
    """A throw-away tower: strategy, campaign, board, records."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-status-", ignore_cleanup_errors=True)
        self.tower = Path(self._tmp.name) / "tower"
        self.write_doc(STRATEGY, strategy_text())
        self.write_doc(CAMPAIGN, campaign_text())
        self.write_json("primary/TASK_BOARD.json", {
            "schema": "tower/task-board@1", "tasks": [{"id": CLOSED}]})
        self.write_json("primary/CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "owner": {"name": "mac"}})
        self.write_record(CLOSED, "closed", "PASS")
        self.write_record(CARD, "dispatched")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_doc(self, relpath: str, text: str) -> Path:
        path = self.tower / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relpath: str, data) -> Path:
        return self.write_doc(relpath, json.dumps(data, ensure_ascii=False, indent=2))

    def write_record(self, task_id: str, status: str,
                     verdict: str | None = None) -> None:
        self.write_json(f"tasks/{task_id}/record.json", {
            "schema": "tower/task@1", "id": task_id, "title": "夹具卡",
            "status": status, "next": "等待处理",
            "review": {"verdict": verdict} if verdict else None})

    def snapshot(self, event: str, at: str, note: str | None = None,
                 task: str = CARD, tests: int | None = None) -> subprocess.CompletedProcess:
        args = ["status-snapshot", "--task", task, "--event", event, "--at", at]
        if note is not None:
            args += ["--note", note]
        if tests is not None:
            args += ["--tests", str(tests)]
        return run_cli(self.tower, *args)

    def check(self, *args: str) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "campaign-check", *args)

    def payload(self, *args: str) -> dict:
        cp = self.check(*args)
        return json.loads(cp.stdout) if cp.stdout.strip() else {}

    def codes(self, payload: dict, key: str = "errors") -> list[str]:
        return [finding["code"] for finding in payload.get(key) or []]

    def status_text(self, name: str = "2026-10-28.md") -> str:
        return (self.tower / "status" / name).read_text(encoding="utf-8")

    def headings(self, text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("## ")]


class SnapshotCase(StatusTowerCase):
    """status-snapshot: append-only, same-day twice, frozen time."""

    def test_same_day_twice_appends_two_entries(self) -> None:
        self.assertEqual(self.snapshot("dispatched", "2026-10-28T10:00:00",
                                       "first").returncode, 0)
        self.assertEqual(self.snapshot("note", "2026-10-28T11:30:00",
                                       "second").returncode, 0)
        text = self.status_text()
        self.assertTrue(text.startswith("# STATUS — 2026-10-28\n"))
        self.assertEqual(text.count("# STATUS"), 1)
        self.assertEqual(self.headings(text),
                         ["## 10:00 · PILOT-046 · dispatched",
                          "## 11:30 · PILOT-046 · note"])
        self.assertIn("- note: first", text)
        self.assertIn("- note: second", text)

    def test_snapshot_records_campaign_wip_blocked_and_tests(self) -> None:
        self.write_record("PILOT-047", "rework", "FAIL")
        self.snapshot("dispatched", "2026-10-28T10:00:00", tests=470)
        text = self.status_text()
        self.assertIn("- campaign: C-2026-Q4-01 (1/1)", text)
        self.assertIn("- wip: 1/1", text)
        self.assertIn("- blocked: 1", text)
        self.assertIn("- tests: 470", text)

    def test_at_freezes_the_whole_date(self) -> None:
        self.snapshot("dispatched", "2026-10-27T09:05:00")
        self.assertTrue((self.tower / "status/2026-10-27.md").is_file())
        self.assertFalse((self.tower / "status/2026-10-28.md").exists())
        text = self.status_text("2026-10-27.md")
        self.assertIn("# STATUS — 2026-10-27", text)
        self.assertIn("## 09:05 · PILOT-046 · dispatched", text)


class IndexCase(StatusTowerCase):
    """status-index: entries, hash, key order, recomputability."""

    def test_index_counts_entries_and_matches_file_hash(self) -> None:
        self.snapshot("dispatched", "2026-10-28T10:00:00")
        self.snapshot("note", "2026-10-28T11:30:00", "second")
        self.assertEqual(run_cli(self.tower, "status-index").returncode, 0)
        data = json.loads((self.tower / "status/index.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "tower/status-index@1")
        self.assertEqual(len(data["days"]), 1)
        entry = data["days"][0]
        self.assertEqual(entry["date"], DAY)
        self.assertEqual(entry["file"], "status/2026-10-28.md")
        self.assertEqual(entry["entries"], 2)
        day_file = self.tower / "status/2026-10-28.md"
        self.assertEqual(entry["sha256"], sha(day_file))
        self.assertEqual(data["cards"], {
            CARD: {"last_event": "note", "last_date": DAY}})
        self.assertEqual(data["campaigns"], {
            "C-2026-Q4-01": {"progress": "1/1"}})

    def test_index_is_byte_stable_and_recomputable(self) -> None:
        self.snapshot("dispatched", "2026-10-28T10:00:00")
        index = self.tower / "status/index.json"
        run_cli(self.tower, "status-index")
        first = index.read_bytes()
        run_cli(self.tower, "status-index")
        self.assertEqual(index.read_bytes(), first)
        index.unlink()
        run_cli(self.tower, "status-index")
        self.assertEqual(index.read_bytes(), first)

    def test_index_ignores_weekly_archive_and_readme(self) -> None:
        self.snapshot("dispatched", "2026-10-28T10:00:00")
        self.write_doc("status/README.md", "# STATUS\n")
        self.write_doc("status/weekly/2026-W44.md", "# WEEKLY\n")
        self.write_doc("status/archive/2026-Q4.md", "# ARCHIVE\n")
        run_cli(self.tower, "status-index")
        data = json.loads((self.tower / "status/index.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual([entry["file"] for entry in data["days"]],
                         ["status/2026-10-28.md"])


class RollupCase(StatusTowerCase):
    """status-rollup: one week, byte-stable, writes only weekly/."""

    def test_rollup_summarises_the_week_and_is_byte_stable(self) -> None:
        self.write_record("PILOT-047", "rework", "FAIL")
        self.snapshot("closed", "2026-10-26T09:00:00", task=CLOSED)
        self.snapshot("note", "2026-10-28T11:00:00")
        self.assertEqual(run_cli(self.tower, "status-rollup",
                                 "--week", WEEK).returncode, 0)
        target = self.tower / "status/weekly" / f"{WEEK}.md"
        first = target.read_bytes()
        run_cli(self.tower, "status-rollup", "--week", WEEK)
        self.assertEqual(target.read_bytes(), first)
        text = first.decode("utf-8")
        self.assertIn("- 事件数：2", text)
        self.assertIn("- closed 卡：PILOT-045", text)
        self.assertIn("- blocked 计数：1", text)
        self.assertIn("- wip 变化：1/1", text)
        self.assertIn("C-2026-Q4-01 1/1", text)
        self.assertIn("## 事件", text)

    def test_rollup_writes_nothing_but_weekly(self) -> None:
        self.snapshot("dispatched", "2026-10-28T10:00:00")
        before = {path.relative_to(self.tower).as_posix(): sha(path)
                  for path in sorted((self.tower / "status").rglob("*"))
                  if path.is_file() and "weekly" not in path.parts}
        run_cli(self.tower, "status-rollup", "--week", WEEK)
        after = {path.relative_to(self.tower).as_posix(): sha(path)
                 for path in sorted((self.tower / "status").rglob("*"))
                 if path.is_file() and "weekly" not in path.parts}
        self.assertEqual(before, after)


class ArchiveCase(StatusTowerCase):
    """status-archive: keeps originals, byte-stable, one line per day."""

    def test_archive_keeps_originals_and_is_byte_stable(self) -> None:
        self.snapshot("dispatched", "2026-10-27T10:00:00")
        self.snapshot("note", "2026-10-28T10:00:00")
        cp = run_cli(self.tower, "status-archive", "--before", "2026-10-28")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        archive = self.tower / "status/archive/2026-Q4.md"
        text = archive.read_text(encoding="utf-8")
        self.assertIn("2026-10-27", text)
        self.assertNotIn("2026-10-28", text)
        self.assertTrue((self.tower / "status/2026-10-27.md").is_file())
        self.assertTrue((self.tower / "status/2026-10-28.md").is_file())
        first = archive.read_bytes()
        run_cli(self.tower, "status-archive", "--before", "2026-10-28")
        self.assertEqual(archive.read_bytes(), first)


class StatusIsolationCase(StatusTowerCase):
    """Every status command must leave the control plane byte-identical."""

    def test_status_commands_leave_control_plane_untouched(self) -> None:
        self.snapshot("dispatched", "2026-10-27T10:00:00")
        before = plane_hashes(self.tower)
        self.snapshot("note", "2026-10-28T10:00:00")
        run_cli(self.tower, "status-index")
        run_cli(self.tower, "status-rollup", "--week", WEEK)
        run_cli(self.tower, "status-archive", "--before", "2026-10-29")
        self.assertEqual(plane_hashes(self.tower), before)


class BoardShapeCase(StatusTowerCase):
    """E7: a malformed board exits 2 cleanly instead of raising."""

    def test_board_array_is_clean_exit_two(self) -> None:
        self.write_json("primary/TASK_BOARD.json", [])
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(json.loads(cp.stdout)), ["E7"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)

    def test_board_non_object_task_element_is_clean_exit_two(self) -> None:
        self.write_json("primary/TASK_BOARD.json", {
            "schema": "tower/task-board@1", "tasks": ["PILOT-001"]})
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(json.loads(cp.stdout)), ["E7"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)


class R3EmptyTaskForcesCase(StatusTowerCase):
    """R3: an empty ``task_forces`` is 0/0 and never an E5."""

    def test_empty_list_and_empty_key_are_zero_of_zero(self) -> None:
        for block in ("task_forces: []\n", "task_forces:\n"):
            with self.subTest(block=block):
                self.write_doc(CAMPAIGN, campaign_text(forces_block=block))
                data = self.payload()
                self.assertEqual(data["errors"], [])
                brief = run_cli(self.tower, "brief")
                self.assertEqual(brief.returncode, 0, msg=brief.stdout + brief.stderr)
                self.assertIn("0/0 closed", brief.stdout)


class R4QuotedScalarCase(StatusTowerCase):
    """R4: single-quoted scalars, ``''`` escapes, clean rejection."""

    def test_single_quotes_parse_and_campaign_goal_is_linked(self) -> None:
        parsed = towerctl.parse_command_front_matter(
            ["title: 'it''s fine'", "goal: 'G1'"])
        self.assertEqual(parsed, {"title": "it's fine", "goal": "G1"})
        self.write_doc(CAMPAIGN, campaign_text(goal="'G1'"))
        cp = self.check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["errors"], [])

    def test_unsupported_structure_still_exits_two_cleanly(self) -> None:
        self.write_doc(STRATEGY,
                       "---\nschema: tower/strategy@1\nid: S\ngoals: [G1]\n---\n")
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.codes(json.loads(cp.stdout)), ["E1"])
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)


class R5BudgetCase(StatusTowerCase):
    """R5: card units in both languages, week windows via ``started``."""

    def test_card_budget_units_are_parsed(self) -> None:
        for task_id in ("PILOT-101", "PILOT-102", "PILOT-103"):
            self.write_record(task_id, "closed", "PASS")
        forces = (CLOSED, "PILOT-101", "PILOT-102", "PILOT-103")
        for budget in ("2 cards", "2 card", "2 张卡"):
            with self.subTest(budget=budget):
                self.write_doc(CAMPAIGN, campaign_text(
                    task_forces=forces, budget=budget, wip_limit=5))
                data = self.payload()
                self.assertEqual(data["errors"], [])
                details = [item["detail"] for item in data["warnings"]
                           if item["code"] == "W2"]
                self.assertTrue(any("budget of 2 cards" in item
                                    for item in details), msg=details)

    def test_started_plus_week_window_is_w2(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(
            started=day(-30), budget="2 cards / 2 weeks"))
        data = self.payload()
        self.assertEqual(data["errors"], [])
        details = [item["detail"] for item in data["warnings"]
                   if item["code"] == "W2"]
        self.assertTrue(any("budget window" in item for item in details),
                        msg=details)
        self.assertEqual(self.check("--strict").returncode, 2)

    def test_unparseable_budget_is_not_a_false_positive(self) -> None:
        for budget, started in (("2 cards", None), ("tbd", day(-30))):
            with self.subTest(budget=budget, started=started):
                self.write_doc(CAMPAIGN, campaign_text(
                    budget=budget, started=started))
                self.assertEqual(self.payload()["warnings"], [])


class W3SpecOnlyCase(StatusTowerCase):
    """W3: spec-only references warn; missing cards stay E5."""

    def test_spec_only_is_warning_and_strict_upgrades(self) -> None:
        self.write_doc("pilot/PILOT-047.spec.json", "{}\n")
        self.write_doc(CAMPAIGN, campaign_text(task_forces=(CLOSED, "PILOT-047")))
        data = self.payload()
        self.assertEqual(data["errors"], [])
        self.assertEqual(self.codes(data, "warnings"), ["W3"])
        strict = self.check("--strict")
        self.assertEqual(strict.returncode, 2)
        self.assertEqual(self.codes(json.loads(strict.stdout)), ["W3"])

    def test_missing_card_is_still_e5(self) -> None:
        self.write_doc(CAMPAIGN, campaign_text(task_forces=(CLOSED, "PILOT-999")))
        data = self.payload()
        self.assertEqual(self.codes(data), ["E5"])
        self.assertEqual(data["warnings"], [])


if __name__ == "__main__":
    unittest.main()
