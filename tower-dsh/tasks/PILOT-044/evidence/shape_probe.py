"""Hand probe for the PILOT-044 shape ratchet (new-debt-only gate).

Builds throw-away tower roots under the host temp directory, freezes a
baseline with the real CLI, mutates the code and prints the verdict for each
case.  Run from the PILOT-044 worktree:

    python -B scratch/shape_probe.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

TCLI = Path(__file__).resolve().parents[1] / "tower-dsh" / "tools" / "towerctl.py"
SMALL = "def small():\n    return 1\n"


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def long_function(name: str, lines: int) -> str:
    body = [f"    v{index} = {index}" for index in range(lines - 1)]
    return "\n".join([f"def {name}():", *body]) + "\n"


def new_tower(base: Path) -> Path:
    root = base / "tower"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "a.py").write_text(SMALL, encoding="utf-8")
    return root


def verdict(root: Path) -> str:
    cp = run(root, "shape-check")
    detail = next((line.strip().strip('",') for line in cp.stdout.splitlines()
                   if "shape:" in line), "")
    return f"exit={cp.returncode}" + (f"  {detail}" if detail else "")


def case(name: str, prepare, mutate) -> None:
    with tempfile.TemporaryDirectory(
            prefix="shape-probe-", ignore_cleanup_errors=True) as tmp:
        root = new_tower(Path(tmp))
        prepare(root)
        if prepare is not None:
            frozen = run(root, "shape-check", "--write-baseline")
            if frozen.returncode != 0:
                print(f"{name}: BASELINE FAILED {frozen.stdout}")
                return
        mutate(root)
        print(f"{name}: {verdict(root)}")


def main() -> None:
    def noop(root: Path) -> None:
        pass

    case("clean-baselined-tower", noop, noop)
    case("new-90-line-function", noop,
         lambda root: (root / "tools" / "a.py").write_text(
             SMALL + "\n\n" + long_function("long_one", 90), encoding="utf-8"))
    case("baselined-120-line-function", lambda root: (root / "tools" / "a.py").write_text(
        long_function("legacy", 120), encoding="utf-8"), noop)
    case("baselined-120-grows-to-130",
         lambda root: (root / "tools" / "a.py").write_text(
             long_function("legacy", 120), encoding="utf-8"),
         lambda root: (root / "tools" / "a.py").write_text(
             long_function("legacy", 130), encoding="utf-8"))
    case("new-700-line-file", noop,
         lambda root: (root / "tools" / "big.py").write_text(
             "".join(f"v{i} = {i}\n" for i in range(700)), encoding="utf-8"))
    case("new-unused-import", noop,
         lambda root: (root / "tools" / "a.py").write_text(
             "import json\n\n\n" + SMALL, encoding="utf-8"))

    def duplicate(root: Path) -> None:
        block = "def dup():\n" + "".join(f"    v{i} = {i}\n" for i in range(14))
        (root / "tools" / "a.py").write_text(block, encoding="utf-8")
        (root / "tools" / "b.py").write_text(block, encoding="utf-8")

    case("new-15-line-duplicate", noop, duplicate)

    with tempfile.TemporaryDirectory(
            prefix="shape-probe-", ignore_cleanup_errors=True) as tmp:
        root = new_tower(Path(tmp))
        cp = run(root, "shape-check")
        hint = next((line.strip() for line in cp.stdout.splitlines()
                     if "--write-baseline" in line), "")
        print(f"missing-baseline: exit={cp.returncode}  {hint}")

    with tempfile.TemporaryDirectory(
            prefix="shape-probe-", ignore_cleanup_errors=True) as tmp:
        root = new_tower(Path(tmp))
        first = run(root, "shape-check", "--write-baseline")
        baseline = root / "state" / "SHAPE-BASELINE.json"
        digest_a = baseline.read_bytes()
        again = run(root, "shape-check", "--write-baseline")
        digest_b = baseline.read_bytes()
        print(f"write-baseline: first={first.returncode} second={again.returncode} "
              f"bytes={len(digest_a)} identical={digest_a == digest_b}")


if __name__ == "__main__":
    main()
