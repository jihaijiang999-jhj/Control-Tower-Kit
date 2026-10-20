"""Non-UTF-8 console output tests (PILOT-014).

GitHub's ``windows-latest`` runner does not run Python under UTF-8: the console
code page is cp1252, so ``PYTHONIOENCODING`` falls back to a charmap codec and
``status`` crashed with ``UnicodeEncodeError`` as soon as a task title was not
ASCII.  ``PILOT-012``'s ``continue-on-error`` hid that crash, which is why
``PILOT-014`` both pins ``towerctl``'s stdio to UTF-8 and removes the escape
hatch from the workflow.

These tests reproduce the runner's code page deterministically.  They build a
throw-away tower inside a throw-away git repository under ``tempfile``, set
``PYTHONIOENCODING=cp1252`` for the child (and drop ``PYTHONUTF8`` so the
interpreter cannot silently switch back), capture stdout as **bytes**, and
require the bytes to decode as UTF-8 JSON containing the non-ASCII title.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
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

# Deliberately non-ASCII: cp1252 cannot represent any of these characters.
CHINESE_TITLE = "中文任务标题"

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Tower Test",
    "GIT_AUTHOR_EMAIL": "tower@example.invalid",
    "GIT_COMMITTER_NAME": "Tower Test",
    "GIT_COMMITTER_EMAIL": "tower@example.invalid",
}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class OutputEncodingTestCase(unittest.TestCase):
    """Fixture: ``<tmp>/kit`` is a git repo and ``<tmp>/kit/tower-dsh`` a tower."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="towerctl-encoding-", ignore_cleanup_errors=True)
        self.base = Path(self._tmp.name)
        self.kit = self.base / "kit"
        self.root = self.kit / "tower-dsh"

        for name in ("primary", "supervision/reviews", "supervision/outbox",
                     "ledger", "handoffs", "shared"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

        for name in ("TOWER.md", "AGENTS.md", "START-HERE.md"):
            (self.root / name).write_text(f"# {name}\n", encoding="utf-8")
        write_json(self.root / "shared" / "PROJECT_PROFILE.json",
                   {"schema": "tower/project-profile@1", "name": "tower-编码"})
        write_json(self.root / "shared" / "AUTHORITY_MODEL.json",
                   {"schema": "tower/authority-model@1", "levels": []})
        write_json(self.root / "primary" / "CURRENT_STATE.json", {
            "schema": "tower/current-state@1",
            "tower_id": "tower-encoding",
            "role": "primary",
            "phase": "TEST",
            "primary": {"id": "ctl-encoding"},
            "owner": {"name": "mac"},
            "next_action": CHINESE_TITLE,
        })
        write_json(self.root / "primary" / "TASK_BOARD.json", {
            "schema": "tower/task-board@1",
            "tasks": [{
                "schema": "tower/task@1",
                "id": "TASK-ENCODING",
                "title": CHINESE_TITLE,
                "status": "ready",
            }],
        })
        write_json(self.root / "supervision" / "CURRENT_STATE.json", {
            "schema": "tower/supervision-state@1",
            "role": "supervision",
            "phase": "TEST",
            "supervisor": {"id": "sup-test"},
        })
        for name in ("supervision/reviews", "supervision/outbox", "handoffs"):
            (self.root / name / ".gitkeep").write_text("", encoding="utf-8")
        (self.root / "ledger" / "primary.jsonl").write_text("", encoding="utf-8")

        self.kit.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.git(self.kit, "init").returncode, 0)
        self.assertEqual(
            self.git(self.kit, "symbolic-ref", "HEAD", "refs/heads/main").returncode, 0)
        self.assertEqual(self.git(self.kit, "add", "-A").returncode, 0)
        commit = self.git(self.kit, "-c", "commit.gpgsign=false",
                          "commit", "-m", "initial tower state")
        self.assertEqual(commit.returncode, 0, msg=commit.stdout + commit.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- fixture helpers --------------------------------------------------
    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, env=env,
        )

    def child_env(self) -> dict:
        """Environment that mimics a non-UTF-8 Windows console."""
        env = dict(os.environ)
        env.update(GIT_IDENTITY)
        # Never let the parent's UTF-8 mode leak into the child.
        env.pop("PYTHONUTF8", None)
        env.pop("PYTHONLEGACYWINDOWSSTDIO", None)
        env["PYTHONIOENCODING"] = "cp1252"
        return env

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        """Run towerctl capturing raw bytes, exactly like CI captures a pipe."""
        return subprocess.run(
            [sys.executable, "-B", str(TCLI), "--root", str(self.root), *args],
            capture_output=True, env=self.child_env(),
        )

    def assert_utf8_json(self, cp: subprocess.CompletedProcess) -> dict:
        self.assertEqual(
            cp.returncode, 0,
            msg=("command failed under PYTHONIOENCODING=cp1252\n"
                 f"stdout={cp.stdout!r}\nstderr={cp.stderr!r}"))
        self.assertNotIn(b"UnicodeEncodeError", cp.stderr,
                         msg=f"child crashed encoding its output:\n{cp.stderr!r}")
        try:
            text = cp.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - failure path
            self.fail(f"stdout is not valid UTF-8 ({exc}): {cp.stdout!r}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:  # pragma: no cover - failure path
            self.fail(f"stdout is not valid JSON ({exc}): {text!r}")
        self.assertIsInstance(data, dict)
        return data

    # -- 0. the fixture really is a non-UTF-8 child ----------------------
    def test_environment_forces_cp1252_stdio(self) -> None:
        """Guards the other tests: without this they could pass vacuously."""
        cp = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
            capture_output=True, env=self.child_env(),
        )
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        self.assertEqual(cp.stdout.strip(), b"cp1252")

    # -- 1. status does not crash on the runner's code page --------------
    def test_status_survives_cp1252_console(self) -> None:
        cp = self.run_cli("status")
        data = self.assert_utf8_json(cp)
        self.assertIs(data["ok"], True)
        self.assertEqual(data["tower"], "tower-encoding")

    # -- 2. startup does not crash on the runner's code page -------------
    def test_startup_survives_cp1252_console(self) -> None:
        cp = self.run_cli("startup")
        data = self.assert_utf8_json(cp)
        self.assertIs(data["ok"], True)
        self.assertEqual(data["tower_id"], "tower-encoding")
        self.assertEqual(data["tasks"], 1)

    # -- 3. the bytes are UTF-8 JSON carrying the Chinese title ----------
    def test_status_output_is_utf8_json_with_chinese_title(self) -> None:
        cp = self.run_cli("status")
        data = self.assert_utf8_json(cp)
        rendered = json.dumps(data, ensure_ascii=False)
        self.assertIn(CHINESE_TITLE, rendered,
                      msg=f"Chinese title missing from status output:\n{rendered}")
        # A cp1252 payload would have used escapes or failed outright; the raw
        # bytes must also carry the UTF-8 encoding of the title.
        self.assertIn(CHINESE_TITLE.encode("utf-8"), cp.stdout)

    def test_startup_output_is_utf8_json_with_chinese_title(self) -> None:
        cp = self.run_cli("startup")
        data = self.assert_utf8_json(cp)
        self.assertIn(CHINESE_TITLE, json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
