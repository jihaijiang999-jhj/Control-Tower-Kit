"""Tests for PILOT-043: record-layer depth (ADR-0006).

PILOT-042 recorded completions and ``dispatch.base_sha`` twice (record half +
ledger half) but only ever read the record.  PILOT-043 makes the ledger half
authoritative on the read side:

* ``deliver`` re-checks every completion its diff actually used against a
  matching ``COMPLETION_ADDED`` (task+path), requires the owner's signature and
  field-for-field agreement, and writes nothing when either half is missing or
  disagreeing;
* ``state-verify`` audits ``record.dispatch.base_sha`` against the latest
  ``DISPATCH`` payload (``dispatch_base_mismatch`` / ``dispatch_base_missing``),
  reports ``COMPLETION_ADDED`` tasks with no record (``completion_orphan``) and
  record entries that disagree with their event (``completion_mismatch``), and
  still audits completions of a task whose lifecycle replay was skipped.

The deliver fixture mirrors ``test_completion_and_base.py``: a real git
repository in ``<kit>/tower-dsh`` with a real ``git worktree`` for the task.
The state-verify fixture is a ledgers-and-files tower with no git requirement.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py
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
TASK_ID = "TEST-043"
FIXED_TIME = "2026-10-20T00:00:00+08:00"
OTHER_TIME = "2026-10-19T00:00:00+08:00"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
PROOF_REL = "work/proof.txt"
OWNER = "mac"
REASON = "6.11 authorized completion: helper needed by the task"
DECISION = "D-043"
COMPLETION_PATH = f"{WORKTREE_REL}/tower-dsh/tools/helper.py"
BASE_SHA = "a" * 40
OTHER_SHA = "b" * 40

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)
# The git/CLI/JSON helpers are generic; importing them keeps this module from
# duplicating a second copy of the same 15-line fixture blocks (shape ratchet).
from test_completion_and_base import read_json, run_cli, run_git, write_json  # noqa: E402


def completion_entry(path: str, **overrides) -> dict:
    entry = {"task": TASK_ID, "path": path, "by": OWNER, "reason": REASON,
             "decision": DECISION, "at": FIXED_TIME}
    entry.update(overrides)
    return entry


class RecordLayerGitFixture(unittest.TestCase):
    """A tower inside a real git repository with a real ``git worktree``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-043-git-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.tower = self.kit / "tower-dsh"
        self.worktree = self.tower / WORKTREE_REL
        self.prepare_repository()
        self.write_tower_state()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def prepare_repository(self) -> None:
        self.kit.mkdir(parents=True, exist_ok=True)
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        (self.kit / ".gitignore").write_text(
            "tower-dsh/pilot/worktrees/\n", encoding="utf-8")
        (self.tower / "tools").mkdir(parents=True, exist_ok=True)
        (self.tower / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (self.tower / "pilot").mkdir(parents=True, exist_ok=True)
        (self.tower / "pilot" / f"{TASK_ID}.spec.json").write_text(
            "{}\n", encoding="utf-8")
        self.assertEqual(run_git(self.kit, "init").returncode, 0)
        self.assertEqual(
            run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        self.assertEqual(run_git(self.kit, "add", "-A").returncode, 0)
        cp = run_git(self.kit, "commit", "-m", "base")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        cp = run_git(self.kit, "worktree", "add", str(self.worktree),
                     "-b", f"pilot/{TASK_ID}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

    def write_tower_state(self) -> None:
        write_json(self.tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "primary": {"id": "ctl-test"},
            "owner": {"name": OWNER},
        })
        write_json(self.tower / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        (self.tower / "ledger").mkdir(parents=True, exist_ok=True)
        (self.tower / "ledger" / "primary.jsonl").touch()
        (self.tower / "tasks" / TASK_ID).mkdir(parents=True, exist_ok=True)
        self.save_record(self.task_record())

    def task_record(self) -> dict:
        return {
            "schema": "tower/task@1", "id": TASK_ID, "title": TASK_ID,
            "status": "dispatched", "authority": "workspace_write",
            "worktree": WORKTREE_REL,
            "allowed_paths": [f"{WORKTREE_REL}/tower-dsh/tools/x.py"],
            "dispatch": {"executor": "exec-a", "worktree": WORKTREE_REL,
                         "at": FIXED_TIME},
            "evidence": [],
        }

    # -- builders ---------------------------------------------------------
    def save_record(self, record: dict) -> None:
        write_json(self.tower / "tasks" / TASK_ID / "record.json", record)

    def load_record(self) -> dict:
        return read_json(self.tower / "tasks" / TASK_ID / "record.json")

    def ledger_events(self) -> list[dict]:
        path = self.tower / "ledger" / "primary.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def completion_events(self) -> list[dict]:
        return [event for event in self.ledger_events()
                if event["type"] == "COMPLETION_ADDED"]

    def write_worktree(self, relpath: str, text: str) -> None:
        path = self.worktree / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit_worktree(self, message: str) -> None:
        self.assertEqual(run_git(self.worktree, "add", "-A").returncode, 0)
        cp = run_git(self.worktree, "commit", "-m", message)
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)

    def deliver(self) -> subprocess.CompletedProcess:
        proof = self.tower / PROOF_REL
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("proof of work\n", encoding="utf-8")
        return run_cli(self.tower, "deliver", "--task", TASK_ID,
                       "--evidence", PROOF_REL)

    def completion_add(self, *, path: str = COMPLETION_PATH) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "completion-add", "--task", TASK_ID,
                       "--path", path, "--by", OWNER, "--reason", REASON,
                       "--decision", DECISION)

    def append_completion_event(self, payload: dict) -> None:
        towerctl.append_ledger(self.tower, "COMPLETION_ADDED", "primary", payload)

    def append_dispatch_event(self, base_sha: str) -> None:
        towerctl.append_ledger(self.tower, "DISPATCH", "primary",
                               {"task": TASK_ID, "base_sha": base_sha})

    def git_sha(self, cwd: Path, *args: str) -> str:
        cp = run_git(cwd, *args)
        self.assertEqual(cp.returncode, 0, msg=cp.stderr + cp.stdout)
        return cp.stdout.strip()

    def kit_main_sha(self) -> str:
        return self.git_sha(self.kit, "rev-parse", "main")

    def worktree_head_sha(self) -> str:
        return self.git_sha(self.worktree, "rev-parse", "HEAD")

    def set_record_base_sha(self, base_sha: str | None) -> None:
        record = self.load_record()
        if base_sha is None:
            record["dispatch"].pop("base_sha", None)
        else:
            record["dispatch"]["base_sha"] = base_sha
        self.save_record(record)

    def evidence_dir(self) -> Path:
        return self.tower / "tasks" / TASK_ID / "evidence"

    def assert_failed_with(self, cp: subprocess.CompletedProcess, needle: str) -> None:
        self.assertEqual(cp.returncode, 2,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(needle, "\n".join(payload["errors"]))

    def assert_delivery_wrote_nothing(self) -> None:
        record = self.load_record()
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["evidence"], [])
        self.assertFalse(self.evidence_dir().exists())
        self.assertNotIn("DELIVER", [event["type"] for event in self.ledger_events()])


class DeliverBackingTestCase(RecordLayerGitFixture):
    """``deliver`` only accepts completions whose ledger half backs them."""

    def test_backed_completion_is_accepted_and_reported(self) -> None:
        cp = self.completion_add()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("owner-backed completion")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertTrue(out["scope_checked"])
        self.assertEqual(out["scope_files"], ["tower-dsh/tools/helper.py"])
        self.assertEqual(out["scope_completions"], ["tower-dsh/tools/helper.py"])
        self.assertEqual(self.load_record()["status"], "delivered")
        self.assertTrue((self.evidence_dir() / "proof.txt").exists())

    def test_forged_record_completion_is_rejected_with_zero_writes(self) -> None:
        record = self.load_record()
        record["completions"] = [completion_entry(COMPLETION_PATH)]
        self.save_record(record)
        self.assertEqual(self.completion_events(), [])

        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("hand-written record completion")

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "completion not backed by COMPLETION_ADDED")
        self.assert_delivery_wrote_nothing()

    def test_record_event_field_mismatch_is_rejected(self) -> None:
        self.assertEqual(self.completion_add().returncode, 0)
        original = self.load_record()["completions"][0]
        cases = {
            "by": {"by": "someone-else"},
            "reason": {"reason": "rewritten reason"},
            "decision": {"decision": "D-REWRITTEN"},
            "at": {"at": OTHER_TIME},
        }
        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("completion path change")
        for label, overrides in cases.items():
            with self.subTest(field=label):
                entry = dict(original)
                entry.update(overrides)
                record = self.load_record()
                record["completions"] = [entry]
                self.save_record(record)
                deliver = self.deliver()
                self.assert_failed_with(
                    deliver, "completion record does not match ledger event")
                self.assert_delivery_wrote_nothing()

    def test_event_by_non_owner_is_rejected(self) -> None:
        record = self.load_record()
        entry = completion_entry(COMPLETION_PATH, by="intruder")
        record["completions"] = [entry]
        self.save_record(record)
        self.append_completion_event(entry)
        self.write_worktree("tower-dsh/tools/helper.py", "helper = 1\n")
        self.commit_worktree("non-owner completion event")

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "completion record does not match ledger event")
        self.assertIn("is not owner", "\n".join(json.loads(deliver.stdout)["errors"]))
        self.assert_delivery_wrote_nothing()

    def test_empty_event_fields_are_rejected(self) -> None:
        cases = {
            "by": "helper_by.py",
            "reason": "helper_reason.py",
            "decision": "helper_decision.py",
        }
        paths = {field: f"{WORKTREE_REL}/tower-dsh/tools/{name}"
                 for field, name in cases.items()}
        for name in cases.values():
            self.write_worktree(f"tower-dsh/tools/{name}", "helper = 1\n")
        self.commit_worktree("completion path changes")
        record = self.load_record()
        record["completions"] = [completion_entry(path)
                                 for path in paths.values()]
        self.save_record(record)
        for field, path in paths.items():
            with self.subTest(field=field):
                self.append_completion_event(
                    completion_entry(path, **{field: ""}))
                deliver = self.deliver()
                self.assert_failed_with(
                    deliver, "completion record does not match ledger event")
                self.assertIn(f"ledger {field} is empty",
                              "\n".join(json.loads(deliver.stdout)["errors"]))
                self.assert_delivery_wrote_nothing()


