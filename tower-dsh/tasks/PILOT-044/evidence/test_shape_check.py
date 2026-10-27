"""Tests for the PILOT-044 shape ratchet and the REVIEW structure block.

Every test builds its own throw-away tower root under the runner's ``TMP``
sandbox and drives the real CLI through ``subprocess``, so exit codes and
written bytes are asserted exactly as a caller observes them::

    python -B tools/run_tests.py

The deliver cases additionally build a real git kit with a ``git worktree``
(same layout as ``test_deliver_scope``): tower root ``<kit>/tower-dsh`` and
task worktree ``<tower>/pilot/worktrees/<ID>``.
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
TCLI = TOOLS_DIR / "towerctl.py"
TASK_ID = "TEST-044"
WORKTREE_REL = f"pilot/worktrees/{TASK_ID}"
FIXED_TIME = "2026-10-19T00:00:00+08:00"
SMALL_TOOL = "def small():\n    return 1\n"
QUESTIONS = (
    "新抽象是否有 ≥2 个使用点？",
    "有无死代码/永久开关？",
    "有无 ≥15 行重复？",
    "测试是否只镜像实现？",
    "新增 TODO 是否有卡号？",
)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **GIT_IDENTITY}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def long_function(name: str, lines: int) -> str:
    """Valid Python defining ``name`` with exactly ``lines`` physical lines."""
    body = [f"    v{index} = {index}" for index in range(lines - 1)]
    return "\n".join([f"def {name}():", *body]) + "\n"


def long_method(class_name: str, method: str, lines: int) -> str:
    """A class holding one method with exactly ``lines`` physical lines."""
    body = [f"        v{index} = {index}" for index in range(lines - 1)]
    return f"class {class_name}:\n    def {method}(self):\n" + "\n".join(body) + "\n"


def nested_long_function(outer: str, inner: str, lines: int) -> str:
    """``outer`` nests ``inner`` with exactly ``lines`` physical lines."""
    body = [f"        v{index} = {index}" for index in range(lines - 1)]
    return f"def {outer}():\n    def {inner}():\n" + "\n".join(body) + "\n"


def write_baseline(path: Path, data) -> None:
    """Write a baseline with LF endings, matching ``.gitattributes``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


