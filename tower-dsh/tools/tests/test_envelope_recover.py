"""PILOT-073: ``envelope-recover`` -- adopt an already-landed out-of-band merge.

071 hit the gap this file pins: the code was merged by a direct owner
``gh --admin``, so ``origin/main`` contains the implementation, but the envelope
stayed ``WAITING`` with no ``MERGE`` event.  Nothing may be merged, re-reviewed
or fabricated, so the only honest exit is an audited recovery::

    towerctl envelope-recover --envelope <ENV> --merge-commit <sha> \
        --reason <text> [--by <pinned-supervisor>]

The command is supervisor-only (the pinned merge authority, never the primary)
and fail-closed: the named commit must resolve, sit on ``origin/<base>`` and
contain the envelope's implementation head.  Success appends ``MERGE`` with
``merge_commit`` / ``recovered=true`` / ``by`` / ``reason``, moves the envelope
and queue to ``MERGED`` and never writes ``POST_MERGE_VERIFIED`` (that stays the
post-merge gate's verdict).  Every refusal is exit 2 with zero writes, and a
recovery that already happened is refused the same way.

The fixture is a throw-away git repository plus a bare ``origin`` under
``%TEMP%``, so no network or real repository is involved.  ``PILOT-075`` adds
the order (recovered ``MERGE_START`` then ``MERGE`` from ``CORRECTION_REQUIRED``),
074's no-duplicate repair, and pins that an ordinary correction-to-merge stays
illegal; the 074-shaped fixture replays with zero drift once ``MERGED``.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_envelope_recover -v
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

TCLI = TOOLS_DIR / "towerctl.py"
TASK = "PILOT-071"
ENVELOPE = "ENV-PILOT-071"
SUPERVISOR = "sup-073"
PRIMARY = "ctl-073"
BRANCH = "feature/recover"
BASE = "main"
LEDGER = ("ledger", "supervision.jsonl")
QUEUE = ("supervision", "MERGE_QUEUE.json")
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**dict(os.environ), **GIT_IDENTITY}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def ok(cp: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if cp.returncode != 0:
        raise AssertionError(f"git exit {cp.returncode}: {cp.stdout}{cp.stderr}")
    return cp


class _RecoverKit(unittest.TestCase):
    """A tower whose ``main`` already contains an out-of-band merge."""

    REMOTE_ONLY = False
    ENVELOPE_ID = ENVELOPE
    TASK_ID = TASK

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-recover-", ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.kit = self.tmp / "kit"
        self.root = self.kit / "tower-dsh"
        self.origin = self.tmp / "origin.git"
        self.gh_log = self.tmp / "gh-argv.jsonl"
        self.envelope_id = self.ENVELOPE_ID
        self.task = self.TASK_ID
        for directory in ("primary", "supervision/envelopes", "ledger"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("primary.jsonl", "supervision.jsonl"):
            (self.root / "ledger" / name).write_text("", encoding="utf-8")
        self.write_state()
        self.build_repo()
        self.write_envelope()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture ---------------------------------------------------------
    def write_state(self) -> None:
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "tower_id": "tower-dsh",
            "role": "primary", "phase": "TEST", "owner": {"name": "mac"},
            "primary": {"id": PRIMARY}})
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1", "tower_id": "tower-dsh",
            "role": "supervision", "phase": "TEST",
            "supervisor": {"id": SUPERVISOR}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})

    def commit(self, message: str) -> str:
        ok(run_git(self.kit, "add", "-A"))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m",
                   message))
        return run_git(self.kit, "rev-parse", "HEAD").stdout.strip()

    def build_repo(self) -> None:
        """``main`` gains the implementation through a real no-ff merge.

        ``REMOTE_ONLY`` builds that merge in a throw-away clone instead, so the
        merge commit exists only on the origin and the local object database
        has never seen it -- the shape the fetch-order bug refused.
        """
        self.kit.mkdir(parents=True, exist_ok=True)
        ok(run_git(self.kit, "init"))
        ok(run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main"))
        (self.kit / "README.md").write_text("base\n", encoding="utf-8")
        self.base_sha = self.commit("base")
        ok(run_git(self.kit, "checkout", "-b", BRANCH))
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        self.implementation_head = self.commit("implementation")
        ok(run_git(self.kit, "checkout", BASE))
        bare = subprocess.run(["git", "init", "--bare", str(self.origin)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(bare.returncode, 0, msg=bare.stderr)
        ok(run_git(self.kit, "remote", "add", "origin",
                   str(self.origin).replace("\\", "/")))
        if self.REMOTE_ONLY:
            ok(run_git(self.kit, "push", "origin", BASE, BRANCH))
            builder = self.tmp / "builder"
            ok(run_git(self.tmp, "clone", "--quiet", str(self.origin),
                       str(builder)))
            ok(run_git(builder, "checkout", "-b", BRANCH, f"origin/{BRANCH}"))
            ok(run_git(builder, "checkout", BASE))
            ok(run_git(builder, "-c", "commit.gpgsign=false", "merge", "--no-ff",
                       BRANCH, "-m", "merge feature"))
            self.merge_commit = run_git(builder, "rev-parse",
                                        "HEAD").stdout.strip()
            ok(run_git(builder, "push", "origin", BASE))
            self.assertNotEqual(
                run_git(self.kit, "cat-file", "-e",
                        self.merge_commit).returncode, 0,
                msg="the merge commit must not exist locally")
            return
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "merge", "--no-ff",
                   BRANCH, "-m", "merge feature"))
        self.merge_commit = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(run_git(self.kit, "rev-parse",
                                 "HEAD^2").stdout.strip(),
                         self.implementation_head)
        ok(run_git(self.kit, "push", "origin", BASE))

    def write_envelope(self) -> None:
        tower_envelope.append_supervision_ledger(
            self.root, "ENVELOPE_NEW", "primary",
            {"envelope": self.envelope_id, "task": self.task,
             "head": self.implementation_head})
        tower_envelope.append_supervision_ledger(
            self.root, "QUEUE_ADD", "primary",
            {"envelope": self.envelope_id, "task": self.task})
        write_json(self.envelope_path(), {
            "schema": "tower/merge-envelope@1", "envelope_id": self.envelope_id,
            "task": self.task, "repository": "..", "branch": BRANCH, "base": BASE,
            "envelope_path": f"merge-envelopes/{self.envelope_id}.json",
            "implementation_head_sha": self.implementation_head,
            "tests_baseline": 770, "tower_tests_baseline": 900,
            "status": "WAITING"})
        write_json(self.queue_path(), {
            "schema": "tower/merge-queue@1", "entries": [{
                "envelope_id": self.envelope_id, "task": self.task,
                "branch": BRANCH, "base": BASE, "status": "WAITING",
                "added_at": "2026-11-04T00:00:00+08:00"}]})

    def authorize(self) -> None:
        """Pin the merge authority through the real ``authority-set``."""
        cp = self.cli("authority-set", "--supervisor", SUPERVISOR,
                      "--decision", "D-073", "--by", "mac")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    # -- commands and accessors ------------------------------------------
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {**dict(os.environ), **GIT_IDENTITY}
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", env=env,
            timeout=120)

    def recover(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("envelope-recover", "--envelope", self.envelope_id,
                        "--merge-commit", self.merge_commit,
                        "--reason", "071 direct owner admin", *extra)

    def envelope_path(self) -> Path:
        return self.root / "supervision" / "envelopes" / f"{self.envelope_id}.json"

    def queue_path(self) -> Path:
        return self.root.joinpath(*QUEUE)

    def ledger_path(self) -> Path:
        return self.root.joinpath(*LEDGER)

    def state_verify(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = self.cli("state-verify")
        return cp, json.loads(cp.stdout)

    def envelope(self) -> dict:
        return json.loads(self.envelope_path().read_text(encoding="utf-8"))

    def entry(self) -> dict:
        queue = json.loads(self.queue_path().read_text(encoding="utf-8"))
        return next(item for item in queue["entries"]
                    if item["envelope_id"] == self.envelope_id)

    def save_entry(self, **changes) -> None:
        """Update this envelope's queue entry in place (fixture shaping)."""
        queue = json.loads(self.queue_path().read_text(encoding="utf-8"))
        entry = next(item for item in queue["entries"]
                     if item["envelope_id"] == self.envelope_id)
        entry.update(changes)
        write_json(self.queue_path(), queue)

    def events(self, event_type: str | None = None) -> list[dict]:
        rows = [json.loads(line) for line in
                self.ledger_path().read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return [row for row in rows
                if event_type is None or row.get("type") == event_type]

    def snapshot(self) -> tuple[bytes, bytes, bytes]:
        return (self.envelope_path().read_bytes(), self.queue_path().read_bytes(),
                self.ledger_path().read_bytes())

    def assert_refused(self, cp: subprocess.CompletedProcess,
                       before: tuple[bytes, bytes, bytes]) -> None:
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertFalse(json.loads(cp.stdout)["ok"])
        self.assertEqual(self.snapshot(), before)

    # -- crash injection --------------------------------------------------
    def write_half_state(self, merge_start: bool) -> None:
        """Inject the shape a crash leaves between the files and the ledger.

        ``recover`` writes the queue, then the envelope, then ``MERGE_START``,
        then ``MERGE``.  A crash after step 1/2 leaves both files ``MERGED``
        with an empty ledger; a crash after step 3 leaves the recovered
        ``MERGE_START`` only.  Both must be completable by a retry.
        """
        if merge_start:
            tower_envelope.append_supervision_ledger(
                self.root, "MERGE_START", "supervision",
                {"envelope": self.envelope_id, "supervisor": SUPERVISOR,
                 "recovered": True})
        env = self.envelope()
        env.update({"status": "MERGED", "merge_commit": self.merge_commit})
        write_json(self.envelope_path(), env)
        self.save_entry(status="MERGED", merge_commit=self.merge_commit)

    def stale_local_ref(self, sha: str) -> None:
        """Move the local ``origin/main`` ref without touching the origin."""
        ok(run_git(self.kit, "update-ref", "refs/remotes/origin/main", sha))

    def rewind_origin(self, sha: str) -> None:
        ok(run_git(self.origin, "update-ref", "refs/heads/main", sha))

    # -- correction shaping (PILOT-075) -----------------------------------
    def append(self, event_type: str, **payload) -> None:
        tower_envelope.append_supervision_ledger(
            self.root, event_type, "supervision",
            {"envelope": self.envelope_id, **payload})

    def block_merge(self, reason: str = "checks") -> None:
        """The correction event a blocked merge writes (no merge happened)."""
        self.append("MERGE_BLOCKED", phase=reason, reason=reason)

    def set_status(self, status: str, merge_commit: str | None = None) -> None:
        """Write the envelope/queue pair a command would leave behind."""
        changes = {"status": status}
        if merge_commit is not None:
            changes["merge_commit"] = merge_commit
        env = self.envelope()
        env.update(changes)
        write_json(self.envelope_path(), env)
        self.save_entry(**changes)


class EnvelopeRecoverCase(_RecoverKit):
    """The recovery contract: identity, freshness, repair and refusals."""

    # -- 1. the 071 shape: landed merge, WAITING envelope -----------------
    def test_waiting_envelope_with_landed_merge_is_recovered(self) -> None:
        self.authorize()
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["status"], "MERGED")
        self.assertEqual(out["merge_commit"], self.merge_commit)
        self.assertIs(out["recovered"], True)
        self.assertIs(out["repaired"], False)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(self.envelope()["merge_commit"], self.merge_commit)
        self.assertEqual(self.envelope()["implementation_head_sha"],
                         self.implementation_head)
        self.assertIs(self.envelope()["recovered"], True)
        self.assertEqual(self.entry()["status"], "MERGED")
        self.assertEqual(self.entry()["merge_commit"], self.merge_commit)
        merges = self.events("MERGE")
        self.assertEqual(len(merges), 1)
        payload = merges[0]["payload"]
        self.assertEqual(payload["envelope"], self.envelope_id)
        self.assertEqual(payload["merge_commit"], self.merge_commit)
        self.assertIs(payload["recovered"], True)
        self.assertEqual(payload["by"], SUPERVISOR)
        self.assertEqual(payload["reason"], "071 direct owner admin")
        # The recovery is visible in the ledger, but never claims verification.
        starts = self.events("MERGE_START")
        self.assertEqual(len(starts), 1)
        self.assertIs(starts[0]["payload"]["recovered"], True)
        self.assertEqual(self.events("POST_MERGE_VERIFIED"), [])
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    def test_by_defaults_to_the_pinned_supervisor(self) -> None:
        self.authorize()
        cp = self.recover("--by", SUPERVISOR)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.events("MERGE")[0]["payload"]["by"], SUPERVISOR)

    # -- 2. the commit must really be on origin/<base> --------------------
    def test_unmerged_commit_is_refused_with_zero_writes(self) -> None:
        self.authorize()
        ok(run_git(self.kit, "checkout", "-b", "side", BASE))
        (self.kit / "side.txt").write_text("side\n", encoding="utf-8")
        # Stage only the side file: the tower state must stay untracked so the
        # checkout back to main cannot remove the envelope/queue fixture.
        ok(run_git(self.kit, "add", "--", "side.txt"))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m",
                   "side only"))
        side = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        ok(run_git(self.kit, "checkout", BASE))
        before = self.snapshot()
        cp = self.cli("envelope-recover", "--envelope", ENVELOPE,
                      "--merge-commit", side, "--reason", "not landed")
        self.assert_refused(cp, before)
        self.assertIn("is not on freshly fetched origin/main", cp.stdout)
        self.assertEqual(self.events("MERGE"), [])

    # -- 3. a commit on origin/main but not this envelope's merge ---------
    def test_wrong_commit_is_refused_with_zero_writes(self) -> None:
        self.authorize()
        before = self.snapshot()
        cp = self.cli("envelope-recover", "--envelope", ENVELOPE,
                      "--merge-commit", self.base_sha, "--reason", "wrong sha")
        self.assert_refused(cp, before)
        self.assertIn("does not contain implementation head", cp.stdout)

    # -- 4. only the pinned supervisor (never the primary) ----------------
    def test_non_supervisor_is_refused_with_zero_writes(self) -> None:
        self.authorize()
        before = self.snapshot()
        cp = self.recover("--by", "sup-rogue")
        self.assert_refused(cp, before)
        self.assertIn("only the pinned merge authority", cp.stdout)

    def test_primary_cannot_recover(self) -> None:
        self.authorize()
        before = self.snapshot()
        cp = self.recover("--by", PRIMARY)
        self.assert_refused(cp, before)
        self.assertIn("only the pinned merge authority", cp.stdout)

    # -- 5. no authority configured: fail closed ---------------------------
    def test_unconfigured_authority_is_refused_with_zero_writes(self) -> None:
        before = self.snapshot()
        cp = self.recover()
        self.assert_refused(cp, before)
        self.assertIn("envelope-recover requires a configured", cp.stdout)

    # -- 6. a second recovery is refused, not duplicated -------------------
    def test_repeat_recovery_is_refused_with_zero_writes(self) -> None:
        self.authorize()
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        before = self.snapshot()
        cp = self.recover()
        self.assert_refused(cp, before)
        self.assertIn("already records a MERGE", cp.stdout)
        self.assertEqual(len(self.events("MERGE")), 1)
        self.assertEqual(self.envelope()["status"], "MERGED")
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    # -- 7. half-write repair: files MERGED, ledger empty -----------------
    def test_half_written_files_without_ledger_are_repaired(self) -> None:
        self.authorize()
        self.write_half_state(merge_start=False)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(self.events("MERGE"), [])
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertIs(out["repaired"], True)
        self.assertEqual(len(self.events("MERGE_START")), 1)
        self.assertEqual(len(self.events("MERGE")), 1)
        self.assertEqual(self.events("MERGE")[0]["payload"]["merge_commit"],
                         self.merge_commit)
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    # -- 8. half-write repair: recovered MERGE_START, MERGE missing -------
    def test_half_written_merge_start_is_completed(self) -> None:
        self.authorize()
        self.write_half_state(merge_start=True)
        self.assertEqual(len(self.events("MERGE_START")), 1)
        self.assertEqual(self.events("MERGE"), [])
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        out = json.loads(cp.stdout)
        self.assertIs(out["repaired"], True)
        self.assertEqual(len(self.events("MERGE_START")), 1)  # not duplicated
        self.assertEqual(len(self.events("MERGE")), 1)
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    def test_half_written_other_commit_is_refused(self) -> None:
        self.authorize()
        self.write_half_state(merge_start=True)
        env = self.envelope()
        env["merge_commit"] = "f" * 40
        write_json(self.envelope_path(), env)
        before = self.snapshot()
        cp = self.recover()
        self.assert_refused(cp, before)
        self.assertIn("cannot rewrite a merge", cp.stdout)

    # -- 9. fetch, not the stale local remote-tracking ref ----------------
    def test_fetch_refreshes_a_stale_local_origin_ref(self) -> None:
        self.authorize()
        # The local ref has not seen the merge yet; a fetch must find it.
        self.stale_local_ref(self.base_sha)
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(len(self.events("MERGE")), 1)

    def test_origin_without_the_merge_is_refused_despite_local_ref(self) -> None:
        self.authorize()
        # The local remote-tracking ref still says merged, origin does not.
        self.rewind_origin(self.base_sha)
        before = self.snapshot()
        cp = self.recover()
        self.assert_refused(cp, before)
        self.assertIn("freshly fetched origin/main", cp.stdout)
        self.assertIn("stale remote-tracking ref", cp.stdout)


