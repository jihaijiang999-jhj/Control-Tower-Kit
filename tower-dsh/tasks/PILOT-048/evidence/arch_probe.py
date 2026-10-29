"""PILOT-048 read-only probe: arch-check / arch-graph + control-plane hashes.

Run from the tower root:

    python -B ../../scratch/arch_probe.py

Exits 0 only when both commands are green, ``arch-graph --json`` is byte-stable
across two runs and the primary/supervision/ledger/tasks trees are unchanged.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

TOWER = Path(__file__).resolve().parents[1] / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
TREE_DIRS = ("primary", "supervision", "ledger", "tasks")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), *args],
        cwd=str(TOWER), capture_output=True, text=True, encoding="utf-8",
    )


def digest() -> str:
    sha = hashlib.sha256()
    for name in TREE_DIRS:
        for path in sorted((TOWER / name).rglob("*")):
            if path.is_file():
                sha.update(path.relative_to(TOWER).as_posix().encode())
                sha.update(path.read_bytes())
    return sha.hexdigest()


def main() -> int:
    before = digest()
    check = run("arch-check")
    graph_one = run("arch-graph", "--json")
    graph_two = run("arch-graph", "--json")
    after = digest()
    failures: list[str] = []

    print(f"arch-check exit={check.returncode}")
    if check.returncode != 0:
        failures.append("arch-check is not green")
        print(check.stdout)
    else:
        payload = json.loads(check.stdout)
        print("arch-check ok=", payload["ok"])
        print("arch-check counts=", json.dumps(payload["counts"], sort_keys=True))

    print(f"arch-graph exit={graph_one.returncode}/{graph_two.returncode}")
    if graph_one.returncode != 0 or graph_two.returncode != 0:
        failures.append("arch-graph is not green")
    else:
        graph = json.loads(graph_one.stdout)
        print("schema=", graph["schema"])
        print("nodes=", len(graph["nodes"]), "edges=", len(graph["edges"]))
        print("byte-identical=", graph_one.stdout == graph_two.stdout)
        if graph_one.stdout != graph_two.stdout:
            failures.append("arch-graph is not byte-stable")

    print("control-plane digest before=", before)
    print("control-plane digest after =", after)
    print("read-only=", before == after)
    if before != after:
        failures.append("arch commands wrote to the control plane")

    print("RESULT=", "PASS" if not failures else "FAIL")
    for failure in failures:
        print("FAILURE:", failure)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
