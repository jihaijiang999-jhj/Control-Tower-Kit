"""PILOT-074: VERIFIED requires a MERGE fact; historical backfill and drift.

External review found 065--068 in ``POST_MERGE_VERIFIED`` with no ``MERGE``
event and no ``merge_commit``: verified did not mean "the tower merged it".
This file pins the fix:

* ``post-merge`` on a 074+ envelope only accepts a ``MERGED`` source, a
  ``MERGE``/``MERGE_HISTORICAL`` supervision event and a merge commit that
  resolves, sits on ``origin/<base>`` and carries the implementation head as
  its second parent.  Every refusal is exit 2 with zero writes and no
  ``POST_MERGE_VERIFIED``;
* ``state-verify`` reports ``verified_without_merge`` for a verified envelope
  with no merge fact (and for a base-side envelope whose second parent is not
  the implementation);
* ``envelope-recover --historical`` backfills the missing fact for a pre-074
  verified envelope only, without touching status, ``admin`` or verified;
* legacy pre-074 ``CORRECTION_REQUIRED -> POST_MERGE_VERIFIED`` still replays
  clean while 074+ is refused.

Each test builds a throw-away git repository plus a bare ``origin`` under the
runner's ``TMP`` sandbox, so no network or real tower state is involved.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_verified_merge_fact -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import tower_envelope  # noqa: E402  (needs TOOLS_DIR on sys.path)
import towerctl  # noqa: E402

TCLI = TOOLS_DIR / "towerctl.py"
TOWER = "tower-dsh"
BASE = "main"
BRANCH = "feature/merge-fact"
SUPERVISOR = "sup-074"
PRIMARY = "ctl-074"
TIME = "2026-11-04T00:00:00+08:00"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**dict(os.environ), **GIT_IDENTITY}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess:
    cp = run_git(repo, *args)
    if cp.returncode != 0:
        raise AssertionError(f"git exit {cp.returncode}: {cp.stdout}{cp.stderr}")
    return cp


class _MergeFactKit(unittest.TestCase):
    """A tower whose ``main`` carries a real no-ff merge, and a bare origin."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-merge-fact-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / TOWER
        self.origin = self.tmp / "origin.git"
        for directory in ("ledger", "primary", "state",
                          "supervision/envelopes"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("primary.jsonl", "supervision.jsonl"):
            (self.root / "ledger" / name).write_text("", encoding="utf-8")
        self.write_tower_state()
        self.build_repo()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ---------------------------------------------------------
    def write_tower_state(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": TOWER,
            "role": "primary", "phase": "TEST", "owner": {"name": "mac"},
            "primary": {"id": PRIMARY}})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": TOWER,
            "role": "supervision", "phase": "TEST",
            "supervisor": {"id": SUPERVISOR}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})

    def commit(self, message: str) -> str:
        git_ok(self.kit, "add", "-A")
        git_ok(self.kit, "-c", "commit.gpgsign=false", "commit", "-m", message)
        return git_ok(self.kit, "rev-parse", "HEAD").stdout.strip()

    def build_repo(self) -> None:
        """Base commit, implementation branch, a real merge and its origin."""
        self.kit.mkdir(parents=True, exist_ok=True)
        git_ok(self.kit, "init")
        git_ok(self.kit, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        tests = self.kit / "tests"
        tests.mkdir()
        (tests / "test_smoke.py").write_text(
            "import unittest\n\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_smoke(self):\n"
            "        self.assertTrue(True)\n", encoding="utf-8")
        self.base_sha = self.commit("base")
        git_ok(self.kit, "checkout", "-b", BRANCH)
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation = self.commit("implementation")
        git_ok(self.kit, "checkout", BASE)
        git_ok(self.kit, "-c", "commit.gpgsign=false", "merge", "--no-ff",
               BRANCH, "-m", "merge the implementation")
        self.merge_commit = git_ok(self.kit, "rev-parse", "HEAD").stdout.strip()
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        git_ok(self.kit, "remote", "add", "origin",
               str(self.origin).replace("\\", "/"))
        git_ok(self.kit, "push", "origin", BASE)

    def other_merge(self) -> str:
        """A real merge whose second parent is *not* this implementation."""
        git_ok(self.kit, "checkout", "-b", "other", self.base_sha)
        (self.kit / "other.txt").write_text("other\n", encoding="utf-8")
        self.commit("other implementation")
        git_ok(self.kit, "checkout", BASE)
        git_ok(self.kit, "-c", "commit.gpgsign=false", "merge", "--no-ff",
               "other", "-m", "merge another branch")
        other = git_ok(self.kit, "rev-parse", "HEAD").stdout.strip()
        git_ok(self.kit, "push", "origin", BASE)
        return other

    # -- tower builders --------------------------------------------------
    def envelope_identity(self, card: str) -> tuple[str, str]:
        return f"ENV-PILOT-{card}", f"PILOT-{card}"

    def write_envelope(self, card: str, status: str,
                       merge_commit: str | None,
                       base_side: bool = True) -> str:
        envelope_id, task = self.envelope_identity(card)
        write_json(self.root / "supervision" / "envelopes"
                   / f"{envelope_id}.json", {
                       "schema": "tower/merge-envelope@1",
                       "envelope_id": envelope_id, "task": task,
                       "repository": "..", "branch": BRANCH, "base": BASE,
                       "envelope_path": f"merge-envelopes/{envelope_id}.json",
                       "implementation_head_sha": self.implementation,
                       "envelope_head_sha": self.merge_commit,
                       "base_side": base_side, "tests_baseline": 1,
                       "status": status, "merge_commit": merge_commit})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json", {
            "schema": "tower/merge-queue@1", "entries": [{
                "envelope_id": envelope_id, "task": task, "branch": BRANCH,
                "base": BASE, "status": status, "added_at": TIME,
                "merge_commit": merge_commit}]})
        return envelope_id

    def append(self, event_type: str, envelope_id: str, **payload) -> dict:
        payload.setdefault("envelope", envelope_id)
        return tower_envelope.append_supervision_ledger(
            self.root, event_type, "supervision", payload)

    def reset_ledger(self) -> None:
        (self.root / "ledger" / "supervision.jsonl").write_text(
            "", encoding="utf-8")

    def merge_fact(self, envelope_id: str, task: str,
                   commit: str | None = None) -> None:
        """Seed the legal lifecycle up to ``MERGED`` (optionally with a MERGE)."""
        self.append("ENVELOPE_NEW", envelope_id, task=task,
                    head=self.implementation)
        self.append("QUEUE_ADD", envelope_id, task=task)
        self.append("MERGE_START", envelope_id, supervisor=SUPERVISOR)
        if commit is not None:
            self.append("MERGE", envelope_id, merge_commit=commit)

    def verified_without_merge(self, envelope_id: str, task: str) -> None:
        """Replay-safe verified history with no MERGE event at all."""
        self.append("ENVELOPE_NEW", envelope_id, task=task,
                    head=self.implementation)
        self.append("QUEUE_ADD", envelope_id, task=task)
        self.append("MERGE_START", envelope_id, supervisor=SUPERVISOR)
        self.append("MERGE_BLOCKED", envelope_id, reason="checks")
        self.append("POST_MERGE_VERIFIED", envelope_id, tests_count=1)

    # -- commands and accessors ------------------------------------------
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {**dict(os.environ), **GIT_IDENTITY}
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=180)

    def post_merge(self, envelope_id: str) -> subprocess.CompletedProcess:
        return self.cli("post-merge", "--envelope", envelope_id,
                        "--result", "PASS")

    def state_verify(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.cli("state-verify")
        return cp, json.loads(cp.stdout)

    def authorize(self) -> None:
        cp = self.cli("authority-set", "--supervisor", SUPERVISOR,
                      "--decision", "D-074", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def historical(self, envelope_id: str, commit: str, *extra: str):
        return self.cli("envelope-recover", "--historical", "--envelope",
                        envelope_id, "--merge-commit", commit,
                        "--reason", "PILOT-074 historical backfill", *extra)

    def envelope(self, envelope_id: str) -> dict:
        path = self.root / "supervision" / "envelopes" / f"{envelope_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def entry(self, envelope_id: str) -> dict:
        queue = json.loads((self.root / "supervision" / "MERGE_QUEUE.json")
                           .read_text(encoding="utf-8"))
        return next(item for item in queue["entries"]
                    if item["envelope_id"] == envelope_id)

    def events(self, event_type: str | None = None) -> list[dict]:
        path = self.root / "ledger" / "supervision.jsonl"
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row for row in rows
                if event_type is None or row.get("type") == event_type]

    def snapshot(self, envelope_id: str) -> tuple[bytes, bytes, bytes]:
        return (
            (self.root / "supervision" / "envelopes" / f"{envelope_id}.json")
            .read_bytes(),
            (self.root / "supervision" / "MERGE_QUEUE.json").read_bytes(),
            (self.root / "ledger" / "supervision.jsonl").read_bytes())

    def assert_refused(self, cp: subprocess.CompletedProcess,
                       envelope_id: str, before, *phrases: str) -> None:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        text = json.dumps(json.loads(cp.stdout), ensure_ascii=False)
        for phrase in phrases:
            self.assertIn(phrase, text)
        self.assertEqual(self.snapshot(envelope_id), before)
        verified = [event for event in self.events("POST_MERGE_VERIFIED")
                    if event["payload"].get("envelope") == envelope_id]
        was = [line for line in before[2].decode("utf-8").splitlines()
               if line.strip()
               and json.loads(line).get("type") == "POST_MERGE_VERIFIED"
               and json.loads(line)["payload"].get("envelope") == envelope_id]
        self.assertEqual(len(verified), len(was),
                         "a refusal must never append VERIFIED")

    def drift_kinds(self, payload: dict) -> list[str]:
        return sorted(item["kind"] for item in payload["drift"])


class NewCardPostMergeCase(_MergeFactKit):
    """PILOT-074: a 074+ envelope may only be verified from MERGED + fact."""

    # -- 1. CORRECTION_REQUIRED is refused, zero writes -------------------
    def test_new_card_correction_required_is_refused(self) -> None:
        envelope_id = self.write_envelope("074", "CORRECTION_REQUIRED",
                                          self.merge_commit)
        self.merge_fact(envelope_id, "PILOT-074", self.merge_commit)
        before = self.snapshot(envelope_id)

        cp = self.post_merge(envelope_id)

        self.assert_refused(cp, envelope_id, before, "only MERGED")
        self.assertEqual(self.envelope(envelope_id)["status"],
                         "CORRECTION_REQUIRED")

    # -- 2. MERGED with no MERGE event is refused ------------------------
    def test_merged_without_merge_event_is_refused(self) -> None:
        envelope_id = self.write_envelope("074", "MERGED", self.merge_commit)
        self.append("ENVELOPE_NEW", envelope_id, task="PILOT-074",
                    head=self.implementation)
        before = self.snapshot(envelope_id)

        cp = self.post_merge(envelope_id)

        self.assert_refused(cp, envelope_id, before, "no MERGE")

    # -- 3. either half empty, or two different commits, is refused ------
    def refuse_halves(self, envelope_commit, ledger_commit) -> None:
        self.reset_ledger()
        envelope_id = self.write_envelope("074", "MERGED", envelope_commit)
        self.merge_fact(envelope_id, "PILOT-074")
        self.append("MERGE", envelope_id, merge_commit=ledger_commit)
        before = self.snapshot(envelope_id)
        cp = self.post_merge(envelope_id)
        self.assert_refused(cp, envelope_id, before,
                            "same non-empty merge_commit")

    def test_ledger_side_empty_merge_commit_is_refused(self) -> None:
        self.refuse_halves(self.merge_commit, "")

    def test_envelope_side_empty_merge_commit_is_refused(self) -> None:
        self.refuse_halves(None, self.merge_commit)

    def test_two_different_merge_commits_are_refused(self) -> None:
        self.refuse_halves(self.merge_commit, self.implementation)

    def test_both_sides_empty_merge_commit_are_refused(self) -> None:
        self.refuse_halves(None, "")

    # -- 4. a merge commit with the wrong second parent is refused -------
    def test_merge_commit_with_wrong_second_parent_is_refused(self) -> None:
        other = self.other_merge()
        envelope_id = self.write_envelope("074", "MERGED", other)
        self.merge_fact(envelope_id, "PILOT-074", other)
        before = self.snapshot(envelope_id)

        cp = self.post_merge(envelope_id)

        self.assert_refused(cp, envelope_id, before, "second parent")

    # -- 5. a single-parent commit is refused as "no second parent" ------
    def test_merge_commit_without_second_parent_is_refused(self) -> None:
        envelope_id = self.write_envelope("074", "MERGED", self.implementation)
        self.merge_fact(envelope_id, "PILOT-074", self.implementation)
        before = self.snapshot(envelope_id)

        cp = self.post_merge(envelope_id)

        self.assert_refused(cp, envelope_id, before, "no second parent")

    # -- 6. the landed merge passes and writes VERIFIED ------------------
    def test_landed_merge_is_verified(self) -> None:
        envelope_id = self.write_envelope("074", "MERGED", self.merge_commit)
        self.merge_fact(envelope_id, "PILOT-074", self.merge_commit)
        write_json(self.root / "merge-envelopes" / f"{envelope_id}.json",
                   {"schema": "tower/merge-envelope@1",
                    "envelope_id": envelope_id})
        self.commit("state and base-side envelope")

        cp = self.post_merge(envelope_id)

        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope(envelope_id)["status"],
                         "POST_MERGE_VERIFIED")
        self.assertEqual(self.entry(envelope_id)["status"],
                         "POST_MERGE_VERIFIED")
        verified = self.events("POST_MERGE_VERIFIED")
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["payload"]["envelope"], envelope_id)
        _, payload = self.state_verify()
        self.assertEqual(payload["drift"], [])


