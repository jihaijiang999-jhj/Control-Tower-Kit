"""Clause coverage gate plus the supplementary clause tests it binds (PILOT-009).

``CoverageGateTestCase`` drives ``towerctl spec-coverage``: the real tower root
must be fully covered, while unknown clause ids, unknown test ids and unbound
``tool-check`` clauses exit 2.  ``review-check`` / ``owner-gate`` clauses are
reported as manual / owner and never fail.

The remaining classes are real gate tests for clauses that had no semantically
matching test before.  They live here (rather than in the pre-existing test
modules) so PILOT-009 does not change any existing test behaviour; the
``clause_bindings`` map points at these ids.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"
FIXED_TIME = "2026-10-19T00:00:00+08:00"

sys.path.insert(0, str(TOOLS_DIR))
import towerctl  # noqa: E402  (import after sys.path setup)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )


# ---------------------------------------------------------------------------
# coverage gate
# ---------------------------------------------------------------------------
WORKFLOW_TEMPLATE = """---
schema: tower/workflow@1
id: WF-FIX
title: clause coverage fixture
owner: tester
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-FIX — clause coverage fixture

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
{rows}
"""

SAMPLE_TEST = '''import unittest


class SampleTest(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertTrue(True)
'''


def spec_text(rows: list[tuple[str, str]]) -> str:
    body = "\n".join(f"| {clause_id} | fixture clause {clause_id} | {enforcement} |"
                     for clause_id, enforcement in rows)
    return WORKFLOW_TEMPLATE.format(rows=body)


def bindings_text(mapping: dict[str, list[str]]) -> str:
    lines = ["BINDINGS = {"]
    for key, test_ids in mapping.items():
        lines.append(f"    {key!r}: [")
        lines.extend(f"        {test_id!r}," for test_id in test_ids)
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines) + "\n"


class CoverageGateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-coverage-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        (self.root / "specs").mkdir()
        self.tests_dir = self.root / "tests"
        self.tests_dir.mkdir()
        (self.tests_dir / "test_sample.py").write_text(SAMPLE_TEST, encoding="utf-8")
        self.bindings = self.root / "bindings.py"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_spec(self, rows: list[tuple[str, str]]) -> None:
        (self.root / "specs" / "wf-fix.md").write_text(
            spec_text(rows), encoding="utf-8")

    def write_bindings(self, mapping: dict[str, list[str]]) -> Path:
        self.bindings.write_text(bindings_text(mapping), encoding="utf-8")
        return self.bindings

    def run_gate(self, *, bindings: Path | None = None,
                 tests_dir: Path | None = None) -> tuple[subprocess.CompletedProcess, dict]:
        cp = run_cli(self.root, "spec-coverage",
                     "--bindings", str(bindings or self.bindings),
                     "--tests-dir", str(tests_dir or self.tests_dir))
        self.assertTrue(cp.stdout.strip(), msg=f"stderr={cp.stderr}")
        return cp, json.loads(cp.stdout)

    def unknown_kinds(self, data: dict) -> list[str]:
        return [entry.get("kind") for entry in data["unknown"]]

    # -- 1. the real tower root is fully covered -------------------------
    def test_real_tower_root_is_fully_covered(self) -> None:
        cp = run_cli(TOWER_ROOT, "spec-coverage")
        self.assertEqual(cp.returncode, 0,
                         msg=f"stdout={cp.stdout}\nstderr={cp.stderr}")
        data = json.loads(cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["specs"], 6)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["tool_gaps"], [])
        self.assertEqual(data["unknown"], [])
        self.assertGreater(data["tool_check"], 0)
        self.assertEqual(data["covered"], data["tool_check"])
        self.assertEqual(len(data["manual"]), len(set(data["manual"])))
        self.assertEqual(len(data["owner"]), len(set(data["owner"])))

    # -- 2. binding to a test id that does not exist ---------------------
    def test_binding_to_unknown_test_id_exits_two(self) -> None:
        self.write_spec([("INV-01", "tool-check")])
        self.write_bindings({
            "WF-FIX/INV-01": ["test_sample.SampleTest.test_missing"],
        })
        cp, data = self.run_gate()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual(data["tool_gaps"], [])
        self.assertIn("unknown_test", self.unknown_kinds(data))
        entry = next(u for u in data["unknown"] if u["kind"] == "unknown_test")
        self.assertEqual(entry["clause"], "WF-FIX/INV-01")
        self.assertEqual(entry["test"], "test_sample.SampleTest.test_missing")

    # -- 3. binding a key that is not a known clause ---------------------
    def test_binding_to_unknown_clause_id_exits_two(self) -> None:
        self.write_spec([("INV-01", "tool-check")])
        self.write_bindings({
            "WF-FIX/INV-01": ["test_sample.SampleTest.test_ok"],
            "WF-FIX/INV-99": ["test_sample.SampleTest.test_ok"],
        })
        cp, data = self.run_gate()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout)
        self.assertFalse(data["ok"])
        self.assertIn("unknown_clause", self.unknown_kinds(data))
        self.assertIn({"kind": "unknown_clause", "clause": "WF-FIX/INV-99"},
                      data["unknown"])

    # -- 4. a new tool-check clause without a binding --------------------
    def test_unbound_tool_check_clause_exits_two(self) -> None:
        self.write_spec([("INV-01", "tool-check"), ("INV-02", "tool-check")])
        self.write_bindings({
            "WF-FIX/INV-01": ["test_sample.SampleTest.test_ok"],
        })
        cp, data = self.run_gate()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout)
        self.assertFalse(data["ok"])
        self.assertEqual(data["tool_gaps"], ["WF-FIX/INV-02"])
        self.assertEqual(data["unknown"], [])
        self.assertEqual(data["covered"], 1)
        self.assertEqual(data["tool_check"], 2)

    # -- 5. review-check / owner-gate are manual / owner, not failures ---
    def test_manual_and_owner_clauses_do_not_fail(self) -> None:
        self.write_spec([
            ("INV-01", "tool-check"),
            ("INV-03", "review-check"),
            ("INV-04", "owner-gate"),
        ])
        self.write_bindings({
            "WF-FIX/INV-01": ["test_sample.SampleTest.test_ok"],
        })
        cp, data = self.run_gate()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["specs"], 1)
        self.assertEqual(data["clauses"], 3)
        self.assertEqual(data["tool_check"], 1)
        self.assertEqual(data["covered"], 1)
        self.assertEqual(data["manual"], ["WF-FIX/INV-03"])
        self.assertEqual(data["owner"], ["WF-FIX/INV-04"])
        self.assertEqual(data["tool_gaps"], [])
        self.assertEqual(data["unknown"], [])

    # -- 6. --bindings / --tests-dir point at temporary fixtures ---------
    def test_bindings_and_tests_dir_overrides(self) -> None:
        alt_tests = self.root / "alt-tests"
        alt_tests.mkdir()
        (alt_tests / "test_custom.py").write_text(
            "import unittest\n\n\n"
            "class CustomTest(unittest.TestCase):\n"
            "    def test_present(self) -> None:\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        alt_bindings = self.root / "config" / "custom_bindings.py"
        alt_bindings.parent.mkdir()
        alt_bindings.write_text(bindings_text({
            "WF-FIX/INV-01": ["test_custom.CustomTest.test_present"],
        }), encoding="utf-8")
        self.write_spec([("INV-01", "tool-check")])

        cp, data = self.run_gate(bindings=alt_bindings, tests_dir=alt_tests)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["specs"], 1)
        self.assertEqual(data["tool_check"], 1)
        self.assertEqual(data["covered"], 1)


# ---------------------------------------------------------------------------
# WF-TASK supplementary clause tests
# ---------------------------------------------------------------------------
TASK_ID = "T-001"


class TaskInvariantTestCase(unittest.TestCase):
    """Real task-gate tests for INV-06 (no skipping) and INV-07 (ledger)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-task-invariants-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "ledger", "specs",
                          f"tasks/{TASK_ID}/evidence",
                          f"pilot/worktrees/{TASK_ID}"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.spec_path = self.root / "specs" / "task.spec.json"
        write_json(self.spec_path, {
            "schema": "tower/spec@1",
            "id": TASK_ID,
            "title": "clause invariant",
            "authority": "workspace_write",
            "scope": ["exercise task invariants"],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
        })
        self.record = {
            "schema": "tower/task@1",
            "id": TASK_ID,
            "title": "clause invariant",
            "status": "ready",
            "authority": "workspace_write",
            "scope": ["exercise task invariants"],
            "allowed_paths": ["tools/example.py"],
            "forbidden": ["merge", "production access"],
            "acceptance": ["tests pass"],
            "depends_on": [],
            "worktree": f"pilot/worktrees/{TASK_ID}",
            "spec_path": "specs/task.spec.json",
            "spec_sha256": sha256_file(self.spec_path),
            "spec_gate": "PASS",
            "executor": None,
            "dispatch": None,
            "evidence": [],
            "review": None,
            "decision": None,
            "closeout": None,
            "created_at": FIXED_TIME,
            "updated_at": FIXED_TIME,
            "next": "",
        }
        self.write_record()
        (self.root / "tasks" / TASK_ID / "TASK.md").write_text(
            f"# {TASK_ID} — clause invariant\n", encoding="utf-8")
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / TASK_ID / "record.json", data)
        self.record = data

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def valid_evidence(self) -> list[dict]:
        proof = self.root / "tasks" / TASK_ID / "evidence" / "proof.txt"
        proof.write_text("proof of work\n", encoding="utf-8")
        return [{
            "id": "E-001",
            "path": f"tasks/{TASK_ID}/evidence/proof.txt",
            "sha256": sha256_file(proof),
            "bytes": proof.stat().st_size,
            "at": FIXED_TIME,
        }]

    def ledger_events(self) -> list[dict]:
        path = self.root / "ledger" / "primary.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # -- INV-06: only documented transitions; no ready -> accepted --------
    def test_state_transitions_reject_skips(self) -> None:
        self.write_record(status="ready", executor="exec-a",
                          review={"reviewer": "rev-a", "verdict": "PASS"},
                          evidence=self.valid_evidence())

        skipped_accept = run_cli(self.root, "accept", "--task", TASK_ID,
                                 "--decision", "D-1")
        self.assertEqual(skipped_accept.returncode, 2,
                         msg=skipped_accept.stdout + skipped_accept.stderr)
        self.assertIn("cannot accept", skipped_accept.stdout)
        record = self.load_record()
        self.assertEqual(record["status"], "ready")
        self.assertIsNone(record["decision"])

        skipped_close = run_cli(self.root, "close", "--task", TASK_ID)
        self.assertEqual(skipped_close.returncode, 2,
                         msg=skipped_close.stdout + skipped_close.stderr)
        self.assertIn("cannot close", skipped_close.stdout)
        self.assertEqual(self.load_record()["status"], "ready")

        self.write_record(status="closed")
        skipped_dispatch = run_cli(self.root, "dispatch", "--task", TASK_ID,
                                   "--executor", "exec-b")
        self.assertEqual(skipped_dispatch.returncode, 2,
                         msg=skipped_dispatch.stdout + skipped_dispatch.stderr)
        self.assertIn("cannot dispatch", skipped_dispatch.stdout)
        self.assertEqual(self.load_record()["status"], "closed")

    # -- INV-07: every state change leaves a ledger event ----------------
    def test_every_state_change_writes_ledger_event(self) -> None:
        proof = self.root / "proof.txt"
        proof.write_text("proof of work\n", encoding="utf-8")
        steps = [
            ("DISPATCH", ("dispatch", "--task", TASK_ID, "--executor", "exec-a")),
            ("DELIVER", ("deliver", "--task", TASK_ID, "--evidence", str(proof))),
            ("CHECKBACK", ("checkback", "--task", TASK_ID,
                           "--reviewer", "rev-a", "--verdict", "PASS")),
            ("ACCEPT", ("accept", "--task", TASK_ID, "--decision", "D-1")),
            ("CLOSEOUT", ("close", "--task", TASK_ID)),
        ]
        for expected, args in steps:
            cp = run_cli(self.root, *args)
            self.assertEqual(cp.returncode, 0,
                             msg=f"{expected}: stdout={cp.stdout}\nstderr={cp.stderr}")
            events = self.ledger_events()
            matching = [event for event in events if event["type"] == expected]
            self.assertEqual(len(matching), 1,
                             msg=f"{expected} not recorded exactly once: {events}")
            self.assertEqual(matching[0]["payload"]["task"], TASK_ID)
        self.assertEqual([event["type"] for event in self.ledger_events()],
                         [name for name, _args in steps])
        self.assertEqual(self.load_record()["status"], "closed")


