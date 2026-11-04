"""PILOT-071: ``task-supersede`` — the owner-only non-merge terminal state.

Each case builds a throw-away tower under the runner's ``TMP`` sandbox (ledger
rows are appended through the real ``towerctl`` helpers, hash chain included)
and drives the command through ``subprocess``, so exit codes and written bytes
are exactly what an operator observes::

    python -B tools/run_tests.py --pattern test_task_supersede.py

The contract under test: a ``delivered``/``rework`` card becomes
``superseded`` with one ``TASK_SUPERSEDE`` primary-ledger event, the record and
board agree, the id is voided, no envelope/MERGE appears, ``state-verify``
stays clean, ``where`` counts the card as terminal done, and every illegal
request (repeat, closed, accepted, non-owner, missing target) exits 2 without
writing a byte.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TCLI = TOOLS_DIR / "towerctl.py"
sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (TOOLS_DIR must be on sys.path first)

CURRENT_STATE = {"schema": "tower/current-state@1", "owner": {"name": "mac"},
                 "next_action": "", "blockers": []}
STAMP = "2026-11-04T00:00:00+08:00"
BASE_STATUSES = {"PILOT-069": "delivered", "PILOT-070": "closed",
                 "PILOT-071": "ready"}
ROADMAP_TEN = tuple(f"PILOT-{number:03d}" for number in range(61, 71))


def campaign_text(roadmap: tuple[str, ...], current: str) -> str:
    """A minimal active campaign whose roadmap drives ``where``."""
    lines = ["---", "schema: tower/campaign@1", "id: C-2026-Q4-04",
             "goal: G2", "status: active", "owner: mac",
             'objective: "交付硬化"', "key_results:", '  - "TASK_SUPERSEDE"',
             "roadmap:"]
    lines += [f"  - {task_id}" for task_id in roadmap]
    lines += [f"current: {current}", "task_forces:"]
    lines += [f"  - {task_id}" for task_id in roadmap if task_id != "PILOT-069"]
    lines += ['sequence: "061 → 070"', "stop_conditions:",
              '  - "drift != 0 立即停"', 'budget: "12 张卡 / 12 周"',
              "wip_limit: 1", "review_by: 2026-11-20", "---",
              "# C-2026-Q4-04 — 交付硬化", ""]
    return "\n".join(lines)


class SupersedeCase(unittest.TestCase):
    """A tower shaped like the live 069/070 hand-off."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-supersede-", ignore_cleanup_errors=True)
        self.base = Path(self._tmp.name)
        self.root = self.base / "tower"
        self.build_tower(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ----------------------------------------------------------
    def fresh(self, name: str, statuses: dict[str, str] | None = None) -> Path:
        """A brand-new tower for one refusal case (no cross-contamination)."""
        root = self.base / name
        self.build_tower(root, statuses)
        return root

    def build_tower(self, root: Path, statuses: dict[str, str] | None = None
                    ) -> None:
        statuses = {**BASE_STATUSES, **(statuses or {})}
        for name in ("primary", "ledger", "state", "supervision/envelopes"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "ledger" / "primary.jsonl").touch()
        (root / "ledger" / "supervision.jsonl").touch()
        self.write_json(root, "primary/CURRENT_STATE.json", CURRENT_STATE)
        self.write_json(root, "supervision/MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1", "entries": []})
        self.events(root, "PILOT-069", delivered=True)
        self.events(root, "PILOT-070", delivered=True, closed=True)
        for task_id, status in statuses.items():
            self.write_card(root, task_id, status)

    def events(self, root: Path, task_id: str, *, delivered: bool,
               closed: bool = False) -> None:
        """Hash-chained lifecycle rows that fold to the card's base status."""
        def add(event_type: str, **payload) -> None:
            towerctl.append_ledger(root, event_type, "primary",
                                   {"task": task_id, **payload})

        add("TASK_NEW", title=f"{task_id} card")
        add("DISPATCH", executor=f"exec-{task_id[-3:]}",
            worktree=f"pilot/worktrees/{task_id}")
        if delivered:
            add("DELIVER", evidence=0)
        if closed:
            add("CHECKBACK", reviewer="rev-070", verdict="PASS")
            add("ACCEPT", decision="D-PILOT-070")
            add("CLOSEOUT", closeout="tasks/PILOT-070/CLOSEOUT.md")

    def write_card(self, root: Path, task_id: str, status: str) -> None:
        """Write the record and its board row at the same status."""
        self.write_json(root, f"tasks/{task_id}/record.json", {
            "schema": "tower/task@1", "id": task_id, "title": f"{task_id} card",
            "status": status, "next": "test fixture"})
        board_path = root / "primary" / "TASK_BOARD.json"
        board = (json.loads(board_path.read_text(encoding="utf-8"))
                 if board_path.is_file() else {"schema": "tower/task-board@1",
                                               "tower_id": "tower-dsh",
                                               "tasks": []})
        tasks = [entry for entry in board["tasks"] if entry["id"] != task_id]
        tasks.append({"id": task_id, "title": f"{task_id} card",
                      "status": status})
        board["tasks"] = tasks
        self.write_json(root, "primary/TASK_BOARD.json", board)

    def write_json(self, root: Path, relpath: str, data) -> None:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def write_campaign(self, root: Path,
                       roadmap: tuple[str, ...], current: str) -> None:
        path = root / "command" / "campaigns" / "C-2026-Q4-04.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(campaign_text(roadmap, current), encoding="utf-8")

    # -- helpers ----------------------------------------------------------
    def cli(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
            capture_output=True, text=True, encoding="utf-8")

    def supersede(self, root: Path, task: str = "PILOT-069",
                  target: str = "PILOT-070", by: str = "mac",
                  reason: str = "070 replaces 069") -> subprocess.CompletedProcess:
        return self.cli(root, "task-supersede", "--task", task,
                        "--by-task", target, "--reason", reason, "--by", by)

    def record(self, root: Path, task_id: str) -> dict:
        return json.loads((root / "tasks" / task_id / "record.json")
                          .read_text(encoding="utf-8"))

    def board_entry(self, root: Path, task_id: str) -> dict:
        board = json.loads((root / "primary" / "TASK_BOARD.json")
                           .read_text(encoding="utf-8"))
        return next(entry for entry in board["tasks"] if entry["id"] == task_id)

    def ledger_events(self, root: Path, name: str) -> list[dict]:
        path = root / "ledger" / f"{name}.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def registry(self, root: Path) -> dict:
        path = root / "state" / "TASK_IDS.json"
        return json.loads(path.read_text(encoding="utf-8"))["ids"]

    def snapshot(self, root: Path) -> dict[str, bytes]:
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in sorted(root.rglob("*")) if path.is_file()}

    def assert_refused(self, root: Path, args: tuple[str, ...],
                       *needles: str) -> dict:
        before = self.snapshot(root)
        cp = self.cli(root, *args)
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        blob = " ".join(payload["errors"]).lower()
        for needle in needles:
            self.assertIn(needle.lower(), blob, msg=str(payload["errors"]))
        self.assertEqual(self.snapshot(root), before,
                         msg="a refusal must write nothing")
        return payload

    def where_json(self, root: Path) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.cli(root, "where", "--json")
        return cp, json.loads(cp.stdout) if cp.stdout.strip() else {}

    def mark_superseded(self, root: Path, task_id: str = "PILOT-069",
                        target: str = "PILOT-070") -> None:
        """Simulate a crash after record/board but before the ledger event."""
        self.write_card(root, task_id, "superseded")
        record = self.record(root, task_id)
        record.update({"superseded_by": target, "superseded_at": STAMP})
        self.write_json(root, f"tasks/{task_id}/record.json", record)

    def set_registry_status(self, root: Path, task_id: str, status: str) -> None:
        path = root / "state" / "TASK_IDS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["ids"][task_id]["status"] = status
        self.write_json(root, "state/TASK_IDS.json", data)


