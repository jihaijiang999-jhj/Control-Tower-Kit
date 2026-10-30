"""Tests for the PILOT-052 object layer: ``towerctl profile-check``.

Positive cases run against the real worktree.  Every negative case builds a
throw-away copy of the tower (``tools/``, ``state/``, ``arch/``, ``adr/``,
``ARCHITECTURE.md``, ``EVENT_CATALOG.json``) under the runner's ``TMP``
sandbox, writes exactly one broken PROFILE there and drives the real CLI, so
exit codes and the single-JSON error contract are asserted as a caller
observes them::

    python -B tools/run_tests.py --pattern test_profile.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"
COPIED = ("tools", "state", "arch", "adr", "ARCHITECTURE.md",
          "EVENT_CATALOG.json", "specs", "templates", "command")
TREE_DIRS = ("primary", "supervision", "ledger", "tasks", "state")
FACT_IDS = ("AUTH", "AUTH-CONF", "LEDGER", "STATE", "ARCH", "CAMPAIGN",
            "SHAPE", "SPEC", "WHERE", "STARTUP", "SPEC-COVERAGE")
HEAD = """---
schema: tower/profile@1
object: FIXTURE
version: 1
updated: 2026-10-30
owner: mac
status: active
---

| id | fact | probe | expect | why |
|---|---|---|---|---|
"""


def tower_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def tower_copy() -> Path:
    """A writable copy of the tower laid out as ``<tmp>/tower-dsh``."""
    target = Path(tempfile.mkdtemp(prefix="pilot052-")) / "tower-dsh"
    target.mkdir()
    for name in COPIED:
        source = TOWER_ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target / name)
    return target


def digest_tree(relatives: tuple[str, ...]) -> str:
    """One digest over every file under the given tower-relative directories."""
    digest = hashlib.sha256()
    for name in relatives:
        base = TOWER_ROOT / name
        for profile in sorted(base.rglob("*")):
            if profile.is_file():
                digest.update(
                    profile.relative_to(TOWER_ROOT).as_posix().encode("utf-8"))
                digest.update(profile.read_bytes())
    return digest.hexdigest()


def profile_doc(*rows: str) -> str:
    return HEAD + "".join(rows)


def fact(ident: str = "AUTH", probe: str = "arch-check",
         expect: str = "exit=0", why: str = "invariant") -> str:
    return f"| {ident} | fact | {probe} | {expect} | {why} |\n"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def authority_fixture() -> Path:
    """A tower whose authority is configured but not marked required (optional)."""
    root = Path(tempfile.mkdtemp(prefix="pilot052-optional-")) / "tower-dsh"
    for directory in ("primary", "supervision", "ledger", "state"):
        (root / directory).mkdir(parents=True)
    (root / "ledger" / "primary.jsonl").touch()
    (root / "ledger" / "supervision.jsonl").touch()
    write_json(root / "primary" / "CURRENT_STATE.json", {
        "schema": "tower/current-state@1", "tower_id": "tower-dsh",
        "role": "primary", "phase": "TEST", "primary": {"id": "ctl-primary"},
        "owner": {"name": "mac"}, "next_action": "test"})
    write_json(root / "primary" / "TASK_BOARD.json",
               {"schema": "tower/task-board@1", "tasks": []})
    write_json(root / "supervision" / "CURRENT_STATE.json", {
        "schema": "tower/supervision-state@1", "role": "supervision",
        "phase": "TEST", "supervisor": {"id": "sup-A"}})
    write_json(root / "supervision" / "MERGE_QUEUE.json",
               {"schema": "tower/merge-queue@1", "entries": []})
    return root


class ProfileCheckPositiveCase(unittest.TestCase):
    def test_template_is_parseable_without_running_probes(self) -> None:
        cp = tower_cli(TOWER_ROOT, "profile-check", "--file",
                       "state/PROFILE-TEMPLATE.md")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["object"], "OBJECT-ID")
        self.assertEqual(payload["checked"], 0)
        self.assertEqual(payload["findings"], [])

    def test_real_profile_runs_all_facts(self) -> None:
        cp = tower_cli(TOWER_ROOT, "profile-check")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["object"], "TOWER-DSH")
        self.assertEqual(payload["checked"], 11)
        self.assertEqual(payload["findings"], [])
        text = (TOWER_ROOT / "state" / "PROFILE-TOWER-DSH.md").read_text(
            encoding="utf-8")
        for ident in FACT_IDS:
            self.assertIn(f"| {ident} |", text)

    def test_object_selector_matches_default(self) -> None:
        default = tower_cli(TOWER_ROOT, "profile-check")
        by_object = tower_cli(TOWER_ROOT, "profile-check", "--object",
                              "TOWER-DSH")
        self.assertEqual(default.returncode, 0, default.stdout + default.stderr)
        self.assertEqual(by_object.returncode, 0, by_object.stdout + by_object.stderr)
        self.assertEqual(json.loads(default.stdout), json.loads(by_object.stdout))

    def test_profile_check_writes_no_tower_state(self) -> None:
        before = digest_tree(TREE_DIRS)
        cp = tower_cli(TOWER_ROOT, "profile-check")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual(before, digest_tree(TREE_DIRS))


class ProfileCheckNegativeCase(unittest.TestCase):
    def fixture(self) -> Path:
        root = tower_copy()
        self.addCleanup(shutil.rmtree, root.parent, ignore_errors=True)
        return root

    def run_profile(self, root: Path, text: str) -> subprocess.CompletedProcess:
        (root / "state" / "FIXTURE.md").write_text(text, encoding="utf-8")
        return tower_cli(root, "profile-check", "--file", "state/FIXTURE.md")

    def assert_rejected(self, cp: subprocess.CompletedProcess, ident: str) -> None:
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        self.assertTrue(cp.stdout.strip().startswith("{"))
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(sorted(set(payload) - {"checked"}),
                         ["findings", "object", "ok"])
        for item in payload["findings"]:
            self.assertEqual(sorted(item), ["actual", "expected", "id"])
        self.assertIn(ident, {item["id"] for item in payload["findings"]})

    def test_missing_front_matter_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, "# no front-matter\n")
        self.assert_rejected(cp, "state/FIXTURE.md")

    def test_missing_column_is_rejected(self) -> None:
        root = self.fixture()
        text = HEAD.replace("| id | fact | probe | expect | why |",
                            "| id | fact | probe | why |")
        self.assert_rejected(self.run_profile(root, text), "state/FIXTURE.md")

    def test_duplicate_id_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(), fact()))
        self.assert_rejected(cp, "AUTH")

    def test_unknown_probe_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(probe="no-such-probe")))
        self.assert_rejected(cp, "AUTH")

    def test_write_probe_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(probe="merge")))
        self.assert_rejected(cp, "AUTH")

    def test_recursive_probe_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(probe="profile-check")))
        self.assert_rejected(cp, "AUTH")

    def test_bad_expect_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(expect="exit=zero")))
        self.assert_rejected(cp, "AUTH")

    def test_bad_table_is_rejected(self) -> None:
        root = self.fixture()
        text = HEAD.replace("|---|---|---|---|---|\n", "")
        self.assert_rejected(self.run_profile(root, text), "state/FIXTURE.md")

    def test_missing_file_is_rejected(self) -> None:
        root = self.fixture()
        cp = tower_cli(root, "profile-check", "--file", "state/MISSING.md")
        self.assert_rejected(cp, "state/MISSING.md")

    def test_exit_mismatch_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(root, profile_doc(fact(expect="exit=1")))
        self.assert_rejected(cp, "AUTH")
        findings = json.loads(cp.stdout)["findings"]
        self.assertEqual(findings[0]["actual"], "exit=0")

    def test_stdout_mismatch_is_rejected(self) -> None:
        root = self.fixture()
        cp = self.run_profile(
            root, profile_doc(fact(expect="exit=0; stdout=__absent__")))
        self.assert_rejected(cp, "AUTH")
        findings = json.loads(cp.stdout)["findings"]
        self.assertIn("stdout has no", findings[0]["actual"])

    def test_optional_authority_breaks_required_fact(self) -> None:
        root = authority_fixture()
        self.addCleanup(shutil.rmtree, root.parent, ignore_errors=True)
        setup = tower_cli(root, "authority-set", "--supervisor", "sup-A",
                          "--decision", "D-FIX", "--by", "mac")
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        text = profile_doc(
            fact(ident="AUTH", probe="authority-check",
                 expect='exit=0; stdout="required": true'),
            fact(ident="AUTH-CONF", probe="authority-check",
                 expect='exit=0; stdout="status": "configured"'))
        cp = self.run_profile(root, text)
        self.assert_rejected(cp, "AUTH")
        findings = json.loads(cp.stdout)["findings"]
        self.assertEqual([item["id"] for item in findings], ["AUTH"])


if __name__ == "__main__":
    unittest.main()