class VerifiedWithoutMergeDriftCase(_MergeFactKit):
    """PILOT-074: state-verify reports and the historical backfill clears it."""

    # -- 1. drift before, zero after the backfill ------------------------
    def test_verified_without_merge_drifts_then_backfill_clears(self) -> None:
        envelope_id = self.write_envelope("066", "POST_MERGE_VERIFIED", None)
        self.verified_without_merge(envelope_id, "PILOT-066")

        cp, payload = self.state_verify()

        self.assertEqual(cp.returncode, 2, msg=cp.stdout)
        self.assertIn("verified_without_merge", self.drift_kinds(payload))
        self.assertEqual([item["target"] for item in payload["drift"]
                          if item["kind"] == "verified_without_merge"],
                         [envelope_id])

        self.authorize()
        backfill = self.historical(envelope_id, self.merge_commit)

        self.assertEqual(backfill.returncode, 0,
                         msg=backfill.stdout + backfill.stderr)
        out = json.loads(backfill.stdout)
        self.assertEqual(out["status"], "POST_MERGE_VERIFIED")
        self.assertEqual(out["merge_commit"], self.merge_commit)
        self.assertIs(out["historical"], True)
        envelope = self.envelope(envelope_id)
        self.assertEqual(envelope["status"], "POST_MERGE_VERIFIED")
        self.assertEqual(envelope["merge_commit"], self.merge_commit)
        self.assertNotIn("admin", envelope)
        self.assertEqual(len(self.events("POST_MERGE_VERIFIED")), 1)
        historical = self.events("MERGE_HISTORICAL")
        self.assertEqual(len(historical), 1)
        self.assertIs(historical[0]["payload"]["historical"], True)
        self.assertIs(historical[0]["payload"]["recovered"], True)
        self.assertEqual(historical[0]["payload"]["by"], SUPERVISOR)
        _, payload = self.state_verify()
        self.assertEqual(payload["drift"], [])

    # -- 5. empty or mismatched halves are drift, never verified ---------
    def drift_halves(self, envelope_commit, ledger_commit) -> None:
        self.reset_ledger()
        envelope_id = self.write_envelope(
            "074", "POST_MERGE_VERIFIED", envelope_commit)
        for event, extra in (
                ("ENVELOPE_NEW", {"task": "PILOT-074",
                                  "head": self.implementation}),
                ("QUEUE_ADD", {"task": "PILOT-074"}),
                ("MERGE_START", {"supervisor": SUPERVISOR}),
                ("MERGE", {"merge_commit": ledger_commit}),
                ("POST_MERGE_VERIFIED", {"tests_count": 1})):
            self.append(event, envelope_id, **extra)
        before = self.snapshot(envelope_id)
        cp, payload = self.state_verify()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout)
        rows = [item for item in payload["drift"]
                if item["kind"] == "verified_without_merge"]
        self.assertEqual([item["target"] for item in rows], [envelope_id])
        self.assertIn("ledger=", rows[0]["actual"])
        self.assertIn("envelope=", rows[0]["actual"])
        self.assertEqual(self.snapshot(envelope_id), before)

    def test_ledger_side_empty_merge_commit_is_drift(self) -> None:
        self.drift_halves(self.merge_commit, "")

    def test_envelope_side_empty_merge_commit_is_drift(self) -> None:
        self.drift_halves(None, self.merge_commit)

    def test_two_different_merge_commits_are_drift(self) -> None:
        self.drift_halves(self.merge_commit, self.implementation)

    def test_both_sides_empty_merge_commit_are_drift(self) -> None:
        self.drift_halves(None, "")

    # -- 2. a 074+ envelope can never use the historical path ------------
    def test_historical_backfill_rejects_074_plus(self) -> None:
        envelope_id = self.write_envelope("074", "POST_MERGE_VERIFIED", None)
        self.authorize()
        before = self.snapshot(envelope_id)

        cp = self.historical(envelope_id, self.merge_commit)

        self.assert_refused(cp, envelope_id, before, "not pre-074")

    # -- 3. the backfill refuses a wrong second parent -------------------
    def test_historical_backfill_rejects_wrong_second_parent(self) -> None:
        other = self.other_merge()
        envelope_id = self.write_envelope("067", "POST_MERGE_VERIFIED", None)
        self.verified_without_merge(envelope_id, "PILOT-067")
        self.authorize()
        before = self.snapshot(envelope_id)

        cp = self.historical(envelope_id, other)

        self.assert_refused(cp, envelope_id, before, "second parent")

    # -- 4. the backfill refuses a commit not on origin/main -------------
    def test_historical_backfill_rejects_commit_not_on_origin(self) -> None:
        envelope_id = self.write_envelope("068", "POST_MERGE_VERIFIED", None)
        self.verified_without_merge(envelope_id, "PILOT-068")
        local_only = self.commit("local only commit")
        self.authorize()
        before = self.snapshot(envelope_id)

        cp = self.historical(envelope_id, local_only)

        self.assert_refused(cp, envelope_id, before, "not on origin/main")