class DispatchBaseAuthorityTestCase(RecordLayerGitFixture):
    """``deliver`` takes its diff base from the DISPATCH event, not the record."""

    def test_record_and_event_base_sha_match_delivers(self) -> None:
        base = self.kit_main_sha()
        self.append_dispatch_event(base)
        self.set_record_base_sha(base)

        self.write_worktree("tower-dsh/tools/x.py", "x = 2\n")
        self.commit_worktree("in scope change")

        deliver = self.deliver()
        self.assertEqual(deliver.returncode, 0, msg=deliver.stdout + deliver.stderr)
        out = json.loads(deliver.stdout)
        self.assertEqual(out["scope_files"], ["tower-dsh/tools/x.py"])
        self.assertEqual(self.load_record()["status"], "delivered")

    def test_record_base_sha_rewritten_to_head_is_rejected(self) -> None:
        base = self.kit_main_sha()
        self.append_dispatch_event(base)
        self.set_record_base_sha(base)

        # The attack: move the record baseline to HEAD so the diff looks empty,
        # while the out-of-scope change stays on the branch.  The DISPATCH event
        # still points at the branch base, so deliver must reject before the
        # diff is computed.
        self.write_worktree("tower-dsh/pilot/other.json", '{"v": 2}\n')
        self.commit_worktree("out of scope change")
        head = self.worktree_head_sha()
        self.set_record_base_sha(head)

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "dispatch base_sha does not match DISPATCH event")
        self.assertIn(head, "\n".join(json.loads(deliver.stdout)["errors"]))
        self.assert_delivery_wrote_nothing()

    def test_record_base_sha_without_dispatch_event_is_rejected(self) -> None:
        self.set_record_base_sha(self.kit_main_sha())

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "is not backed by a DISPATCH event")
        self.assert_delivery_wrote_nothing()

    def test_event_base_sha_missing_from_record_is_rejected(self) -> None:
        base = self.kit_main_sha()
        self.append_dispatch_event(base)
        self.set_record_base_sha(None)

        deliver = self.deliver()
        self.assert_failed_with(
            deliver, "dispatch base_sha does not match DISPATCH event")
        self.assert_delivery_wrote_nothing()


