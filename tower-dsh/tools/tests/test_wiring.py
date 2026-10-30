"""PILOT-050 wiring tests: dispatch campaign, W1/W2, post-merge gates, CI.

Every test builds an isolated tower root, drives the real CLI through
``subprocess`` (so exit codes are observed exactly), and keeps the fixture
self-contained: no network, no dependencies, no writes outside ``tempfile``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
REPO_ROOT = TOOLS_DIR.parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tower-gate.yml"
TASK_ID = "TEST-WIRE-001"
ENVELOPE_ID = "ENV-TEST-WIRE-001"
FIXED_TIME = "2026-10-30T00:00:00+08:00"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def codes(payload: dict, code: str) -> list[dict]:
    return [item for item in payload["warnings"] if item["code"] == code]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WiringCase(unittest.TestCase):
    """One temporary tower root plus the command-document fixture writers."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-wiring-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger",
                          f"tasks/{TASK_ID}", f"pilot/worktrees/{TASK_ID}"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.write_board([])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_board(self, ids) -> None:
        write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{"id": task_id, "status": "closed"} for task_id in ids],
        })

    def write_strategy(self) -> None:
        text = "\n".join([
            "---", "schema: tower/strategy@1", "id: S-WIRE", 'title: "wiring"',
            "goals:", "  - id: G2", '    text: "wire the command layer"',
            "review_by: 2026-12-31", "non_goals: []", "---", "", "# S-WIRE", "",
        ])
        path = self.root / "command" / "STRATEGY.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_campaign(self, campaign_id: str = "C-WIRE", *, status: str = "active",
                       roadmap=None, forces=(), legacy=None,
                       budget: str = "9 张卡 / 8 周") -> None:
        lines = [
            "---", "schema: tower/campaign@1", f"id: {campaign_id}",
            "goal: G2", f"status: {status}", "owner: mac",
            'objective: "wiring fixture"', f'budget: "{budget}"',
            "wip_limit: 9", "review_by: 2026-12-31",
        ]
        for key, values in (("roadmap", roadmap), ("task_forces", forces),
                            ("legacy_cards", legacy)):
            if values is None:
                continue
            lines.append(f"{key}:")
            lines += [f"  - {value}" for value in values]
        lines.append("---")
        path = self.root / "command" / "campaigns" / f"{campaign_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_card(self, task_id: str, status: str, *,
                   dispatch: dict | None = None) -> dict:
        record = {
            "schema": "tower/task@1", "id": task_id, "title": task_id,
            "status": status, "executor": None, "dispatch": dispatch,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
        }
        write_json(self.root / "tasks" / task_id / "record.json", record)
        return record

    def report(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = run_cli(self.root, "campaign-check")
        return cp, json.loads(cp.stdout)


class DispatchCampaignCase(WiringCase):
    """dispatch --campaign: four campaign-count paths, zero writes on refusal."""

    def setUp(self) -> None:
        super().setUp()
        spec = self.root / "specs" / "task.spec.json"
        write_json(spec, {
            "schema": "tower/spec@1", "id": TASK_ID, "title": "wiring",
            "authority": "workspace_write", "scope": ["wiring"],
            "worktree": f"pilot/worktrees/{TASK_ID}", "allowed_paths": [],
            "forbidden": [], "acceptance": [],
        })
        self.write_card(TASK_ID, "ready")
        record = read_json(self.root / "tasks" / TASK_ID / "record.json")
        record.update({
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "spec_path": "specs/task.spec.json",
            "spec_sha256": sha256_file(spec), "spec_gate": "PASS",
        })
        write_json(self.root / "tasks" / TASK_ID / "record.json", record)
        (self.root / "tasks" / TASK_ID / "TASK.md").write_text(
            f"# {TASK_ID}\n", encoding="utf-8")
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")

    def dispatch(self, *extra: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, "dispatch", "--task", TASK_ID,
                       "--executor", "exec-a", *extra)

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def ledger_text(self) -> str:
        return (self.root / "ledger" / "primary.jsonl").read_text(encoding="utf-8")

    def test_legacy_tower_with_no_campaign_keeps_old_behaviour(self) -> None:
        cp = self.dispatch()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        dispatch = self.load_record()["dispatch"]
        self.assertNotIn("campaign", dispatch)
        self.assertEqual(self.load_record()["status"], "dispatched")

    def test_single_active_campaign_requires_the_flag_and_writes_nothing(self) -> None:
        self.write_campaign(roadmap=[TASK_ID], forces=[TASK_ID])
        cp = self.dispatch()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("--campaign", cp.stdout)
        self.assertEqual(self.load_record()["status"], "ready")
        self.assertIsNone(self.load_record()["dispatch"])
        self.assertEqual(self.ledger_text(), "")

    def test_unknown_or_out_of_roadmap_campaign_is_rejected(self) -> None:
        self.write_campaign(roadmap=["OTHER-CARD"], forces=[TASK_ID])
        unknown = self.dispatch("--campaign", "C-NOPE")
        self.assertEqual(unknown.returncode, 2, msg=unknown.stdout + unknown.stderr)
        self.assertIn("unknown campaign", unknown.stdout)
        outside = self.dispatch("--campaign", "C-WIRE")
        self.assertEqual(outside.returncode, 2, msg=outside.stdout + outside.stderr)
        self.assertIn("roadmap", outside.stdout)
        self.assertEqual(self.load_record()["status"], "ready")
        self.assertEqual(self.ledger_text(), "")

    def test_valid_campaign_is_recorded_in_record_and_ledger(self) -> None:
        self.write_campaign(roadmap=[TASK_ID], forces=[TASK_ID])
        cp = self.dispatch("--campaign", "C-WIRE")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.load_record()["dispatch"]["campaign"], "C-WIRE")
        event = json.loads(self.ledger_text().splitlines()[-1])
        self.assertEqual(event["type"], "DISPATCH")
        self.assertEqual(event["payload"]["campaign"], "C-WIRE")
        self.assertEqual(self.load_record()["dispatch"]["kind"], "subagent")

    def test_more_than_one_active_campaign_is_ambiguous(self) -> None:
        self.write_campaign("C-A", roadmap=[TASK_ID])
        self.write_campaign("C-B", roadmap=[TASK_ID])
        cp = self.dispatch("--campaign", "C-A")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("ambiguous", cp.stdout)
        self.assertEqual(self.load_record()["status"], "ready")
        self.assertEqual(self.ledger_text(), "")

    def test_legacy_tower_still_validates_a_given_campaign(self) -> None:
        self.write_campaign(roadmap=[TASK_ID], status="paused")
        cp = self.dispatch("--campaign", "C-WIRE")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("not active", cp.stdout)
        self.assertEqual(self.load_record()["status"], "ready")