class SupersedeTransitionCase(SupersedeCase):
    """delivered -> superseded: record, board, ledger, id, no envelope/MERGE."""

    def test_delivered_card_becomes_superseded_everywhere(self) -> None:
        cp = self.supersede(self.root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "superseded")
        self.assertEqual(payload["superseded_by"], "PILOT-070")
        self.assertFalse(payload["repaired"])

        record = self.record(self.root, "PILOT-069")
        self.assertEqual(record["status"], "superseded")
        self.assertEqual(record["superseded_by"], "PILOT-070")
        self.assertEqual(self.board_entry(self.root, "PILOT-069")["status"],
                         "superseded")

        events = [event for event in self.ledger_events(self.root, "primary")
                  if event["type"] == "TASK_SUPERSEDE"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "owner")
        self.assertEqual(sorted(events[0]["payload"]),
                         ["at", "by", "reason", "superseded_by", "task"])
        self.assertEqual(events[0]["payload"]["task"], "PILOT-069")
        self.assertEqual(events[0]["payload"]["by"], "mac")
        self.assertEqual(events[0]["payload"]["superseded_by"], "PILOT-070")
        self.assertEqual(events[0]["payload"]["reason"], "070 replaces 069")

        registry = self.registry(self.root)
        self.assertEqual(registry["PILOT-069"]["status"], "void")
        # The target and other cards keep their registry status.
        self.assertEqual(registry["PILOT-070"]["status"], "closed")

        # No envelope, no MERGE: the card is retired, never merged.
        envelopes = list((self.root / "supervision" / "envelopes").glob("*.json"))
        self.assertEqual(envelopes, [])
        for name in ("primary", "supervision"):
            types = [event["type"]
                     for event in self.ledger_events(self.root, name)]
            self.assertNotIn("MERGE", types)
        self.assertEqual(self.ledger_events(self.root, "supervision"), [])

        verify = self.cli(self.root, "state-verify")
        self.assertEqual(verify.returncode, 0, msg=verify.stdout + verify.stderr)
        result = json.loads(verify.stdout)
        self.assertEqual(result["drift"], [])
        self.assertTrue(result["ok"])

    def test_supersede_never_fakes_review_or_acceptance(self) -> None:
        record_before = self.record(self.root, "PILOT-069")
        self.supersede(self.root)
        record = self.record(self.root, "PILOT-069")
        for field in ("review", "decision", "closeout", "evidence", "executor"):
            self.assertEqual(record.get(field), record_before.get(field),
                             msg=field)
        self.assertIsNone(record.get("accepted_at"))
        # PILOT-069 gains no ACCEPT/CLOSEOUT event; 070 keeps its own ACCEPT.
        accepted = [event["payload"]["task"]
                    for event in self.ledger_events(self.root, "primary")
                    if event["type"] == "ACCEPT"]
        self.assertEqual(accepted, ["PILOT-070"])
        closed = [event["payload"]["task"]
                  for event in self.ledger_events(self.root, "primary")
                  if event["type"] == "CLOSEOUT"]
        self.assertEqual(closed, ["PILOT-070"])

    def test_rework_card_can_be_superseded(self) -> None:
        root = self.fresh("rework", {"PILOT-071": "rework"})
        cp = self.supersede(root, task="PILOT-071", target="PILOT-070")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.record(root, "PILOT-071")["status"],
                         "superseded")
        self.assertEqual(self.registry(root)["PILOT-071"]["status"], "void")

    def test_superseded_card_is_terminal_for_accept_and_close(self) -> None:
        root = self.fresh("terminal")
        cp = self.supersede(root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        before = self.snapshot(root)
        accept = self.cli(root, "accept", "--task", "PILOT-069",
                          "--decision", "D-069")
        self.assertEqual(accept.returncode, 2, msg=accept.stdout + accept.stderr)
        self.assertNotIn("Traceback", accept.stdout + accept.stderr)
        close = self.cli(root, "close", "--task", "PILOT-069")
        self.assertEqual(close.returncode, 2, msg=close.stdout + close.stderr)
        self.assertNotIn("Traceback", close.stdout + close.stderr)
        check = self.cli(root, "check", "--task", "PILOT-069",
                         "--phase", "accept")
        self.assertEqual(check.returncode, 2, msg=check.stdout + check.stderr)
        self.assertEqual(self.snapshot(root), before,
                         msg="terminal refusals must write nothing")


class SupersedeRefusalCase(SupersedeCase):
    """Every illegal request exits 2 with zero writes."""

    def test_repeat_supersede_is_refused(self) -> None:
        first = self.supersede(self.root)
        self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
        self.assert_refused(
            self.root,
            ("task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-070", "--reason", "again", "--by", "mac"),
            "already superseded")

    def test_closed_card_is_refused(self) -> None:
        root = self.fresh("closed")
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-070", "--by-task",
             "PILOT-071", "--reason", "x", "--by", "mac"),
            "cannot be superseded", "closed")

    def test_accepted_card_is_refused(self) -> None:
        root = self.fresh("accepted", {"PILOT-071": "accepted"})
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-071", "--by-task",
             "PILOT-069", "--reason", "x", "--by", "mac"),
            "cannot be superseded", "accepted")

    def test_non_owner_is_refused(self) -> None:
        root = self.fresh("intruder")
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-070", "--reason", "x", "--by", "intruder"),
            "owner", "intruder")

    def test_missing_target_card_is_refused(self) -> None:
        root = self.fresh("missing-target")
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-999", "--reason", "x", "--by", "mac"),
            "target card missing", "PILOT-999")

    def test_self_supersede_is_refused(self) -> None:
        root = self.fresh("self")
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-069", "--reason", "x", "--by", "mac"),
            "itself")

    def test_empty_reason_is_refused(self) -> None:
        root = self.fresh("reason")
        self.assert_refused(
            root,
            ("task-supersede", "--task", "PILOT-069", "--by-task",
             "PILOT-070", "--reason", "  ", "--by", "mac"),
            "reason")