class ShapeCheckCase(unittest.TestCase):
    """Standalone ``shape-check`` against a minimal, non-git tower root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-shape-", ignore_cleanup_errors=True)
        self.tower = Path(self._tmp.name) / "tower"
        (self.tower / "tools").mkdir(parents=True)
        self.write_tool("tools/a.py", SMALL_TOOL)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_tool(self, relpath: str, text: str) -> Path:
        path = self.tower / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def freeze(self) -> None:
        cp = run_cli(self.tower, "shape-check", "--write-baseline")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def check(self) -> subprocess.CompletedProcess:
        return run_cli(self.tower, "shape-check")

    # -- 1. new function over the line budget ----------------------------
    def test_new_long_function_fails(self) -> None:
        self.freeze()
        self.write_tool("tools/a.py", SMALL_TOOL + "\n\n" + long_function("long_one", 90))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new function long_one", cp.stdout)

    # -- 2. baselined debt stays green -----------------------------------
    def test_baselined_long_function_passes(self) -> None:
        self.write_tool("tools/a.py", long_function("legacy", 120))
        self.freeze()
        cp = self.check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    # -- 3. ratchet: a baselined function may not grow --------------------
    def test_growing_a_baselined_function_fails(self) -> None:
        self.write_tool("tools/a.py", long_function("legacy", 120))
        self.freeze()
        self.write_tool("tools/a.py", long_function("legacy", 130))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("grew to 130 lines", cp.stdout)

    # -- 4. new file over the file budget --------------------------------
    def test_new_long_file_fails(self) -> None:
        self.freeze()
        self.write_tool("tools/big.py", "".join(
            f"v{index} = {index}\n" for index in range(700)))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new file tools/big.py", cp.stdout)

    # -- 5. new unused import --------------------------------------------
    def test_new_unused_import_fails(self) -> None:
        self.freeze()
        self.write_tool("tools/a.py", "import json\n\n\n" + SMALL_TOOL)
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("unused import json", cp.stdout)

    # -- 6. new duplicated block -----------------------------------------
    def test_new_duplicate_block_fails(self) -> None:
        block = "def dup():\n" + "".join(
            f"    v{index} = {index}\n" for index in range(14))
        self.freeze()
        self.write_tool("tools/a.py", block)
        self.write_tool("tools/b.py", block)
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new duplicated block", cp.stdout)

    # -- 7. baseline writes are byte-identical and key-sorted ------------
    def test_write_baseline_is_byte_identical(self) -> None:
        self.freeze()
        baseline = self.tower / "state" / "SHAPE-BASELINE.json"
        first = baseline.read_bytes()
        self.freeze()
        self.assertEqual(baseline.read_bytes(), first)
        text = first.decode("utf-8")
        self.assertLess(text.index('"duplicate_blocks"'), text.index('"files"'))
        self.assertNotIn("timestamp", text)

    # -- 8. missing baseline is an explicit failure ----------------------
    def test_missing_baseline_fails_with_hint(self) -> None:
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("--write-baseline", cp.stdout)

    # -- 9. methods and nested functions are in scope ---------------------
    def test_new_long_method_fails(self) -> None:
        self.freeze()
        self.write_tool("tools/a.py", long_method("Big", "huge", 91))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new function Big.huge", cp.stdout)

    def test_baselined_long_method_passes(self) -> None:
        self.write_tool("tools/a.py", long_method("Big", "huge", 120))
        self.freeze()
        cp = self.check()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def test_growing_a_baselined_method_fails(self) -> None:
        self.write_tool("tools/a.py", long_method("Big", "huge", 120))
        self.freeze()
        self.write_tool("tools/a.py", long_method("Big", "huge", 130))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("Big.huge", cp.stdout)
        self.assertIn("grew to 130 lines", cp.stdout)

    def test_new_nested_long_function_fails(self) -> None:
        self.freeze()
        self.write_tool("tools/a.py", nested_long_function("outer", "inner", 90))
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new function outer.inner", cp.stdout)

    def test_baseline_uses_qualified_names(self) -> None:
        self.write_tool("tools/a.py", long_method("Big", "huge", 120))
        self.freeze()
        functions = read_json(
            self.tower / "state" / "SHAPE-BASELINE.json")["files"]["tools/a.py"]["functions"]
        self.assertEqual(functions["Big.huge"]["lines"], 120)
        self.assertNotIn("huge", functions)

    # -- 10. a syntax error is a clean exit 2, not a traceback -------------
    def test_syntax_error_fails_cleanly(self) -> None:
        self.freeze()
        self.write_tool("tools/a.py", "def broken(:\n")
        cp = self.check()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("cannot parse tools/a.py", cp.stdout)
        self.assertNotIn("Traceback", cp.stdout + cp.stderr)


class DeliverShapeFixture(unittest.TestCase):
    """Real git kit + task worktree shared by the deliver shape cases."""

    include_tools = True

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-shape-deliver-", ignore_cleanup_errors=True)
        self.kit = Path(self._tmp.name) / "kit"
        self.tower = self.kit / "tower-dsh"
        self.worktree = self.tower / WORKTREE_REL
        self.proof = self.tower / "work" / "proof.txt"
        self.write_source_tree()
        self.init_kit()
        self.add_worktree()
        self.write_tower_state()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_source_tree(self) -> None:
        self.tower.mkdir(parents=True, exist_ok=True)
        (self.kit / ".gitignore").write_text(
            "tower-dsh/pilot/worktrees/\n", encoding="utf-8")
        # Mirror the tower repo: LF checkouts keep the baseline byte-identical.
        (self.kit / ".gitattributes").write_text(
            "* text=auto eol=lf\n", encoding="utf-8")
        (self.tower / "README.md").write_text("base\n", encoding="utf-8")
        (self.tower / "pilot").mkdir(parents=True, exist_ok=True)
        (self.tower / "pilot" / f"{TASK_ID}.spec.json").write_text("{}\n", encoding="utf-8")
        if self.include_tools:
            (self.tower / "tools").mkdir(parents=True, exist_ok=True)
            (self.tower / "tools" / "a.py").write_text(SMALL_TOOL, encoding="utf-8")
        files = {"tools/a.py": {"lines": 2, "functions": {
            "small": {"lines": 2, "branches": 0}}}} if self.include_tools else {}
        write_baseline(self.tower / "state" / "SHAPE-BASELINE.json", {
            "schema": "tower/shape-baseline@1", "files": files,
            "unused_imports": {}, "duplicate_blocks": [],
        })

    def init_kit(self) -> None:
        self.assertEqual(run_git(self.kit, "init").returncode, 0)
        self.assertEqual(
            run_git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        self.assertEqual(run_git(self.kit, "add", "-A").returncode, 0)
        cp = run_git(self.kit, "commit", "-m", "base")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def add_worktree(self) -> None:
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        cp = run_git(self.kit, "worktree", "add", str(self.worktree),
                     "-b", f"pilot/{TASK_ID}")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def allowed_paths(self) -> list[str]:
        paths = [f"{WORKTREE_REL}/tower-dsh/README.md",
                 f"{WORKTREE_REL}/tower-dsh/state/SHAPE-BASELINE.json"]
        if self.include_tools:
            paths.append(f"{WORKTREE_REL}/tower-dsh/tools/a.py")
        return paths

    def record(self) -> dict:
        return {
            "schema": "tower/task@1", "id": TASK_ID, "title": "shape gate deliver",
            "status": "dispatched", "authority": "workspace_write",
            "scope": ["shape gate"], "allowed_paths": self.allowed_paths(),
            "forbidden": ["merge"], "acceptance": ["tests pass"], "depends_on": [],
            "worktree": WORKTREE_REL, "executor": "exec-a",
            "dispatch": {"executor": "exec-a", "worktree": WORKTREE_REL, "at": FIXED_TIME},
            "evidence": [], "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "等待 executor 交付",
        }

    def write_tower_state(self) -> None:
        write_json(self.tower / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-test"}, "owner": {"name": "mac"}})
        write_json(self.tower / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.tower / "tasks" / TASK_ID / "record.json", self.record())
        (self.tower / "ledger").mkdir(parents=True, exist_ok=True)
        (self.tower / "ledger" / "primary.jsonl").touch()
        self.proof.parent.mkdir(parents=True, exist_ok=True)
        self.proof.write_text("proof\n", encoding="utf-8")

    def load_record(self) -> dict:
        return read_json(self.tower / "tasks" / TASK_ID / "record.json")

    def ledger_types(self) -> list[str]:
        path = self.tower / "ledger" / "primary.jsonl"
        rows = [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row["type"] for row in rows]

    def put_worktree(self, relpath: str, text: str) -> None:
        path = self.worktree / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit_worktree(self) -> None:
        add = run_git(self.worktree, "add", "-A")
        self.assertEqual(add.returncode, 0, msg=add.stdout + add.stderr)
        cp = run_git(self.worktree, "commit", "-m", "task change")
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)

    def deliver(self) -> tuple[subprocess.CompletedProcess, dict]:
        cp = run_cli(self.tower, "deliver", "--task", TASK_ID,
                     "--evidence", str(self.proof))
        payload = json.loads(cp.stdout) if cp.stdout.strip() else {}
        return cp, payload


class DeliverShapeGateCase(DeliverShapeFixture):
    """Deliver refuses new shape debt and writes nothing; clean shape passes."""

    def test_new_long_function_blocks_delivery_with_no_writes(self) -> None:
        self.put_worktree("tower-dsh/tools/a.py",
                          SMALL_TOOL + "\n\n" + long_function("long_one", 90))
        self.commit_worktree()
        record_path = self.tower / "tasks" / TASK_ID / "record.json"
        before = record_path.read_bytes()
        evidence = self.tower / "tasks" / TASK_ID / "evidence" / "proof.txt"
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("new function long_one", cp.stdout)
        self.assertTrue(payload.get("shape_checked"))
        self.assertEqual(record_path.read_bytes(), before)
        self.assertFalse(evidence.exists())
        self.assertEqual(self.ledger_types(), [])

    def test_clean_shape_delivers_with_shape_checked(self) -> None:
        self.put_worktree("tower-dsh/tools/a.py",
                          SMALL_TOOL + "\n\ndef helper():\n    return 2\n")
        self.commit_worktree()
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload.get("shape_check"), "checked")
        self.assertTrue(payload.get("shape_checked"))
        self.assertEqual(self.load_record()["status"], "delivered")
        self.assertEqual(self.ledger_types(), ["DELIVER"])


class DeliverShapeTamperedBaselineCase(DeliverShapeFixture):
    """A task cannot widen the gate by editing its own baseline copy."""

    def test_modified_baseline_blocks_delivery(self) -> None:
        self.put_worktree("tower-dsh/tools/a.py",
                          SMALL_TOOL + "\n\n" + long_function("long_one", 90))
        data = read_json(self.tower / "state" / "SHAPE-BASELINE.json")
        data["files"]["tools/a.py"]["functions"]["long_one"] = {
            "lines": 90, "branches": 0}
        write_baseline(self.worktree / "tower-dsh/state/SHAPE-BASELINE.json", data)
        self.commit_worktree()
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("shape baseline modified in worktree", cp.stdout)
        self.assertFalse(payload.get("ok"))


class DeliverShapeDeletedBaselineCase(DeliverShapeFixture):
    """Deleting the worktree baseline is not a way to disable the ratchet."""

    def test_deleted_baseline_blocks_delivery(self) -> None:
        (self.worktree / "tower-dsh/state/SHAPE-BASELINE.json").unlink()
        self.commit_worktree()
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("shape baseline missing in worktree", cp.stdout)
        self.assertFalse(payload.get("ok"))


class DeliverShapeNoTowerBaselineCase(DeliverShapeFixture):
    """A tower without its baseline fails closed instead of skipping."""

    def test_missing_tower_baseline_blocks_delivery(self) -> None:
        (self.tower / "state" / "SHAPE-BASELINE.json").unlink()
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 2, msg=cp.stdout + cp.stderr)
        self.assertIn("shape baseline missing: state/SHAPE-BASELINE.json in the tower root",
                      cp.stdout)
        self.assertFalse(payload.get("ok"))


class DeliverShapeNoToolsCase(DeliverShapeFixture):
    """A worktree without ``tools/*.py``: nothing to scan, so skip."""

    include_tools = False

    def test_missing_tools_dir_skips_shape_check(self) -> None:
        self.put_worktree("tower-dsh/README.md", "base\nchanged\n")
        self.commit_worktree()
        cp, payload = self.deliver()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        self.assertEqual(payload.get("shape_check"), "skipped")
        self.assertFalse(payload.get("shape_checked"))


class CheckbackStructureCase(unittest.TestCase):
    """``checkback --structure`` renders the five questions and records the answer."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-structure-", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1", "role": "primary",
            "primary": {"id": "ctl-test"}, "owner": {"name": "mac"}})
        write_json(self.root / "primary" / "TASK_BOARD.json",
                   {"schema": "tower/task-board@1", "tasks": []})
        write_json(self.root / "tasks" / TASK_ID / "record.json", {
            "schema": "tower/task@1", "id": TASK_ID, "title": "structure block",
            "status": "delivered", "authority": "workspace_write",
            "scope": ["structure"], "allowed_paths": [], "forbidden": ["merge"],
            "acceptance": ["tests pass"], "depends_on": [], "worktree": WORKTREE_REL,
            "executor": "exec-a",
            "dispatch": {"executor": "exec-a", "worktree": WORKTREE_REL, "at": FIXED_TIME},
            "evidence": [], "review": None, "decision": None, "closeout": None,
            "created_at": FIXED_TIME, "updated_at": FIXED_TIME,
            "next": "等待独立 reviewer",
        })
        (self.root / "ledger").mkdir(parents=True, exist_ok=True)
        (self.root / "ledger" / "primary.jsonl").touch()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def checkback(self, *extra: str) -> subprocess.CompletedProcess:
        return run_cli(self.root, "checkback", "--task", TASK_ID,
                       "--reviewer", "rev-a", "--verdict", "PASS", *extra)

    def review_text(self) -> str:
        return (self.root / "tasks" / TASK_ID / "REVIEW.md").read_text(encoding="utf-8")

    def load_record(self) -> dict:
        return read_json(self.root / "tasks" / TASK_ID / "record.json")

    def test_structure_answer_is_recorded_and_rendered(self) -> None:
        answer = "抽象复用两处；无死代码；无重复；测试有边界；TODO 带卡号"
        cp = self.checkback("--structure", answer)
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        review = self.review_text()
        self.assertIn("## Structure review（五问）", review)
        for question in QUESTIONS:
            self.assertIn(question, review)
        self.assertIn(f"reviewer 回答：{answer}", review)
        record = self.load_record()
        self.assertEqual(record["review"]["structure"], answer)
        self.assertEqual(record["status"], "reviewed")

    def test_structure_answer_defaults_to_pending(self) -> None:
        cp = self.checkback()
        self.assertEqual(cp.returncode, 0, msg=cp.stdout + cp.stderr)
        review = self.review_text()
        self.assertIn("## Structure review（五问）", review)
        for question in QUESTIONS:
            self.assertIn(question, review)
        self.assertIn("reviewer 回答：未提供（044 起建议填写，暂不阻塞）", review)
        self.assertEqual(self.load_record()["review"]["structure"], "")


if __name__ == "__main__":
    unittest.main()
