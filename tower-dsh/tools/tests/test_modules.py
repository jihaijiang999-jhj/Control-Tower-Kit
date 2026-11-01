"""PILOT-056: ``towerctl`` is a thin entry over 23 modules on a 4-layer DAG.

The split is behaviour-preserving, so this file only owns the structural
contract: every module exists and stays under the size cap, ``towerctl.py`` is
the entry, imports go one way (base -> domain -> compose -> entry), there is no
cycle, and the CLI still starts and answers a read-only command.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
TOWER_ROOT = TOOLS_DIR.parent
TCLI = TOOLS_DIR / "towerctl.py"
MODULE_LIMIT = 600
ENTRY_LIMIT = 3000

LAYERS = {
    "tower_common": "base", "tower_ledger": "base",
    "tower_ledger_replay": "base",
    "tower_task": "domain", "tower_command": "domain",
    "tower_authority": "domain", "tower_authority_cmd": "domain",
    "tower_profile": "domain", "tower_shape": "domain",
    "tower_campaign": "domain", "tower_dispatch": "domain",
    "tower_delivery": "domain", "tower_envelope": "domain",
    "tower_handoff": "domain", "tower_merge": "domain",
    "tower_arch": "domain", "tower_arch_check": "domain",
    "tower_post_merge": "domain",
    "tower_views": "compose", "tower_lookup": "compose",
    "tower_status": "compose", "tower_state_verify": "compose",
    "tower_cli": "entry",
}
# declared total order: a module may only import one that appears earlier
ORDER = [
    "tower_common", "tower_ledger", "tower_ledger_replay",
    "tower_task", "tower_command", "tower_authority", "tower_authority_cmd",
    "tower_profile", "tower_shape", "tower_campaign", "tower_dispatch",
    "tower_delivery", "tower_envelope", "tower_handoff", "tower_merge",
    "tower_arch", "tower_arch_check", "tower_post_merge",
    "tower_views", "tower_lookup", "tower_status", "tower_state_verify",
    "tower_cli",
]
MODULES = [name for name in ORDER if name != "tower_cli"]
LAYER_RANK = {"base": 0, "domain": 1, "compose": 2, "entry": 3}
POSITION = {name: index for index, name in enumerate(ORDER)}


def module_path(name: str) -> Path:
    return TOOLS_DIR / f"{name}.py"


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def imports_of(path: Path) -> set[str]:
    """Every top-level ``tower_*`` module imported by ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return {name for name in names if name.startswith("tower_")}


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(TOWER_ROOT), *args],
        cwd=str(TOWER_ROOT), capture_output=True, text=True, encoding="utf-8")


class ModulesSplitCase(unittest.TestCase):
    def test_modules_present_and_small(self) -> None:
        self.assertEqual(len(ORDER), 23)
        self.assertEqual(len(MODULES), 22)
        self.assertEqual(set(LAYERS), set(ORDER))
        for name in MODULES:
            with self.subTest(module=name):
                path = module_path(name)
                self.assertTrue(path.is_file(), f"missing {path.name}")
                self.assertLess(line_count(path), MODULE_LIMIT,
                                f"{path.name} is {line_count(path)} lines")
                self.assertIn(LAYERS[name], LAYER_RANK)

    def test_towerctl_entry_is_thin_and_reexports(self) -> None:
        self.assertLess(line_count(TCLI), ENTRY_LIMIT)
        imports = imports_of(TCLI)
        self.assertIn("tower_cli", imports)
        self.assertFalse(imports & {"test_arch", "test_modules"})
        sys.path.insert(0, str(TOOLS_DIR))
        import towerctl  # noqa: E402  (import after sys.path setup)
        self.assertTrue(callable(towerctl.main))
        self.assertTrue(hasattr(towerctl, "build_parser"))
        self.assertEqual(len(towerctl.cli_commands()), 52)

    def test_import_dag_is_one_way_and_acyclic(self) -> None:
        edges = {name: imports_of(module_path(name)) for name in MODULES}
        edges["tower_cli"] = imports_of(module_path("tower_cli"))
        for importer, targets in edges.items():
            for target in targets:
                with self.subTest(importer=importer, target=target):
                    self.assertIn(target, LAYERS)
                    self.assertLessEqual(LAYER_RANK[LAYERS[target]],
                                         LAYER_RANK[LAYERS[importer]])
                    if LAYERS[target] == LAYERS[importer]:
                        self.assertLess(POSITION[target], POSITION[importer])
        seen: dict[str, int] = {}

        def visit(node: str) -> None:
            self.assertNotEqual(seen.get(node), 1, f"import cycle at {node}")
            if seen.get(node) == 2:
                return
            seen[node] = 1
            for target in sorted(edges.get(node, ())):
                visit(target)
            seen[node] = 2

        for name in ORDER:
            if seen.get(name, 0) == 0:
                visit(name)

    def test_cli_smoke_is_read_only_and_single_json(self) -> None:
        help_run = run_cli("--help")
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        graph = run_cli("arch-graph", "--json")
        self.assertEqual(graph.returncode, 0, graph.stdout + graph.stderr)
        payload = json.loads(graph.stdout)
        self.assertEqual(payload["schema"], "tower/arch-graph@1")
        self.assertIn("tools/towerctl.py", payload["nodes"])
        state = run_cli("state-verify")
        self.assertEqual(state.returncode, 0, state.stdout + state.stderr)
        self.assertEqual(json.loads(state.stdout)["drift"], [])


if __name__ == "__main__":
    unittest.main()