class CampaignCoverageCase(WiringCase):
    """W1 (three coverage sources) and W2 (only open cards consume budget)."""

    def test_w1_is_silent_when_any_source_covers_the_card(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=("PILOT-001",), legacy=("PILOT-002",))
        self.write_card("PILOT-001", "closed")
        self.write_card("PILOT-002", "closed")
        self.write_card("PILOT-003", "closed",
                        dispatch={"executor": "e", "campaign": "C-WIRE"})
        self.write_board(["PILOT-001", "PILOT-002", "PILOT-003"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(codes(payload, "W1"), [])

    def test_w1_reports_a_card_no_source_covers(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=("PILOT-001",))
        self.write_card("PILOT-001", "closed")
        self.write_card("PILOT-002", "closed")
        self.write_board(["PILOT-001", "PILOT-002"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual([item["target"] for item in codes(payload, "W1")],
                         ["PILOT-002"])

    def test_w1_returns_when_legacy_cards_are_missing(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=("PILOT-001",))
        self.write_card("PILOT-001", "closed")
        self.write_card("PILOT-030", "closed")
        self.write_board(["PILOT-001", "PILOT-030"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("PILOT-030", [item["target"] for item in codes(payload, "W1")])

    def test_w1_ignores_a_dispatch_naming_an_unknown_campaign(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=())
        self.write_card("PILOT-004", "closed",
                        dispatch={"executor": "e", "campaign": "C-GONE"})
        self.write_board(["PILOT-004"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual([item["target"] for item in codes(payload, "W1")],
                         ["PILOT-004"])

    def test_w2_does_not_charge_closed_cards_to_the_budget(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=("PILOT-001", "PILOT-002", "PILOT-003"),
                            budget="2 张卡 / 8 周")
        self.write_card("PILOT-001", "closed")
        self.write_card("PILOT-002", "delivered")
        self.write_card("PILOT-003", "accepted")
        self.write_board(["PILOT-001", "PILOT-002", "PILOT-003"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(codes(payload, "W2"), [])

    def test_w2_warns_when_open_cards_exceed_the_budget(self) -> None:
        self.write_strategy()
        self.write_campaign(forces=("PILOT-001", "PILOT-002", "PILOT-003"),
                            budget="2 张卡 / 8 周")
        for task_id in ("PILOT-001", "PILOT-002", "PILOT-003"):
            self.write_card(task_id, "dispatched")
        self.write_board(["PILOT-001", "PILOT-002", "PILOT-003"])
        cp, payload = self.report()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(len(codes(payload, "W2")), 1)
        self.assertIn("open task_forces", codes(payload, "W2")[0]["detail"])


class PostMergeWiringCase(unittest.TestCase):
    """post-merge appends campaign-check / arch-check only for wired towers."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-wiring-pm-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.root = self.kit / "tower-dsh"
        for directory in ("supervision/envelopes", "supervision/reviews",
                          "tasks/PM-000", "ledger"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "supervision.jsonl").write_text("", encoding="utf-8")
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "TEST", "supervisor": {"id": "sup-t"},
        })
        self.init_repo()
        write_json(self.root / "supervision" / "envelopes" / f"{ENVELOPE_ID}.json", {
            "schema": "tower/merge-envelope@1", "envelope_id": ENVELOPE_ID,
            "task": "PM-000", "repository": "..", "branch": "feature/wire",
            "base": "main", "envelope_path": f"merge-envelopes/{ENVELOPE_ID}.json",
            "implementation_head_sha": self.implementation_head,
            "envelope_head_sha": self.merge_commit,
            "status": "MERGED", "tests_baseline": 1,
            "merge_commit": self.merge_commit,
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1",
            "entries": [{"envelope_id": ENVELOPE_ID, "task": "PM-000",
                         "branch": "feature/wire", "base": "main",
                         "status": "MERGED", "added_at": FIXED_TIME,
                         "merge_commit": self.merge_commit}],
            "updated_at": FIXED_TIME,
        })
        self.commit_all("supervision state")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(["git", "-C", str(self.kit), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              env=env)

    def commit_all(self, message: str) -> str:
        self.assertEqual(self.git("add", "-A").returncode, 0)
        cp = self.git("-c", "commit.gpgsign=false", "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def init_repo(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.git("init").returncode, 0)
        self.assertEqual(self.git("symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / "tests").mkdir()
        (self.kit / "tests" / "test_smoke.py").write_text(
            "import unittest\n\n\nclass Smoke(unittest.TestCase):\n"
            "    def test_smoke(self):\n        self.assertTrue(True)\n",
            encoding="utf-8")
        write_json(self.kit / "merge-envelopes" / f"{ENVELOPE_ID}.json",
                   {"schema": "tower/merge-envelope@1",
                    "envelope_id": ENVELOPE_ID, "task": "PM-000"})
        self.commit_all("base")
        self.assertEqual(self.git("checkout", "-b", "feature/wire").returncode, 0)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit_all("implementation")
        self.assertEqual(self.git("checkout", "main").returncode, 0)
        merge = self.git("-c", "commit.gpgsign=false", "merge", "--no-ff",
                         "-m", "merge: PM-000", "feature/wire")
        self.assertEqual(merge.returncode, 0, msg=merge.stdout + merge.stderr)
        self.merge_commit = self.git("rev-parse", "HEAD").stdout.strip()

    def run_post_merge(self, result: str = "PASS") -> subprocess.CompletedProcess:
        return run_cli(self.root, "post-merge", "--envelope", ENVELOPE_ID,
                       "--result", result)

    def envelope(self) -> dict:
        return read_json(self.root / "supervision" / "envelopes"
                         / f"{ENVELOPE_ID}.json")

    def test_wired_tower_appends_both_checks_and_campaign_failure_blocks(self) -> None:
        self.root.joinpath("command", "campaigns").mkdir(parents=True)
        (self.root / "command" / "campaigns" / "C-WIRE.md").write_text(
            "---\nschema: tower/campaign@1\nid: C-WIRE\ngoal: G2\n"
            "status: active\nowner: mac\nreview_by: 2026-12-31\n---\n\n# C-WIRE\n",
            encoding="utf-8")
        write_json(self.root / "arch" / "GATES.json", {})
        self.commit_all("wiring files")
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        names = [check["name"] for check in payload["checks"]]
        self.assertEqual(names[-2:], ["campaign-check", "arch-check"])
        self.assertEqual(names[:5], [
            "post-merge tests pass", "tests count >= baseline",
            "implementation is ancestor of base", "envelope file exists on base",
            "working tree clean"])
        campaign = payload["checks"][-2]
        self.assertFalse(campaign["ok"], campaign)
        self.assertEqual(payload["status"], "CORRECTION_REQUIRED")
        self.assertEqual(self.envelope()["status"], "CORRECTION_REQUIRED")

    def test_legacy_fixture_keeps_the_pre_050_check_list(self) -> None:
        cp = self.run_post_merge("PASS")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual([check["name"] for check in payload["checks"]], [
            "post-merge tests pass", "tests count >= baseline",
            "implementation is ancestor of base", "envelope file exists on base",
            "working tree clean"])
        self.assertTrue(all(check["ok"] for check in payload["checks"]))
        self.assertEqual(payload["status"], "POST_MERGE_VERIFIED")


class CiWorkflowCase(unittest.TestCase):
    """The CI workflow runs the two new gates before a final status step."""

    RUN_RE = re.compile(r"^\s*run:[ \t]*(\S.*)$", re.MULTILINE)

    def test_ci_runs_arch_and_campaign_before_status(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("continue-on-error", text)
        runs = [match.strip() for match in self.RUN_RE.findall(text)]
        self.assertEqual(runs, [
            "python -B -m unittest discover -s tools/tests -v",
            "python tools/towerctl.py spec-lint --strict",
            "python tools/towerctl.py spec-coverage",
            "python tools/towerctl.py verify-ledger",
            "python tools/towerctl.py arch-check",
            "python tools/towerctl.py campaign-check",
            "python tools/towerctl.py status",
        ])
        self.assertEqual(runs[-1], "python tools/towerctl.py status")


if __name__ == "__main__":
    unittest.main()