# ---------------------------------------------------------------------------
# WF-MERGE supplementary clause tests
# ---------------------------------------------------------------------------
MERGE_TASK = "T-MERGE"


class MergeInvariantTestCase(unittest.TestCase):
    """Envelope git checks for WF-MERGE INV-01 / 02 / 03 / 05."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-merge-invariants-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repo = self.root / "pilot" / "repo"
        self.repo.mkdir(parents=True)
        (self.root / "tasks" / MERGE_TASK / "evidence").mkdir(parents=True)
        self.assertEqual(run_git(self.repo, "init").returncode, 0)
        self.assertEqual(
            run_git(self.repo, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.base_sha = self.commit_all("base")

        self.assertEqual(run_git(self.repo, "checkout", "-b", "feature").returncode, 0)
        (self.repo / "implementation.txt").write_text("implementation\n",
                                                      encoding="utf-8")
        self.a_sha = self.commit_all("implementation")

        (self.repo / "merge-envelopes").mkdir()
        write_json(self.repo / "merge-envelopes" / "ENV-1.json",
                   {"envelope_id": "ENV-1"})
        self.b_sha = self.commit_all("envelope")

        self.assertEqual(
            run_git(self.repo, "checkout", "-b", "other", "main").returncode, 0)
        (self.repo / "other.txt").write_text("sibling\n", encoding="utf-8")
        self.commit_all("sibling")
        self.assertEqual(run_git(self.repo, "checkout", "feature").returncode, 0)

        proof = self.root / "tasks" / MERGE_TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        self.record = {
            "schema": "tower/task@1",
            "id": MERGE_TASK,
            "title": "merge invariants",
            "status": "closed",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [{
                "id": "E-001",
                "path": f"tasks/{MERGE_TASK}/evidence/proof.txt",
                "sha256": sha256_file(proof),
                "bytes": proof.stat().st_size,
                "at": FIXED_TIME,
            }],
        }
        self.write_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def commit_all(self, message: str) -> str:
        add = run_git(self.repo, "add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        commit = run_git(self.repo, "-c", "commit.gpgsign=false",
                         "commit", "-m", message)
        self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)
        return run_git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / MERGE_TASK / "record.json", data)
        self.record = data

    def valid_evidence(self) -> list[dict]:
        proof = self.root / "tasks" / MERGE_TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        return [{
            "id": "E-001",
            "path": f"tasks/{MERGE_TASK}/evidence/proof.txt",
            "sha256": sha256_file(proof),
            "bytes": proof.stat().st_size,
            "at": FIXED_TIME,
        }]

    def envelope(self) -> dict:
        return {
            "schema": "tower/merge-envelope@1",
            "envelope_id": "ENV-1",
            "task": MERGE_TASK,
            "repository": "pilot/repo",
            "branch": "feature",
            "base": "main",
            "envelope_path": "merge-envelopes/ENV-1.json",
            "implementation_head_sha": self.a_sha,
            "envelope_head_sha": self.b_sha,
        }

    def check(self, env: dict, name: str) -> dict:
        checks = towerctl.envelope_checks(self.root, env)
        return next(check for check in checks if check["name"] == name)

    # -- INV-01: envelope parent == implementation head ------------------
    def test_envelope_check_requires_parent_equal_implementation(self) -> None:
        env = self.envelope()
        self.assertTrue(
            self.check(env, "envelope parent == implementation head")["ok"],
            msg="fixture envelope must start valid")
        env["implementation_head_sha"] = "0" * 40
        self.assertFalse(
            self.check(env, "envelope parent == implementation head")["ok"])

    # -- INV-02: A..B only contains the envelope path --------------------
    def test_envelope_check_rejects_extra_files_in_envelope_commit(self) -> None:
        checkout = run_git(self.repo, "checkout", "-b", "envelope-extra", self.a_sha)
        self.assertEqual(checkout.returncode, 0, msg=checkout.stderr)
        write_json(self.repo / "merge-envelopes" / "ENV-2.json",
                   {"envelope_id": "ENV-2"})
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        extra_sha = self.commit_all("envelope with an extra file")

        env = self.envelope()
        env.update({"branch": "envelope-extra", "envelope_head_sha": extra_sha,
                    "envelope_path": "merge-envelopes/ENV-2.json"})
        self.assertTrue(
            self.check(env, "envelope parent == implementation head")["ok"],
            msg="parent check must stay valid so the path check is isolated")
        self.assertFalse(
            self.check(env, "envelope commit only changes envelope path")["ok"])

    # -- INV-03: base must be an ancestor of the implementation ----------
    def test_envelope_check_requires_base_ancestor_of_implementation(self) -> None:
        env = self.envelope()
        self.assertTrue(
            self.check(env, "base main is ancestor of implementation")["ok"])
        env["base"] = "other"
        self.assertFalse(
            self.check(env, "base other is ancestor of implementation")["ok"])

    # -- INV-05: accepted/closed + PASS review + reviewer != executor +
    #            valid evidence hashes.
    def test_envelope_check_requires_accepted_task_and_valid_evidence(self) -> None:
        env = self.envelope()
        self.write_record(status="reviewed")
        self.assertFalse(self.check(env, "task accepted/closed")["ok"])

        self.write_record(status="closed",
                          review={"reviewer": "exec-a", "verdict": "PASS"})
        self.assertFalse(self.check(env, "reviewer != executor")["ok"])

        evidence = self.valid_evidence()
        evidence[0]["sha256"] = "0" * 64
        self.write_record(status="closed", evidence=evidence)
        self.assertFalse(self.check(env, "evidence hashes valid")["ok"])


# ---------------------------------------------------------------------------
# WF-HANDOFF supplementary clause tests
# ---------------------------------------------------------------------------
PACKAGE = "HANDOFF-FIX-001"


class HandoffInvariantTestCase(unittest.TestCase):
    """Claim / check / activate gates for WF-HANDOFF INV-01..04."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-handoff-invariants-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "supervision", "ledger",
                          "pilot/repo", "tasks", "handoffs"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": "ctl-src"},
            "owner": {"name": "mac"},
            "next_action": "test",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})

        self.repo = self.root / "pilot" / "repo"
        self.assertEqual(run_git(self.repo, "init").returncode, 0)
        self.assertEqual(
            run_git(self.repo, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.commit_all("base")

        cp = run_cli(self.root, "handoff-new", "--package", PACKAGE)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def commit_all(self, message: str) -> str:
        add = run_git(self.repo, "add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stderr)
        commit = run_git(self.repo, "-c", "commit.gpgsign=false",
                         "commit", "-m", message)
        self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)
        return run_git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def package_dir(self) -> Path:
        return self.root / "handoffs" / PACKAGE

    def package(self) -> dict:
        return read_json(self.package_dir() / "package.json")

    def check(self, pkg: dict, name: str) -> dict:
        checks = towerctl.handoff_checks(self.root, PACKAGE, pkg)
        return next(check for check in checks if check["name"] == name)

    # -- INV-01: receiver controller != source controller ----------------
    def test_handoff_claim_rejects_source_controller(self) -> None:
        pkg = self.package()
        cp = run_cli(self.root, "handoff-claim", "--package", PACKAGE,
                     "--controller", pkg["source_controller"])
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("differ", cp.stdout.lower())
        self.assertFalse((self.package_dir() / "CLAIM.json").exists())

    # -- INV-02: package file hashes must match HANDOFF.md on disk -------
    def test_handoff_check_rejects_tampered_handoff_hash(self) -> None:
        handoff = self.package_dir() / "HANDOFF.md"
        handoff.write_text(handoff.read_text(encoding="utf-8") + "\ntampered\n",
                           encoding="utf-8")
        self.assertFalse(self.check(self.package(), "HANDOFF.md hash")["ok"])

    # -- INV-03: §0 anchors must match the generation-time snapshot ------
    def test_handoff_check_detects_section0_drift(self) -> None:
        pkg = self.package()
        self.assertTrue(self.check(pkg, "main SHA unchanged")["ok"],
                        msg="fixture must start without drift")
        (self.repo / "drift.txt").write_text("drift\n", encoding="utf-8")
        self.commit_all("drift")
        self.assertFalse(self.check(self.package(), "main SHA unchanged")["ok"])

    # -- INV-04: activate requires a prior accept ------------------------
    def test_handoff_activate_requires_acceptance(self) -> None:
        cp = run_cli(self.root, "handoff-activate", "--package", PACKAGE,
                     "--controller", "rev-1")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("not ACCEPTED", cp.stdout)
        self.assertEqual(self.package()["status"], "PREPARED")
        self.assertFalse((self.package_dir() / "ACTIVATION.json").exists())


# ---------------------------------------------------------------------------
# policy supplementary clause tests
# ---------------------------------------------------------------------------
POLICY_TASK = "T-POLICY"


class PolicyInvariantTestCase(unittest.TestCase):
    """Tool-check policy clauses: RED-LINES C-11, CHANGE-LEVELS C-02/03/08."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-policy-invariants-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        for directory in ("primary", "supervision/envelopes", "ledger",
                          f"tasks/{POLICY_TASK}/evidence"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-dsh",
            "role": "primary",
            "primary": {"id": "ctl-primary"},
            "owner": {"name": "mac"},
            "phase": "TEST",
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-1"},
        })
        write_json(self.root / "supervision" / "MERGE_QUEUE.json",
                   {"schema": "tower/merge-queue@1", "entries": []})
        self.envelope_file = self.root / "envelope.json"
        write_json(self.envelope_file, {"envelope_id": "ENV-1",
                                        "task": POLICY_TASK})
        self.record = {
            "schema": "tower/task@1",
            "id": POLICY_TASK,
            "title": "policy invariants",
            "status": "reviewed",
            "executor": "exec-a",
            "review": {"reviewer": "rev-a", "verdict": "PASS"},
            "evidence": [],
        }
        self.write_record()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_record(self, **overrides) -> None:
        data = dict(self.record)
        data.update(overrides)
        write_json(self.root / "tasks" / POLICY_TASK / "record.json", data)
        self.record = data

    def valid_evidence(self) -> list[dict]:
        proof = self.root / "tasks" / POLICY_TASK / "evidence" / "proof.txt"
        proof.write_text("proof\n", encoding="utf-8")
        return [{
            "id": "E-001",
            "path": f"tasks/{POLICY_TASK}/evidence/proof.txt",
            "sha256": sha256_file(proof),
            "bytes": proof.stat().st_size,
            "at": FIXED_TIME,
        }]

    # -- POL-RED-LINES C-11: primary cannot be the merge supervisor ------
    def test_merge_rejects_supervisor_equal_primary(self) -> None:
        cp = run_cli(self.root, "merge", "--envelope", "ENV-1",
                     "--role", "supervisor", "--supervisor", "ctl-primary")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("primary cannot merge", cp.stdout)

    # -- POL-CHANGE-LEVELS C-02: L1 needs accepted task + PASS review ----
    def test_envelope_new_requires_accepted_task_and_pass_review(self) -> None:
        self.write_record(status="reviewed",
                          review={"reviewer": "rev-a", "verdict": "PASS"})
        not_accepted = run_cli(self.root, "envelope-new", "--task", POLICY_TASK,
                               "--file", str(self.envelope_file))
        self.assertEqual(not_accepted.returncode, 2,
                         msg=not_accepted.stdout + not_accepted.stderr)
        self.assertIn("cannot submit envelope", not_accepted.stdout)
        self.assertFalse(
            (self.root / "supervision" / "envelopes" / "ENV-1.json").exists())

        self.write_record(status="accepted",
                          review={"reviewer": "rev-a", "verdict": "FAIL"})
        no_pass = run_cli(self.root, "envelope-new", "--task", POLICY_TASK,
                          "--file", str(self.envelope_file))
        self.assertEqual(no_pass.returncode, 2,
                         msg=no_pass.stdout + no_pass.stderr)
        self.assertIn("no PASS review", no_pass.stdout)

    # -- POL-CHANGE-LEVELS C-03: L2 accept needs a PASS review -----------
    def test_accept_requires_pass_review(self) -> None:
        self.write_record(status="reviewed",
                          review={"reviewer": "rev-a", "verdict": "FAIL"},
                          evidence=self.valid_evidence())
        cp = run_cli(self.root, "accept", "--task", POLICY_TASK,
                     "--decision", "D-1")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("PASS", cp.stdout)
        record = read_json(self.root / "tasks" / POLICY_TASK / "record.json")
        self.assertEqual(record["status"], "reviewed")
        self.assertIsNone(record.get("decision"))

    # -- POL-CHANGE-LEVELS C-08: no merge without a queue entry ----------
    def test_merge_rejects_envelope_not_queued(self) -> None:
        write_json(self.root / "supervision" / "envelopes" / "ENV-1.json", {
            "envelope_id": "ENV-1",
            "task": POLICY_TASK,
            "status": "DRAFT",
            "base": "main",
            "repository": "pilot/repo",
        })
        cp = run_cli(self.root, "merge", "--envelope", "ENV-1",
                     "--role", "supervisor", "--supervisor", "sup-x")
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("not queued", cp.stdout)


if __name__ == "__main__":
    unittest.main()
