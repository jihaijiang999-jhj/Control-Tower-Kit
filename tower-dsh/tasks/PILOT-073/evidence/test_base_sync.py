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

PILOT-073 narrows "``pilot/`` stays code/docs": the two *bookkeeping* inputs of
a card -- ``pilot/<card>.spec.json`` (top level only) and
``command/campaigns/**`` -- are state.  They were the 071 base-ahead that forced
a direct ``gh --admin``; every other ``pilot/`` path (worktrees, evidence,
deeper spec copies) and ``tools/``/``arch/`` stay code/docs even with the flag.

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
SPEC_PATH = "tower-dsh/pilot/PILOT-073.spec.json"
CAMPAIGN_PATH = "tower-dsh/command/campaigns/C-2026-Q4-04.md"
ENVELOPE_PATH = "tower-dsh/merge-envelopes/ENV-PILOT-068.json"
ROOT_ENVELOPE_PATH = "merge-envelopes/ENV-PILOT-068.json"
# The base-side envelope sits under the tower prefix of the kit repository.
ENVELOPE_REPO_PATH = "tower-dsh/merge-envelopes/ENV-REVIEW-058.json"
BRANCH_CODE_PATH = "feature.txt"
REVIEW_CHECK = review_gate.REVIEW_CHECK
ok = review_gate.ok
read_json = review_gate.read_json
write_json = review_gate.write_json
run_git = review_gate.run_git


def merge_event_types(root: Path) -> list[str]:
    """Every supervision-ledger event type, oldest first."""
    path = root / "ledger" / "supervision.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["type"] for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _BaseSyncKit(review_gate.ReviewGateKitCase):
    """The 058/061 kit plus a bare origin whose ``main`` can move ahead.

    Only helpers live here; the concrete cases below inherit them so a new
    scenario never re-runs (or duplicates) the PILOT-067/068 tests.
    """

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

    def assert_state_ahead_refused(self, path: str) -> list[str]:
        """A state-only base-ahead without the flag: exit 2, nothing written."""
        self.promote_reviewed_envelope()
        self.advance_base(path)
        cp = self.run_merge()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any("--allow-state-ahead" in error for error in errors),
                        errors)
        self.assertTrue(any(path in error for error in errors), errors)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        self.assertFalse([event for event in merge_event_types(self.root)
                          if event.startswith("MERGE")])
        self.assertFalse(self.gh_log.exists())
        return errors


class BaseSyncKitCase(_BaseSyncKit):
    """PILOT-067/068 cases: branch-side envelope, base still behind."""

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
        self.assert_state_ahead_refused(STATE_PATH)

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

    # -- 8. spec + campaign base advance is state, not code (PILOT-073) ----
    def test_spec_and_campaign_base_with_flag_is_audited_admin(self) -> None:
        self.promote_reviewed_envelope()
        self.advance_base_paths([SPEC_PATH, CAMPAIGN_PATH])
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertIn("--admin", self.merge_argv())
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["base_sync"], "state-only")
        self.assertEqual(envelope["base_ahead_paths"],
                         [CAMPAIGN_PATH, SPEC_PATH])
        self.assertIs(envelope["admin"], True)

    def test_spec_base_advance_without_the_flag_is_refused(self) -> None:
        self.assert_state_ahead_refused(SPEC_PATH)

    # -- 9. the review stays bound to the implementation ------------------
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


class EnvelopeHeadBaseCase(_BaseSyncKit):
    """PILOT-070: the real merge shape -- ``HEAD`` *is* the base tip.

    At merge time the checkout is ``main`` and ``main`` already equals
    ``origin/main``; only the envelope's ``implementation_head_sha`` is behind.
    A ``HEAD``-based merge-base therefore equals the tip and the old policy saw
    ``[]`` forever.  These cases build that shape (a base-side envelope, as in
    063/065/066/067/068/070) and drive the real ``merge --mode pr``.
    """

    def setUp(self) -> None:
        super().setUp()
        # The base-side envelope lives on main and the implementation branch
        # carries code only, so drop the 058 branch-side envelope commit.
        ok(run_git(self.kit, "checkout", BRANCH))
        ok(run_git(self.kit, "reset", "--hard", self.implementation_head))
        ok(run_git(self.kit, "checkout", BASE))
        self.merge_preview_sha = ""

    # -- fixture ----------------------------------------------------------
    def gh_env(self) -> dict:
        env = super().gh_env()
        if self.merge_preview_sha:
            env["RG_BRANCH_SHA"] = self.merge_preview_sha
        return env

    def promote_base_side(self) -> None:
        """checkback -> accept -> base-side envelope -> queue (063 + 058)."""
        cp = self.checkback("--head", self.implementation_head,
                            "--base", self.base_sha)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("accept", "--task", TASK, "--decision", "D-070")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        write_json(self.kit / ENVELOPE_REPO_PATH, {"envelope_id": ENVELOPE})
        ok(run_git(self.kit, "add", "--", ENVELOPE_REPO_PATH))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "commit",
                   "-m", "base-side envelope"))
        self.envelope_head = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        write_json(self.root / "envelope.json", self.payload())
        cp = self.cli("envelope-new", "--task", TASK,
                      "--file", str(self.root / "envelope.json"), "--base-side")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        cp = self.cli("queue-add", "--envelope", ENVELOPE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def state_ahead(self) -> str:
        """Publish a state-only base commit and catch local ``main`` up to it."""
        ahead = self.advance_base_paths([STATE_PATH])
        ok(run_git(self.kit, "reset", "--hard", ahead))
        self.assertEqual(run_git(self.kit, "rev-parse", "main").stdout.strip(),
                         ahead)
        self.assertEqual(
            run_git(self.origin, "rev-parse", "refs/heads/main").stdout.strip(),
            ahead)
        return ahead

    def preview_merge(self, ahead: str) -> str:
        """The merge commit GitHub would create, pushed so the ff can find it."""
        ok(run_git(self.kit, "checkout", "-b", "merge-preview", ahead))
        ok(run_git(self.kit, "-c", "commit.gpgsign=false", "merge", "--no-ff",
                   BRANCH, "-m", "preview merge"))
        self.merge_preview_sha = run_git(
            self.kit, "rev-parse", "HEAD").stdout.strip()
        ok(run_git(self.kit, "push", "origin",
                   f"{self.merge_preview_sha}:refs/heads/merge-preview"))
        ok(run_git(self.kit, "checkout", BASE))
        return self.merge_preview_sha

    def assert_refused(self, cp: subprocess.CompletedProcess,
                       needle: str) -> list[str]:
        """The common refusal shape: exit 2, no event, no gh, nothing written."""
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        errors = json.loads(cp.stdout)["errors"]
        self.assertTrue(any(needle in error for error in errors), errors)
        self.assertEqual(self.envelope_state()["status"], "DRAFT")
        self.assertEqual(self.queue_status(), "WAITING")
        events = merge_event_types(self.root)
        self.assertFalse([event for event in events
                          if event.startswith("MERGE")], events)
        self.assertFalse(self.gh_log.exists())
        return errors

    # -- 1. HEAD at the base tip, implementation behind -------------------
    def test_base_tip_head_impl_behind_state_base_is_audited_admin(self) -> None:
        self.promote_base_side()
        ahead = self.state_ahead()
        self.assertNotEqual(ahead, self.implementation_head)
        tip = run_git(self.origin, "rev-parse",
                      "refs/heads/main").stdout.strip()
        head = run_git(self.kit, "rev-parse", "HEAD").stdout.strip()
        # The premise of the bug: HEAD and origin/main are the same commit, so
        # a merge-base of HEAD..tip is the tip itself (base-ahead was []).
        self.assertEqual(head, tip)
        self.assertEqual(run_git(self.kit, "merge-base", "HEAD", tip)
                         .stdout.strip(), tip)
        # ... while the implementation head still sees the base-only commits.
        self.assertEqual(
            tower_cli.base_ahead_paths(self.kit, self.implementation_head),
            [STATE_PATH, ENVELOPE_REPO_PATH])
        merge_commit = self.preview_merge(ahead)
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        argv = self.merge_argv()
        self.assertIn("--admin", argv)
        self.assertEqual(argv[argv.index("--match-head-commit") + 1],
                         self.implementation_head)
        envelope = self.envelope_state()
        self.assertEqual(envelope["status"], "MERGED")
        self.assertEqual(envelope["merge_commit"], merge_commit)
        self.assertEqual(envelope["base_sync"], "state-only")
        self.assertIn(STATE_PATH, envelope["base_ahead_paths"])
        self.assertIn(ENVELOPE_REPO_PATH, envelope["base_ahead_paths"])
        self.assertNotIn(BRANCH_CODE_PATH, envelope["base_ahead_paths"])
        self.assertIs(envelope["admin"], True)
        entry = self.merge_ledger_entry()
        self.assertEqual(entry["base_sync"], "state-only")
        self.assertEqual(entry["base_ahead_paths"],
                         envelope["base_ahead_paths"])
        self.assertIs(entry["admin"], True)
        payload = self.merge_payload()
        self.assertEqual(payload["base_sync"], "state-only")
        self.assertEqual(payload["base_ahead_paths"],
                         envelope["base_ahead_paths"])
        self.assertIs(payload["admin"], True)

    # -- 2. a real code path on the base is still refused ------------------
    def test_base_code_ahead_is_refused_even_with_the_flag(self) -> None:
        self.promote_base_side()
        ahead = self.advance_base_paths([CODE_PATH])
        ok(run_git(self.kit, "reset", "--hard", ahead))
        cp = self.run_merge("--allow-state-ahead")
        errors = self.assert_refused(cp, CODE_PATH)
        self.assertIn("--admin is never allowed", errors[0])
        self.assertIn("git rebase origin/main", cp.stdout)

    # -- 3. without the flag even state-only is refused --------------------
    def test_state_ahead_without_the_flag_is_refused(self) -> None:
        self.promote_base_side()
        self.state_ahead()
        cp = self.run_merge()
        errors = self.assert_refused(cp, "--allow-state-ahead")
        self.assertIn(STATE_PATH, errors[0])

    # -- 4. the implementation head is required (no HEAD fallback) ---------
    def test_missing_implementation_head_is_refused(self) -> None:
        self.promote_base_side()
        self.state_ahead()
        env_path = self.envelope_path()
        env = read_json(env_path)
        env.pop("implementation_head_sha", None)
        write_json(env_path, env)
        cp = self.run_merge("--allow-state-ahead")
        self.assert_refused(cp, "implementation_head_sha")
        self.assertIn("never falls back to HEAD", cp.stdout)

    def test_unresolvable_implementation_head_is_refused(self) -> None:
        self.promote_base_side()
        self.state_ahead()
        env_path = self.envelope_path()
        env = read_json(env_path)
        env["implementation_head_sha"] = "0" * 40
        write_json(env_path, env)
        cp = self.run_merge("--allow-state-ahead")
        self.assert_refused(cp, "not a resolvable commit")

    def test_missing_envelope_is_refused(self) -> None:
        self.promote_base_side()
        self.envelope_path().unlink()
        cp = self.run_merge("--allow-state-ahead")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("envelope not found", cp.stdout)
        self.assertFalse(self.gh_log.exists())


class BasePathClassificationCase(unittest.TestCase):
    """The whitelist is exact; anything unrecognised falls to code/docs."""

    def test_state_paths_and_code_paths_split_by_prefix(self) -> None:
        state_paths = ["tower-dsh/ledger/primary.jsonl",
                       "tower-dsh/primary/CURRENT_STATE.json",
                       "tower-dsh/supervision/CURRENT_STATE.json",
                       "tower-dsh/tasks/PILOT-067/TASK.md",
                       "tower-dsh/state/PROFILE-TOWER-DSH.md",
                       "tower-dsh/merge-envelopes/ENV-PILOT-068.json",
                       "tower-dsh/pilot/PILOT-071.spec.json",
                       "tower-dsh/pilot/PILOT-073.spec.json",
                       "tower-dsh/command/campaigns/C-2026-Q4-04.md"]
        code_paths = ["tower-dsh/tools/tower_merge.py",
                      "tower-dsh/arch/ADR-0009-delivery-trust.md",
                      "tower-dsh/EVENT_CATALOG.json",
                      "tower-dsh/pilot/PILOT-067.md",
                      "tower-dsh/pilot/PILOT-073.spec.json.bak",
                      "tower-dsh/pilot/worktrees/PILOT-071/tower-dsh/tools/tower_cli.py",
                      "tower-dsh/command/campaigns.md",
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

    def test_pilot_spec_and_campaign_are_state_only_inside_the_tower(self) -> None:
        # PILOT-073: the spec/campaign pair is exactly what 071 lost.
        state, code = tower_cli.classify_base_paths(
            ["tower-dsh/pilot/PILOT-071.spec.json",
             "tower-dsh/command/campaigns/C-2026-Q4-04.md"], "tower-dsh/")
        self.assertEqual(state, ["tower-dsh/pilot/PILOT-071.spec.json",
                                 "tower-dsh/command/campaigns/C-2026-Q4-04.md"])
        self.assertEqual(code, [])
        # Only the top-level ``pilot/<card>.spec.json`` spelling is state: a
        # second level or another suffix stays code (the flag never widens it).
        state, code = tower_cli.classify_base_paths(
            ["tower-dsh/pilot/nested/PILOT-071.spec.json",
             "tower-dsh/pilot/PILOT-071.spec.json.orig"], "tower-dsh/")
        self.assertEqual(state, [])
        self.assertEqual(code, ["tower-dsh/pilot/nested/PILOT-071.spec.json",
                                "tower-dsh/pilot/PILOT-071.spec.json.orig"])


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
