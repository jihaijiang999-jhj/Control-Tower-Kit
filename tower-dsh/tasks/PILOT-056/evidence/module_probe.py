"""PILOT-056 module probe: line budgets, 4-layer DAG, CLI smoke."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

TOWER = Path(r"C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh\pilot\worktrees\PILOT-056\tower-dsh")
TOOLS = TOWER / "tools"
TCLI = TOOLS / "towerctl.py"

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
ORDER = [
    "tower_common", "tower_ledger", "tower_ledger_replay",
    "tower_task", "tower_command", "tower_authority", "tower_authority_cmd",
    "tower_profile", "tower_shape", "tower_campaign", "tower_dispatch",
    "tower_delivery", "tower_envelope", "tower_handoff", "tower_merge",
    "tower_arch", "tower_arch_check", "tower_post_merge",
    "tower_views", "tower_lookup", "tower_status", "tower_state_verify",
    "tower_cli",
]
RANK = {"base": 0, "domain": 1, "compose": 2, "entry": 3}
POS = {name: index for index, name in enumerate(ORDER)}


def lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return {name for name in names if name.startswith("tower_")}


print("== line budgets (limit: entry <3000, module <600) ==")
print(f"{'file':24s} {'layer':8s} {'lines':>5s}  ok")
counts = {}
for name in ORDER:
    path = TOOLS / f"{name}.py"
    counts[name] = lines(path)
    limit = 3000 if name == "tower_cli" else 600
    print(f"{name + '.py':24s} {LAYERS[name]:8s} {counts[name]:5d}  {counts[name] < limit}")
print(f"{'towerctl.py':24s} {'entry':8s} {lines(TCLI):5d}  {lines(TCLI) < 3000}")
print("modules:", len(ORDER), " total lines:", sum(counts.values()) + lines(TCLI))

print("\n== import DAG (one-way 4 layers, no cycles) ==")
edges = {}
problems = []
for name in ORDER:
    targets = imports(TOOLS / f"{name}.py")
    edges[name] = targets
    for target in sorted(targets):
        if target not in LAYERS:
            problems.append(f"{name} imports unknown {target}")
            continue
        if RANK[LAYERS[target]] > RANK[LAYERS[name]]:
            problems.append(f"UPWARD {name} -> {target}")
        elif LAYERS[target] == LAYERS[name] and POS[target] >= POS[name]:
            problems.append(f"SAME-LAYER-BACKWARD {name} -> {target}")
        print(f"  {name:22s} -> {target:22s} {LAYERS[target]}")
seen = {}


def visit(node: str, stack: list[str]) -> None:
    if seen.get(node) == 1:
        problems.append("CYCLE " + " -> ".join(stack + [node]))
        return
    if seen.get(node) == 2:
        return
    seen[node] = 1
    for target in sorted(edges.get(node, ())):
        visit(target, stack + [node])
    seen[node] = 2


for name in ORDER:
    if seen.get(name, 0) == 0:
        visit(name, [])
print("cycles/backward problems:", problems or "none")

print("\n== CLI smoke (read-only) ==")
sys.path.insert(0, str(TOOLS))
import towerctl  # noqa: E402

commands = towerctl.cli_commands()
print("registered subcommands:", len(commands))
for args in (["--help"], ["shape-check"], ["arch-check"], ["profile-check"],
             ["state-verify"], ["authority-check"], ["campaign-check"],
             ["spec-lint", "--strict"], ["verify-ledger"], ["wiring"],
             ["startup"], ["where", "--json"], ["brief"],
             ["arch-graph", "--json"]):
    cp = subprocess.run([sys.executable, "-B", str(TCLI), *args],
                        cwd=str(TOWER), capture_output=True, text=True,
                        encoding="utf-8")
    print(f"  towerctl {' '.join(args):22s} exit={cp.returncode}")
    if args not in (["--help"], ["brief"]) and cp.returncode == 0:
        json.loads(cp.stdout)
print("probe: OK" if not problems else "probe: FAILED")