def build_verify_tower(root: Path, task: str, *, base_sha: str | None) -> None:
    """A board/queue/record tower whose ledger half can be forged separately."""
    for directory in ("ledger", "primary", "tasks",
                      "supervision", "supervision/envelopes"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "primary": {"id": "ctl-test"},
        "owner": {"name": OWNER},
    })
    write_json(root / "primary" / "TASK_BOARD.json", {
        "schema": "tower/task-board@1", "tower_id": "tower-dsh",
        "tasks": [{"id": task, "title": task, "status": "delivered"}]})
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})
    towerctl.append_ledger(root, "TASK_NEW", "primary", {"task": task})
    dispatch = {"task": task}
    if base_sha is not None:
        dispatch["base_sha"] = base_sha
    towerctl.append_ledger(root, "DISPATCH", "primary", dispatch)
    towerctl.append_ledger(root, "DELIVER", "primary", {"task": task})


def put_verify_record(root: Path, task: str, *, status: str = "delivered",
                      completions=None, dispatch=None) -> None:
    record = {"schema": "tower/task@1", "id": task, "title": task,
              "status": status}
    if dispatch is None:
        dispatch = {"executor": "exec-a", "at": FIXED_TIME,
                    "base_sha": BASE_SHA}
    if dispatch is not False:
        record["dispatch"] = dispatch
    if completions is not None:
        record["completions"] = completions
    write_json(root / "tasks" / task / "record.json", record)