class SupersedeRepairCase(SupersedeCase):
    """A crash between the tombstone's halves is completed by the next retry."""

    TASK = "PILOT-069"

    def supersede_events(self, root: Path) -> list[dict]:
        return [event for event in self.ledger_events(root, "primary")
                if event["type"] == "TASK_SUPERSEDE"]

    def assert_converged(self, root: Path) -> None:
        record = self.record(root, self.TASK)
        self.assertEqual(record["status"], "superseded")
        self.assertEqual(record["superseded_by"], "PILOT-070")
        self.assertEqual(self.board_entry(root, self.TASK)["status"],
                         "superseded")
        self.assertEqual(self.registry(root)[self.TASK]["status"], "void")
        self.assertEqual(len(self.supersede_events(root)), 1)
        verify = self.cli(root, "state-verify")
        self.assertEqual(verify.returncode, 0, msg=verify.stdout + verify.stderr)
        self.assertEqual(json.loads(verify.stdout)["drift"], [])

    def test_record_first_crash_is_repaired(self) -> None:
        root = self.fresh("record-first")
        self.mark_superseded(root)
        self.assertEqual(self.supersede_events(root), [])
        cp = self.supersede(root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["repaired"])
        self.assert_converged(root)
        before = self.snapshot(root)
        again = self.supersede(root)
        self.assertEqual(again.returncode, 2, msg=again.stdout + again.stderr)
        self.assertEqual(self.snapshot(root), before)

    def test_ledger_first_crash_is_repaired_without_a_second_event(self) -> None:
        root = self.fresh("ledger-first")
        towerctl.append_ledger(root, "TASK_SUPERSEDE", "owner", {
            "task": self.TASK, "by": "mac", "reason": "070 replaces 069",
            "superseded_by": "PILOT-070", "at": STAMP})
        cp = self.supersede(root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertTrue(json.loads(cp.stdout)["repaired"])
        self.assert_converged(root)

    def test_void_gap_is_repaired_without_a_second_event(self) -> None:
        root = self.fresh("void-gap")
        first = self.supersede(root)
        self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
        self.assertFalse(json.loads(first.stdout)["repaired"])
        self.set_registry_status(root, self.TASK, "active")
        retry = self.supersede(root)
        self.assertEqual(retry.returncode, 0, msg=retry.stdout + retry.stderr)
        self.assertTrue(json.loads(retry.stdout)["repaired"])
        self.assert_converged(root)


class WhereTerminalCase(SupersedeCase):
    """``where`` counts a superseded roadmap node as terminal done."""

    def test_where_counts_superseded_as_done(self) -> None:
        root = self.fresh("where")
        self.write_campaign(root, ("PILOT-061", "PILOT-069", "PILOT-070"),
                            "PILOT-070")
        self.write_card(root, "PILOT-061", "closed")
        cp = self.supersede(root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        run, data = self.where_json(root)
        self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
        statuses = {node["id"]: node["status"] for node in data["nodes"]}
        self.assertEqual(statuses["PILOT-069"], "done")
        self.assertEqual(data["index"], 3)
        self.assertEqual(data["total"], 3)
        self.assertIsNone(data["next"])
        self.assertEqual(data["blocked"], [])

        human = self.cli(root, "where")
        self.assertEqual(human.returncode, 0, msg=human.stdout + human.stderr)
        self.assertIn("[✅069]", human.stdout)
        self.assertIn("位置 3/3", human.stdout)

    def test_where_still_reads_a_delivered_node_as_active(self) -> None:
        root = self.fresh("where-delivered")
        self.write_campaign(root, ("PILOT-061", "PILOT-069", "PILOT-070"),
                            "PILOT-069")
        self.write_card(root, "PILOT-061", "closed")
        _, data = self.where_json(root)
        statuses = {node["id"]: node["status"] for node in data["nodes"]}
        self.assertEqual(statuses["PILOT-069"], "active")
        self.assertEqual(data["next"], "PILOT-069")


class RealFixtureCase(SupersedeCase):
    """The real 069/070 shape: a ten-node C-04 roadmap reaches 10/10."""

    def test_real_069_070_fixture_reaches_ten_of_ten(self) -> None:
        root = self.fresh("real")
        self.write_campaign(root, ROADMAP_TEN, "PILOT-070")
        for task_id in ROADMAP_TEN[:-2]:          # 061..068
            self.write_card(root, task_id, "closed")
        cp = self.supersede(root)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        run, data = self.where_json(root)
        self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
        self.assertEqual(data["total"], 10)
        self.assertEqual(data["index"], 10)
        self.assertIsNone(data["next"])
        self.assertEqual([node["id"] for node in data["nodes"]],
                         list(ROADMAP_TEN))
        self.assertTrue(all(node["status"] == "done" for node in data["nodes"]))
        self.assertEqual(data["wip"], {"in_flight": 0, "limit": 1})

        verify = self.cli(root, "state-verify")
        self.assertEqual(verify.returncode, 0, msg=verify.stdout + verify.stderr)
        self.assertEqual(json.loads(verify.stdout)["drift"], [])


if __name__ == "__main__":
    unittest.main()