class RemoteOnlyRecoverCase(_RecoverKit):
    """The 071 shape literally: the merge commit exists only on the origin."""

    REMOTE_ONLY = True

    def test_remote_only_merge_commit_is_fetched_then_resolved(self) -> None:
        self.authorize()
        # The premise: the local object database has never seen the merge, so
        # resolving before the fetch would refuse a landed merge.
        self.assertNotEqual(
            run_git(self.kit, "cat-file", "-e", self.merge_commit).returncode, 0)
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(self.envelope()["status"], "MERGED")
        self.assertEqual(self.envelope()["merge_commit"], self.merge_commit)
        self.assertEqual(len(self.events("MERGE")), 1)
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    def test_remote_only_commit_absent_from_origin_still_refuses(self) -> None:
        self.authorize()
        # Rewind origin: the commit is neither local nor on the origin now.
        self.rewind_origin(self.base_sha)
        before = self.snapshot()
        cp = self.recover()
        self.assert_refused(cp, before)
        self.assertIn("is not a resolvable commit", cp.stdout)


class CorrectionRecoverCase(_RecoverKit):
    """PILOT-075: recovery out of ``CORRECTION_REQUIRED`` writes the order."""

    def test_correction_recovery_appends_merge_start_then_merge(self) -> None:
        self.authorize()
        self.block_merge()
        self.set_status("CORRECTION_REQUIRED")
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        tail = self.events()[-2:]
        self.assertEqual([event["type"] for event in tail],
                         ["MERGE_START", "MERGE"])
        start, merge = tail
        self.assertIs(start["payload"]["recovered"], True)
        self.assertIs(merge["payload"]["recovered"], True)
        self.assertEqual(merge["payload"]["merge_commit"], self.merge_commit)
        self.assertEqual((self.envelope()["status"], self.entry()["status"]),
                         ("MERGED", "MERGED"))
        self.assertEqual(self.events("POST_MERGE_VERIFIED"), [])
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(verify["drift"], [])

    def test_ordinary_correction_to_merge_stays_illegal(self) -> None:
        """No ``recovered`` flag: the 074 compatibility is not a blanket pass."""
        self.append("MERGE_START", supervisor=SUPERVISOR)
        self.block_merge()
        self.append("MERGE", merge_commit=self.merge_commit, by=SUPERVISOR)
        self.set_status("MERGED", self.merge_commit)
        cp, verify = self.state_verify()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertEqual(
            [row for row in verify["drift"]
             if row["kind"] == "illegal_transition"],
            [{"kind": "illegal_transition", "target": self.envelope_id,
              "event": "MERGE", "expected": ["MERGING"],
              "actual": "CORRECTION_REQUIRED"}])