class RecordLayerVerifyFixture(unittest.TestCase):
    """``state-verify`` audits both halves of the record layer."""

    TASK = "T-943"
    SKIPPED = "T-943-SKIP"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-043-verify-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower-dsh"
        build_verify_tower(self.root, self.TASK, base_sha=BASE_SHA)
        put_verify_record(self.root, self.TASK)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def put_record(self, completions=None, dispatch=None, status="delivered",
                   task=None) -> None:
        put_verify_record(self.root, task or self.TASK, status=status,
                          completions=completions, dispatch=dispatch)

    def state_verify(self) -> tuple[dict, int]:
        proc = run_cli(self.root, "state-verify")
        return json.loads(proc.stdout), proc.returncode

    def drift_kinds(self, out: dict) -> list[str]:
        return sorted(item["kind"] for item in out["drift"])

    def completion_add(self, path: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, "completion-add", "--task", self.TASK,
                       "--path", path, "--by", OWNER, "--reason", REASON,
                       "--decision", DECISION)

    def append_completion(self, payload: dict) -> None:
        towerctl.append_ledger(self.root, "COMPLETION_ADDED", "primary", payload)

    # -- base_sha audit ---------------------------------------------------
    def test_matching_base_sha_has_no_dispatch_drift(self) -> None:
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])

    def test_tampered_base_sha_is_a_mismatch(self) -> None:
        self.put_record(dispatch={"executor": "exec-a", "at": FIXED_TIME,
                                  "base_sha": OTHER_SHA})
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["dispatch_base_mismatch"])
        row = out["drift"][0]
        self.assertEqual(row["target"], self.TASK)
        self.assertEqual(row["expected"], BASE_SHA)
        self.assertEqual(row["actual"], OTHER_SHA)

    def test_event_base_sha_missing_from_record_is_reported(self) -> None:
        self.put_record(dispatch={"executor": "exec-a", "at": FIXED_TIME})
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["dispatch_base_missing"])
        self.assertEqual(out["drift"][0]["expected"], BASE_SHA)
        self.assertIsNone(out["drift"][0]["actual"])

    # -- completion audit -------------------------------------------------
    def test_valid_completion_pair_has_no_form_drift(self) -> None:
        self.assertEqual(self.completion_add(f"{WORKTREE_REL}/tower-dsh/tools/x.py")
                         .returncode, 0)
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertFalse([kind for kind in self.drift_kinds(out)
                          if kind.startswith("completion")])
        self.assertFalse([kind for kind in self.drift_kinds(out)
                          if kind.startswith("dispatch")])

    def test_forged_completion_record_is_unbacked(self) -> None:
        self.put_record(completions=[completion_entry("pilot/x.py",
                                                      task=self.TASK)])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_unbacked"])

    def test_completion_field_mismatch_is_reported(self) -> None:
        path = f"{WORKTREE_REL}/tower-dsh/tools/x.py"
        self.assertEqual(self.completion_add(path).returncode, 0)
        record = read_json(self.root / "tasks" / self.TASK / "record.json")
        record["completions"][0]["reason"] = "rewritten after the fact"
        write_json(self.root / "tasks" / self.TASK / "record.json", record)

        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_mismatch"])
        row = out["drift"][0]
        self.assertEqual(row["target"], self.TASK)
        self.assertEqual(row["path"], path)
        self.assertEqual(row["expected"]["reason"], REASON)
        self.assertEqual(row["actual"]["reason"], "rewritten after the fact")

    def test_orphan_completion_event_is_reported(self) -> None:
        self.append_completion(completion_entry(
            "pilot/orphan.py", task="T-943-ORPHAN"))
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_orphan"])
        self.assertEqual(out["drift"][0]["target"], "T-943-ORPHAN")

    # -- skipped tasks and legacy records ---------------------------------
    def test_skipped_task_with_completions_is_still_audited(self) -> None:
        self.put_record(task=self.SKIPPED, status="delivered",
                        completions=[completion_entry("pilot/skipped.py",
                                                      task=self.SKIPPED)])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_unbacked"])
        skipped = {(item["kind"], item["target"], item["reason"])
                   for item in out["skipped"]}
        self.assertIn(("task", self.SKIPPED, "no_lifecycle_events"), skipped)

    def test_skipped_task_with_mismatched_event_is_audited(self) -> None:
        entry = completion_entry("pilot/skipped.py", task=self.SKIPPED)
        self.append_completion(entry)
        mismatched = dict(entry)
        mismatched["decision"] = "D-REWRITTEN"
        self.put_record(task=self.SKIPPED, status="delivered",
                        completions=[mismatched])
        out, code = self.state_verify()
        self.assertEqual(code, 2, out)
        self.assertEqual(self.drift_kinds(out), ["completion_mismatch"])
        self.assertEqual(out["drift"][0]["target"], self.SKIPPED)

    def test_legacy_skipped_task_without_completions_adds_nothing(self) -> None:
        self.put_record(task=self.SKIPPED)
        out, code = self.state_verify()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["drift"], [])
        skipped = {(item["kind"], item["target"], item["reason"])
                   for item in out["skipped"]}
        self.assertIn(("task", self.SKIPPED, "no_lifecycle_events"), skipped)


class LegacyRecordVerifyTestCase(unittest.TestCase):
    """A legacy tower with no completions and no base_sha stays clean."""

    TASK = "T-944"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-043-legacy-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name) / "tower-dsh"
        build_verify_tower(self.root, self.TASK, base_sha=None)
        put_verify_record(self.root, self.TASK, dispatch={
            "executor": "exec-a", "at": FIXED_TIME})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_legacy_record_adds_no_drift_or_extra_skip(self) -> None:
        proc = run_cli(self.root, "state-verify")
        out = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(out["drift"], [])
        self.assertEqual([item["kind"] for item in out["skipped"]],
                         ["authority_state"])
        self.assertEqual(out["skipped_count"], 1)


if __name__ == "__main__":
    unittest.main()