class ReplayCompatibilityCase(_MergeFactKit):
    """PILOT-074: 074+ transitions are strict, legacy replay is unchanged."""

    def replay(self) -> list[dict]:
        transitions: list[dict] = []
        states = towerctl.replay_envelope_statuses(self.root, transitions)
        self.assertIn("POST_MERGE_VERIFIED", states.values())
        return transitions

    def test_legacy_correction_to_verified_still_replays(self) -> None:
        envelope_id = self.write_envelope("065", "POST_MERGE_VERIFIED", "abc",
                                          base_side=False)
        self.append("ENVELOPE_NEW", envelope_id, task="PILOT-065")
        self.append("QUEUE_ADD", envelope_id, task="PILOT-065")
        self.append("MERGE_START", envelope_id, supervisor=SUPERVISOR)
        self.append("MERGE", envelope_id, merge_commit="abc")
        self.append("POST_MERGE_FAILED", envelope_id, result="FAIL")
        self.append("POST_MERGE_VERIFIED", envelope_id, tests_count=1)

        self.assertEqual(self.replay(), [])

    def test_074_correction_to_verified_is_an_illegal_transition(self) -> None:
        envelope_id = self.write_envelope("074", "POST_MERGE_VERIFIED", "abc",
                                          base_side=False)
        self.append("ENVELOPE_NEW", envelope_id, task="PILOT-074")
        self.append("QUEUE_ADD", envelope_id, task="PILOT-074")
        self.append("MERGE_START", envelope_id, supervisor=SUPERVISOR)
        self.append("MERGE", envelope_id, merge_commit="abc")
        self.append("POST_MERGE_FAILED", envelope_id, result="FAIL")
        self.append("POST_MERGE_VERIFIED", envelope_id, tests_count=1)

        illegal = [row for row in self.replay()
                   if row["kind"] == "illegal_transition"]
        self.assertEqual(len(illegal), 1, illegal)
        self.assertEqual(illegal[0]["event"], "POST_MERGE_VERIFIED")
        self.assertEqual(illegal[0]["expected"], ["MERGED"])
        self.assertEqual(illegal[0]["actual"], "CORRECTION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