class Recover074Case(_RecoverKit):
    """PILOT-075: 074's real shape -- one recovered MERGE, two failures."""

    ENVELOPE_ID = "ENV-PILOT-074"
    TASK_ID = "PILOT-074"

    def write_074_shape(self) -> None:
        """``MERGE_START``, ``MERGE_BLOCKED``, recovered ``MERGE``, 2 failures."""
        self.append("MERGE_START", supervisor=SUPERVISOR)
        self.block_merge()
        self.append("MERGE", merge_commit=self.merge_commit, recovered=True,
                    by=SUPERVISOR, reason="074 admin merge")
        self.append("POST_MERGE_FAILED", result="PASS")
        self.append("POST_MERGE_FAILED", result="PASS")
        self.set_status("CORRECTION_REQUIRED", self.merge_commit)

    def test_existing_recovered_merge_is_normalized_without_a_second_merge(self):
        self.authorize()
        self.write_074_shape()
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["status"], "MERGED")
        self.assertEqual(len(self.events("MERGE")), 1)       # never duplicated
        self.assertEqual(len(self.events("MERGE_START")), 1)
        self.assertEqual(self.events("POST_MERGE_VERIFIED"), [])
        self.assertEqual((self.envelope()["status"], self.envelope()["merge_commit"]),
                         ("MERGED", self.merge_commit))
        self.assertEqual((self.entry()["status"], self.entry()["merge_commit"]),
                         ("MERGED", self.merge_commit))

    def test_074_real_shape_recovers_to_zero_drift(self) -> None:
        self.authorize()
        self.write_074_shape()
        # Only the file halves disagree: the recovered MERGE is already legal.
        before, verify = self.state_verify()
        self.assertEqual(before.returncode, 2, msg=before.stdout + before.stderr)
        self.assertEqual(sorted(row["kind"] for row in verify["drift"]),
                         ["envelope_status", "queue_status"])
        cp = self.recover()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        after, verify = self.state_verify()
        self.assertEqual(after.returncode, 0, msg=after.stdout + after.stderr)
        self.assertEqual(verify["drift"], [])


if __name__ == "__main__":
    unittest.main()
