"""PILOT-067: the base-sync policy of ``merge --mode pr``.

065/066 hit "head branch not up to date" after the base advanced and kept the
review head continuous by merging with ``gh pr merge --admin`` -- a bypass with
no audit trail and no distinction between "the base only moved state" and "the
base changed code".  The merge now classifies the base-only paths before it
touches ``gh``:

* base did not advance -> the ordinary merge, never ``--admin``;
* base advanced with state-only paths and ``--allow-state-ahead`` -> an audited
  ``--admin`` merge whose envelope, merge-ledger entry and ``MERGE`` payload
  carry ``base_sync=state-only`` / ``base_ahead_paths`` / ``admin=true``;
* base advanced with state-only paths and no flag -> exit 2, names the flag;
* base advanced with any code/docs path -> exit 2 even with the flag, names the
  rebase and the re-review, and never allows ``--admin``;
* the review head stays bound to the envelope implementation head throughout.

PILOT-068 adds the base-side ``merge-envelopes/`` directory to that whitelist:
the envelope is committed to the base branch before the PR exists, so a base
that only gained ``tower-dsh/merge-envelopes/ENV-*.json`` plus tower state is
still the audited state-only case, while ``tools/``, ``arch/``,
``EVENT_CATALOG.json``, ``pilot/`` and root docs stay code/docs.

PILOT-069 takes the base-only diff from the fork point: ``merge-base HEAD
origin/main`` .. ``origin/main``.  A branch that carries its own implementation
(``tools/tower_cli.py``) is not "base-only" code, so its own merge can pass
``--allow-state-ahead`` and be audited as ``--admin``; a base that really adds
``tools/`` still exits 2.

The fixture is the PILOT-058 kit (a throw-away repository, a bare origin and an
offline ``gh`` stub injected through ``TOWERCTL_GH``), so no network, token or
real GitHub repository is involved.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest tools.tests.test_base_sync -v
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(TOOLS_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_review_gate as review_gate  # noqa: E402  (path setup must run first)
import tower_cli  # noqa: E402
import tower_envelope  # noqa: E402
import tower_merge  # noqa: E402

ENVELOPE = review_gate.ENVELOPE
TASK = review_gate.TASK
BASE = review_gate.BASE
BRANCH = review_gate.BRANCH
STATE_PATH = "tower-dsh/ledger/BASE-SYNC-STATE.json"
CODE_PATH = "tower-dsh/tools/base_sync_probe.py"
TOOLS_PATH = "tower-dsh/tools/tower_cli.py"
NEW_BASE_CODE_PATH = "tower-dsh/tools/x.py"
ENVELOPE_PATH = "tower-dsh/merge-envelopes/ENV-PILOT-068.json"
ROOT_ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-068.json"
REVIEW_CHECK = review_gate.REVIEW_CHECK
ok = review_gate.ok
read_json = review_gate.read_json
run_git = review_gate.run_git
write_json = review_gate.write_json


def merge_event_types(root: Path) -> list[str]:
    """Every supervision-ledger event type, oldest first."""
    path = root / "ledger" / "supervision.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["type"] for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class BaseSyncKitCase(review_gate.ReviewGateKitCase):
    """The 058/061 kit plus a bare origin whose ``main`` can move ahead."""

    def setUp(self) -> None:
        super().setUp()
        ok(run_git(self.kit, "push", "origin", "main"))

    # -- fixture ---------------------------------------------------------
    def advance_base(self, path: str, text: str = "base advance\n") -> str:
        """Publish one base-only commit as ``origin/main``, then rewind local."""
        return self.advance_base_paths([path], text)

    def advance_base_paths(self, paths: list[str],
                           text: str = "base advance\n") -> str:
        """Publish one base-only commit touching ``paths``, then rewind local.

        The commit is built on a throw-away branch, pushed straight to the bare
        origin's ``main`` and the local checkout returned to the old base, which
        is exactly the "base moved after the branch was cut" shape.
        """
        ok(run_git(self.kit, "checkout", "-b", "base-ahead"))
        for path in paths:
            target = self.kit / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        ok(run_git(self.kit, "add", "--", *paths))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false",
                   "commit", "-m", f"base advance: {', '.join(paths)}"))
        sha = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        ok(run_git(self.kit, "push", "origin", "base-ahead:main"))
        ok(run_git(self.kit, "checkout", BASE))
        return sha

    def rebuild_branch_with_own_code(self, path: str = TOOLS_PATH) -> None:
        """Rebuild ``BRANCH`` so its implementation itself carries ``path``.

        This is the PILOT-069 shape: the task branch owns its code
        (``tools/tower_cli.py`` + the tests), while the base only gains the
        base-side envelope and state after the branch was cut.
        """
        ok(run_git(self.kit, "checkout", "-B", BRANCH, BASE))
        (self.kit / "feature.txt").write_text("implementation\n", encoding="utf-8")
        target = self.kit / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# branch implementation\n", encoding="utf-8")
        ok(run_git(self.kit, "add", "--", "feature.txt", path))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m",
                   "implementation with branch code"))
        self.implementation_head = run_git(
            self.kit, "rev-parse", "HEAD").stdout.strip()
        (self.kit / "merge-envelopes").mkdir(exist_ok=True)
        write_json(self.kit / review_gate.ENVELOPE_PATH, {"envelope_id": ENVELOPE})
        ok(run_git(self.kit, "add", "--", review_gate.ENVELOPE_PATH))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit", "-m",
                   "envelope"))
        self.envelope_head = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        ok(run_git(self.kit, "checkout", BASE))

    # -- commands and state ----------------------------------------------
    def gh_env(self) -> dict:
        return {"TOWERCTL_GH": f"{sys.executable} {self.gh}",
                "RG_GH_LOG": str(self.gh_log),
                "RG_ORIGIN": str(self.origin).replace("\\", "/"),
                "RG_BRANCH_SHA": self.envelope_head}

    def run_merge(self, *extra: str) -> subprocess.CompletedProcess:
        return self.cli("merge", "--envelope", ENVELOPE, "--role", "supervisor",
                        "--supervisor", "sup-067", "--mode", "pr", *extra,
                        env_extra=self.gh_env())

    def merge_argv(self) -> list[str]:
        calls = [json.loads(line) for line in
                 self.gh_log.read_text(encoding="utf-8").splitlines()
                 if line.strip()] if self.gh_log.exists() else []
        return next(call for call in calls if call[:2] == ["pr", "merge"])

    def envelope_state(self) -> dict:
        return read_json(self.envelope_path())

    def review_head(self) -> str:
        return read_json(self.review_path())["head"]

    def merge_ledger_entry(self) -> dict:
        path = self.root / "supervision" / "registries" / "merge-ledger.json"
        return read_json(path)["entries"][-1]

    def merge_payload(self) -> dict:
        path = self.root / "ledger" / "supervision.jsonl"
        lines = [json.loads(line) for line in
                 path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return next(event["payload"] for event in reversed(lines)
                    if event.get("type") == "MERGE")

    def queue_status(self) -> str:
        queue = read_json(self.root / "supervision" / "MERGE_QUEUE.json")
        return next(entry["status"] for entry in queue["entries"]
                    if entry["envelope_id"] == ENVELOPE)

    def promote_reviewed_envelope(self) -> None:
        self.promote("--head", self.implementation_head, "--base", self.base_sha)

    # -- 1. unchanged base ------------------------------------------------
    def test_unchanged_base_merges_without_admin_audit(self) -> None:
        self.promote_reviewed_envelope()
        cp = self.run_merge()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        argv = self.merge_argv()
        self.assertNotIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.envelope_head)
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        for key in ("base_sync", "base_ahead_paths", "admin"):
            self.assertNotIn(key, envelope)
        self.assertNotIn("admin", self.merge_ledger_entry())
        self.assertNotIn("base_sync", self.merge_payload())

    # -- 2. state-only base + explicit flag -------------------------------
    def test_state_only_base_with_flag_is_audited_admin(self) -> None:
        self.promote_reviewed_envelope()
        ahead = self.advance_base(STATE_PATH)
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        argv = self.merge_argv()
        self.assertIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.envelope_head)
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_commit"], self.envelope_head)
        self.assertNotEqual(envelope["merge_commit"], ahead)
        self.assertEqual(envelope["base_sync"], "state-only")
        self.assertEqual(envelope["base_ahead_paths"], [STATE_PATH])
        self.assertIs(envelope["admin"], True)
        entry = self.merge_ledger_entry()
        self.assertEqual(entry["base_sync"], "state-only")
        self.assertEqual(entry["base_ahead_paths"], [STATE_PATH])
        self.assertIs(entry["admin"], True)
        payload = self.merge_payload()
        self.assertEqual(payload["base_sync"], "state-only")
        self.assertEqual(payload["base_ahead_paths"], [STATE_PATH])
        self.assertIs(payload["admin"], True)

    # -- 3. state-only base without the flag ------------------------------
    def test_state_only_base_without_flag_is_refused(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base(STATE_PATH)
        cp = self.run_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any("--allow-state-ahead" in error for error in errors),
                        errors)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        events = merge_event_types(self.root)
        self.assertFalse([event for event in events
                          if event.startswith("MERGE")], events)
        self.assertFalse(self.gh_log.exists())

    # -- 4. code/docs base change -----------------------------------------
    def test_code_base_change_is_refused_even_with_the_flag(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base(CODE_PATH, "code change\n")
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        blob = cp.stdout + cp.stderr
        self.assertIn("git rebase origin/main", blob)
        self.assertIn("review", blob)
        self.assertIn("--admin is never allowed", blob)
        errors = json.loads(cp.stdout)["errors"]
        self.assertIn(CODE_PATH, errors[0])
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        events = merge_event_types(self.root)
        self.assertFalse([event for event in events
                          if event.startswith("MERGE")], events)
        self.assertFalse(self.gh_log.exists())

    # -- 5. base-side envelope joins state-only (PILOT-068) ---------------
    def test_envelope_and_state_base_with_flag_is_audited_admin(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base_paths([STATE_PATH, ENVELOPE_PATH])
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        argv = self.merge_argv()
        self.assertIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.envelope_head)
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["base_sync"], "state-only")
        self.assertEqual(envelope["base_ahead_paths"], [STATE_PATH, ENVELOPE_PATH])
        self.assertIn(ENVELOPE_PATH, envelope["base_ahead_paths"])
        self.assertIs(envelope["admin"], True)
        entry = self.merge_ledger_entry()
        self.assertEqual(entry["base_sync"], "state-only")
        self.assertEqual(entry["base_ahead_paths"], [STATE_PATH, ENVELOPE_PATH])
        self.assertIs(entry["admin"], True)
        payload = self.merge_payload()
        self.assertEqual(payload["base_sync"], "state-only")
        self.assertEqual(payload["base_ahead_paths"], [STATE_PATH, ENVELOPE_PATH])
        self.assertIs(payload["admin"], True)

    # -- 6. envelope-only base without the flag (PILOT-068) ---------------
    def test_envelope_only_base_without_flag_is_refused(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base(ENVELOPE_PATH)
        cp = self.run_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any("--allow-state-ahead" in error for error in errors),
                        errors)
        self.assertTrue(any(ENVELOPE_PATH in error for error in errors), errors)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        self.assertFalse(self.gh_log.exists())

    # -- 7. tools/ stays code even with the flag (PILOT-068) --------------
    def test_tools_code_base_is_refused_even_with_the_flag(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base_paths([TOOLS_PATH, ENVELOPE_PATH])
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any(TOOLS_PATH in error for error in errors), errors)
        self.assertFalse(any(ENVELOPE_PATH in error for error in errors), errors)
        blob = cp.stdout + cp.stderr
        self.assertIn("git rebase origin/main", blob)
        self.assertIn("--admin is never allowed", blob)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        self.assertFalse(self.gh_log.exists())

    # -- 8. the review stays bound to the implementation ------------------
    def test_review_head_stays_bound_to_the_envelope_implementation(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base(STATE_PATH)
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        envelope = self.envelope_state()
        self.assertEqual(envelope["implementation_head_sha"],
                         self.implementation_head)
        self.assertEqual(self.review_head(), self.implementation_head)
        self.assertEqual(envelope["implementation_head_sha"], self.review_head())
        # A review written for the old implementation head is still reported as
        # stale: the audited --admin path may not re-bind review to new code.
        moved = dict(envelope)
        moved["implementation_head_sha"] = "f" * 40
        problems = tower_envelope.review_problems(self.root, moved, TASK)
        self.assertTrue(any(problem.startswith("stale review: head")
                            for problem in problems), problems)

    # -- 9. the branch's own code is never base-only (PILOT-069) ----------
    def test_branch_code_with_state_base_is_audited_admin(self) -> None:
        self.rebuild_branch_with_own_code()
        self.promote_reviewed_envelope()
        self.advance_base_paths([STATE_PATH, ENVELOPE_PATH])
        # The branch checkout carries the branch's own tools/ code, but the
        # base-only set is the fork point .. origin/main, so that code is not
        # base-only.  The pre-069 ``HEAD..origin/main`` spelling did include it.
        ok(run_git(self.kit, "checkout", BRANCH))
        ahead = tower_cli.base_ahead_paths(self.kit, BASE, "origin")
        self.assertEqual(ahead, [STATE_PATH, ENVELOPE_PATH])
        self.assertNotIn(TOOLS_PATH, ahead)
        tip_diff = [line.strip() for line in run_git(
            self.kit, "diff", "--name-only",
            f"HEAD..origin/{BASE}").stdout.splitlines() if line.strip()]
        self.assertIn(TOOLS_PATH, tip_diff)
        ok(run_git(self.kit, "checkout", BASE))
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        argv = self.merge_argv()
        self.assertIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.envelope_head)
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["base_sync"], "state-only")
        self.assertEqual(envelope["base_ahead_paths"],
                         [STATE_PATH, ENVELOPE_PATH])
        self.assertNotIn(TOOLS_PATH, envelope["base_ahead_paths"])
        self.assertIs(envelope["admin"], True)
        entry = self.merge_ledger_entry()
        self.assertEqual(entry["base_ahead_paths"], [STATE_PATH, ENVELOPE_PATH])
        self.assertNotIn(TOOLS_PATH, entry["base_ahead_paths"])
        self.assertIs(entry["admin"], True)
        payload = self.merge_payload()
        self.assertEqual(payload["base_ahead_paths"],
                         [STATE_PATH, ENVELOPE_PATH])
        self.assertNotIn(TOOLS_PATH, payload["base_ahead_paths"])
        self.assertIs(payload["admin"], True)

    # -- 10. branch code + state base without the flag ---------------------
    def test_branch_code_with_state_base_without_flag_is_refused(self) -> None:
        self.rebuild_branch_with_own_code()
        self.promote_reviewed_envelope()
        self.advance_base_paths([STATE_PATH, ENVELOPE_PATH])
        cp = self.run_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any("--allow-state-ahead" in error for error in errors),
                        errors)
        self.assertFalse(any(TOOLS_PATH in error for error in errors), errors)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        self.assertFalse(self.gh_log.exists())

    # -- 11. a base that really adds tools/ is code (PILOT-069) ------------
    def test_base_added_tools_file_is_refused_even_with_the_flag(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base_paths([NEW_BASE_CODE_PATH, STATE_PATH])
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any(NEW_BASE_CODE_PATH in error for error in errors),
                        errors)
        self.assertFalse(any(STATE_PATH in error for error in errors), errors)
        self.assertIn("git rebase origin/main", cp.stdout + cp.stderr)
        self.assertIn("--admin is never allowed", cp.stdout + cp.stderr)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertFalse(self.gh_log.exists())

    # -- 12. an unchanged base is never base-ahead -------------------------
    def test_unchanged_base_is_not_base_ahead(self) -> None:
        self.assertEqual(
            tower_cli.base_ahead_paths(self.kit, BASE, "origin"), [])
        # PILOT-069's own shape: the local base carries an unpublished commit,
        # so HEAD is ahead of origin/main while the base itself did not advance.
        (self.kit / "local-only.txt").write_text("local\n", encoding="utf-8")
        self.commit("local base commit")
        self.assertEqual(
            tower_cli.base_ahead_paths(self.kit, BASE, "origin"), [])


class BasePathClassificationCase(unittest.TestCase):
    """The whitelist is exact; anything unrecognised falls to code/docs."""

    def test_state_paths_and_code_paths_split_by_prefix(self) -> None:
        state_paths = ["tower-dsh/ledger/primary.jsonl",
                       "tower-dsh/primary/CURRENT_STATE.json",
                       "tower-dsh/supervision/CURRENT_STATE.json",
                       "tower-dsh/tasks/PILOT-067/TASK.md",
                       "tower-dsh/state/PROFILE-TOWER-DSH.md",
                       "tower-dsh/merge-envelopes/ENV-PILOT-068.json"]
        code_paths = ["tower-dsh/tools/tower_merge.py",
                      "tower-dsh/arch/ADR-0009-delivery-trust.md",
                      "tower-dsh/EVENT_CATALOG.json",
                      "tower-dsh/pilot/PILOT-067.spec.json",
                      "tower-dsh/README.md",
                      "control-tower/README.md",
                      "merge-envelopes/ENV-PILOT-068.json"]
        state, code = tower_cli.classify_base_paths(state_paths + code_paths,
                                                    "tower-dsh/")
        self.assertEqual(state, state_paths)
        self.assertEqual(code, code_paths)

    def test_whitelist_wins_only_inside_the_tower_prefix(self) -> None:
        # A ``ledger/`` directory outside the tower root is not tower state.
        state, code = tower_cli.classify_base_paths(
            ["ledger/primary.jsonl", "primary/CURRENT_STATE.json"], "")
        self.assertEqual(state, ["ledger/primary.jsonl",
                                 "primary/CURRENT_STATE.json"])
        self.assertEqual(code, [])
        state, code = tower_cli.classify_base_paths(
            ["control-tower/ledger/primary.jsonl"], "tower-dsh/")
        self.assertEqual(state, [])
        self.assertEqual(code, ["control-tower/ledger/primary.jsonl"])
        # ... and neither is a ``merge-envelopes/`` directory outside the tower.
        state, code = tower_cli.classify_base_paths(
            [ROOT_ENVELOPE_PATH, "control-tower/merge-envelopes/ENV.json"],
            "tower-dsh/")
        self.assertEqual(state, [])
        self.assertEqual(code, [ROOT_ENVELOPE_PATH,
                                "control-tower/merge-envelopes/ENV.json"])


class PrMergeArgvCase(unittest.TestCase):
    """``--admin`` is emitted only when the guard recorded an audit."""

    def test_admin_requires_the_state_only_audit(self) -> None:
        args = argparse.Namespace()
        self.assertNotIn("--admin", tower_merge.pr_merge_argv(7, "a" * 40, args))
        args.base_sync_audit = {"base_sync": "state-only", "admin": True}
        argv = tower_merge.pr_merge_argv(7, "a" * 40, args)
        self.assertIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1], "a" * 40)


if __name__ == "__main__":
    unittest.main()
