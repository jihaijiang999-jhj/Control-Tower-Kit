"""Tests for the PILOT-048 architecture spine: ``arch-check`` / ``arch-graph``.

Positive cases run against the real worktree; every negative case builds its own
throw-away copy of the tower (``tools/``, ``arch/``, ``adr/``, ``ARCHITECTURE.md``,
``EVENT_CATALOG.json``) under the runner's ``TMP`` sandbox, mutates exactly one
fact and drives the real CLI, so exit codes and the single-JSON error contract are
asserted as a caller observes them::

    python -B tools/run_tests.py --pattern test_arch.py
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
WORKTREE = TOWER_ROOT.parent
TCLI = TOOLS_DIR / "towerctl.py"
ADR_REL = "adr/ADR-0001-initial-design.md"
ORIGINAL_DESIGN_SHA256 = (
    "46ae26fe4850bd7acdc805654624e4d25fc34d08ce5c20a4398209ec6ae6d5b8")
COPIED = ("tools", "arch", "adr", "ARCHITECTURE.md", "EVENT_CATALOG.json")
TREE_DIRS = ("primary", "supervision", "ledger", "tasks")


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def tower_copy() -> Path:
    """A writable copy of the tower laid out as ``<tmp>/tower-dsh``."""
    target = Path(tempfile.mkdtemp(prefix="pilot048-")) / "tower-dsh"
    target.mkdir()
    for name in COPIED:
        source = TOWER_ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target / name)
    return target


def tree_digest(bases: tuple[Path, ...]) -> str:
    """One digest over every file under ``bases`` (path + bytes, sorted)."""
    digest = hashlib.sha256()
    for base in bases:
        for path in sorted(base.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(TOWER_ROOT).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def adr_body(path: Path) -> bytes:
    """Everything after the closing front-matter fence, byte-for-byte."""
    data = path.read_bytes()
    head, separator, body = data.partition(b"\n---\n")
    if not separator:
        raise AssertionError("ADR has no closing front-matter fence")
    return body


class ArchCheckPositiveCase(unittest.TestCase):
    def test_real_worktree_arch_check_is_green(self) -> None:
        cp = run_cli(TOWER_ROOT, "arch-check")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        counts = payload["counts"]
        self.assertEqual(counts["gates"], 17)
        self.assertEqual(counts["invariants"], 16)
        self.assertEqual(counts["sections"], 6)
        self.assertEqual(counts["events"], counts["event_types_in_code"])
        self.assertGreaterEqual(counts["adrs"], 1)
        self.assertGreaterEqual(counts["edges"], 1)

    def test_arch_graph_is_parseable_and_byte_stable(self) -> None:
        first = run_cli(TOWER_ROOT, "arch-graph", "--json")
        second = run_cli(TOWER_ROOT, "arch-graph", "--json")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        graph = json.loads(first.stdout)
        self.assertEqual(graph["schema"], "tower/arch-graph@1")
        self.assertEqual(sorted(graph), ["edges", "nodes", "schema"])
        self.assertEqual(graph["nodes"], sorted(graph["nodes"]))
        pairs = [(edge["from"], edge["to"]) for edge in graph["edges"]]
        self.assertEqual(pairs, sorted(pairs))
        self.assertIn("tools/towerctl.py", graph["nodes"])
        self.assertNotIn("generated", first.stdout.lower())
        self.assertNotIn("2026-", first.stdout)

    def test_design_md_is_archived_as_adr_0001(self) -> None:
        self.assertFalse((TOWER_ROOT / "DESIGN.md").exists())
        self.assertFalse((WORKTREE / "control-tower" / "DESIGN.md").exists())
        adr = TOWER_ROOT / ADR_REL
        self.assertTrue(adr.is_file())
        self.assertEqual(hashlib.sha256(adr_body(adr)).hexdigest(),
                         ORIGINAL_DESIGN_SHA256)

    def test_arch_commands_are_read_only(self) -> None:
        bases = tuple(TOWER_ROOT / name for name in TREE_DIRS)
        before = tree_digest(bases)
        check = run_cli(TOWER_ROOT, "arch-check")
        graph = run_cli(TOWER_ROOT, "arch-graph", "--json")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(graph.returncode, 0, graph.stdout + graph.stderr)
        self.assertEqual(before, tree_digest(bases))


class ArchCheckNegativeCase(unittest.TestCase):
    def fixture(self) -> Path:
        root = tower_copy()
        self.addCleanup(shutil.rmtree, root.parent, ignore_errors=True)
        return root

    def assert_arch_failure(self, root: Path, code: str) -> None:
        cp = run_cli(root, "arch-check")
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertFalse(payload["ok"])
        for item in payload["errors"]:
            self.assertEqual(sorted(item), ["code", "detail", "target"])
        self.assertIn(code, {item["code"] for item in payload["errors"]})

    def test_unknown_gate_command_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "arch" / "GATES.json"
        data = read_json(path)
        data["gates"][0]["command"] = "no-such-command"
        write_json(path, data)
        self.assert_arch_failure(root, "GATE_COMMAND")

    def test_unknown_gate_test_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "arch" / "GATES.json"
        data = read_json(path)
        data["gates"][0]["test"] = "test_missing_gate_probe_048"
        write_json(path, data)
        self.assert_arch_failure(root, "GATE_TEST")

    def test_invariant_without_c16_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "arch" / "INVARIANTS.json"
        data = read_json(path)
        data["invariants"] = [item for item in data["invariants"]
                              if item["id"] != "C-16"]
        write_json(path, data)
        self.assert_arch_failure(root, "INVARIANT_MISSING")

    def test_invariant_probe_must_exist(self) -> None:
        root = self.fixture()
        path = root / "arch" / "INVARIANTS.json"
        data = read_json(path)
        for item in data["invariants"]:
            if item["id"] == "C-16":
                item["probe"] = {"kind": "test", "ref": "test_missing_probe_048"}
        write_json(path, data)
        self.assert_arch_failure(root, "INVARIANT_PROBE")

    def test_catalog_missing_a_code_type_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "EVENT_CATALOG.json"
        data = read_json(path)
        data["events"] = [item for item in data["events"]
                          if item["type"] != "MERGE"]
        write_json(path, data)
        self.assert_arch_failure(root, "EVENT_MISSING")

    def test_catalog_extra_type_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "EVENT_CATALOG.json"
        data = read_json(path)
        extra = dict(data["events"][0])
        extra.update({"type": "NO_SUCH_EVENT", "producer": "merge",
                      "ledger": "primary", "payload_required": ["x"],
                      "state_verify": False, "drift_kinds": [],
                      "note": "fixture"})
        data["events"].append(extra)
        write_json(path, data)
        self.assert_arch_failure(root, "EVENT_EXTRA")

    def test_invalid_adr_status_is_rejected(self) -> None:
        root = self.fixture()
        path = root / ADR_REL
        path.write_text(path.read_text(encoding="utf-8").replace(
            "status: archived", "status: bogus"), encoding="utf-8")
        self.assert_arch_failure(root, "ADR_STATUS")

    def test_missing_adr_related_file_is_rejected(self) -> None:
        root = self.fixture()
        path = root / ADR_REL
        path.write_text(path.read_text(encoding="utf-8").replace(
            "  - tower-dsh/tools/towerctl.py",
            "  - tower-dsh/tools/does-not-exist.py"), encoding="utf-8")
        self.assert_arch_failure(root, "ADR_RELATED")

    def test_adr_related_file_rejects_drive_path(self) -> None:
        root = self.fixture()
        path = root / ADR_REL
        path.write_text(path.read_text(encoding="utf-8").replace(
            "  - tower-dsh/tools/towerctl.py",
            '  - "C:/Windows/win.ini"'), encoding="utf-8")
        self.assert_arch_failure(root, "ADR_RELATED")

    def test_adr_related_file_rejects_parent_escape(self) -> None:
        root = self.fixture()
        path = root / ADR_REL
        path.write_text(path.read_text(encoding="utf-8").replace(
            "  - tower-dsh/tools/towerctl.py",
            "  - ../outside-the-tower.md"), encoding="utf-8")
        self.assert_arch_failure(root, "ADR_RELATED")

    def test_duplicate_tool_stem_is_rejected(self) -> None:
        root = self.fixture()
        source = root / "tools" / "towerctl.py"
        duplicate = root / "tools" / "zzz" / "towerctl.py"
        duplicate.parent.mkdir()
        duplicate.write_text(source.read_text(encoding="utf-8"),
                             encoding="utf-8")
        self.assert_arch_failure(root, "GRAPH_STEM_DUPLICATE")
        cp = run_cli(root, "arch-graph", "--json")
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        self.assertFalse(json.loads(cp.stdout)["ok"])

    def test_missing_architecture_section_is_rejected(self) -> None:
        root = self.fixture()
        path = root / "ARCHITECTURE.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "## 3. 数据流\n", ""), encoding="utf-8")
        self.assert_arch_failure(root, "ARCH_SECTION")

    def test_towerctl_must_not_import_tests(self) -> None:
        root = self.fixture()
        path = root / "tools" / "towerctl.py"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n\ndef _arch_boundary_fixture():\n"
                         "    import test_arch  # noqa: F401\n")
        self.assert_arch_failure(root, "BOUNDARY_IMPORT")

    def test_unreadable_catalog_is_one_json_error(self) -> None:
        root = self.fixture()
        (root / "EVENT_CATALOG.json").write_text("{not json", encoding="utf-8")
        self.assert_arch_failure(root, "JSON_UNREADABLE")


if __name__ == "__main__":
    unittest.main()
