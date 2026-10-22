"""Tests for ``tools/run_tests.py`` — the repo-local TMP sandbox runner.

The runner exists so the tower suite can run inside a restricted DSH sandbox
where the inherited ``%TEMP%`` ACLs break ``tempfile.mkdtemp``.  Every test
here therefore builds its throw-away suite under the repo-local
``.test-tmp`` directory as well: this file must not depend on the host temp
directory, or it would fail in exactly the environment it is testing.

No recursion: the runner is only ever pointed at a tiny external suite with an
explicit pattern, never back at ``tools/tests``.
"""

import os
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

# ``tower-dsh/tools/tests/test_run_tests.py`` -> tower root, repo root, tools/.
TOWER = Path(__file__).resolve().parents[2]
TOOLS = TOWER / "tools"
ROOT = TOWER.parent

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_tests  # noqa: E402  (tools/ is put on sys.path above)


SMOKE_TEST = '''\
import os
import unittest
from pathlib import Path


class TmpSandbox(unittest.TestCase):
    def test_tmp_is_repo_local_and_identical(self):
        names = ("TMPDIR", "TEMP", "TMP")
        values = {name: os.environ.get(name) for name in names}
        self.assertTrue(all(values.values()), values)
        self.assertEqual(len(set(values.values())), 1, values)
        run_dir = Path(values["TMPDIR"]).resolve()
        self.assertTrue(run_dir.is_dir(), run_dir)
        self.assertRegex(run_dir.name, r"^run-\\d{8}-\\d{6}-\\d+$")
        repo = Path(os.environ["TOWER_TEST_REPO"]).resolve()
        self.assertIn(repo, [run_dir, *run_dir.parents], run_dir)
        self.assertTrue(str(run_dir).startswith(str(repo)), run_dir)
'''

FAILING_TEST = '''\
import unittest


class Broken(unittest.TestCase):
    def test_intentional_failure(self):
        self.fail("PILOT-027 intentional failure")
'''

RUN_DIR_RE = re.compile(r"^run-\d{8}-\d{6}-\d+$")


def run_process(argv, cwd, env=None, merge_streams=False, timeout=180):
    """Run *argv* and always return decoded text output.

    ``merge_streams`` sends stderr into stdout, which lets a test prove the
    ``TOWER_TEST_TMP=`` line really is emitted *before* the child's output
    rather than merely existing on a separate stream.
    """
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        child_env.update(env)
    if merge_streams:
        # stderr is folded into stdout so ordering between the two proves the
        # banner was flushed before the child ran.
        capture = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    else:
        capture = {"capture_output": True}
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=child_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **capture,
    )


class RunnerTestBase(unittest.TestCase):
    def make_suite(self):
        """Create a scratch suite directory under the ignored repo-local root."""
        base = TOWER / ".test-tmp"
        scratch = base / f"test-run-tests-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        suite = scratch / "suite"
        suite.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        return scratch, suite

    def write(self, suite, name, source):
        path = suite / name
        path.write_text(source, encoding="utf-8")
        return path

    def run_runner(self, *extra, merge_streams=False):
        return run_process(
            [sys.executable, "-B", str(TOOLS / "run_tests.py"), *extra],
            cwd=TOWER,
            env={"TOWER_TEST_REPO": str(TOWER)},
            merge_streams=merge_streams,
        )

    def parse_tower_tmp(self, stdout):
        lines = [line for line in stdout.splitlines()
                 if line.startswith("TOWER_TEST_TMP=")]
        self.assertEqual(len(lines), 1, stdout)
        return Path(lines[0].split("=", 1)[1])

    def cleanup_run_dir(self, run_dir):
        self.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)


class TmpSandbox(RunnerTestBase):
    def test_runner_sets_repo_local_tmp_env(self):
        """Default tmp-root lives in the tower root; the child sees it as TMP."""
        _, suite = self.make_suite()
        self.write(suite, "test_smoke.py", SMOKE_TEST)

        cp = self.run_runner("--suite", str(suite), "--pattern", "test_smoke.py")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("Ran 1 test", cp.stderr)

        run_dir = self.parse_tower_tmp(cp.stdout)
        self.cleanup_run_dir(run_dir)
        self.assertTrue(run_dir.is_dir(), run_dir)
        self.assertRegex(run_dir.name, RUN_DIR_RE)
        resolved = run_dir.resolve()
        self.assertEqual(resolved.parent, (TOWER / ".test-tmp").resolve())
        self.assertIn(TOWER.resolve(), [resolved, *resolved.parents], resolved)

    def test_external_suite_pattern_selects_exactly_one_test(self):
        """--suite outside tools/tests + --pattern filters to one green test."""
        scratch, suite = self.make_suite()
        self.write(suite, "test_smoke.py", SMOKE_TEST)
        # Must never be imported: the pattern excludes it, and it would fail.
        self.write(suite, "test_other.py", FAILING_TEST)

        cp = self.run_runner(
            "--suite", str(suite),
            "--pattern", "test_smoke.py",
            "--tmp-root", str(scratch / "tmp"),
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("Ran 1 test", cp.stderr)
        self.assertNotIn("FAILED", cp.stderr)
        self.cleanup_run_dir(self.parse_tower_tmp(cp.stdout))

    def test_failing_suite_returns_non_zero(self):
        scratch, suite = self.make_suite()
        self.write(suite, "test_broken.py", FAILING_TEST)

        cp = self.run_runner(
            "--suite", str(suite),
            "--pattern", "test_broken.py",
            "--tmp-root", str(scratch / "tmp"),
        )
        self.assertNotEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("FAILED", cp.stderr)
        # The sandbox is still announced, and still kept, on a red run.
        run_dir = self.parse_tower_tmp(cp.stdout)
        self.cleanup_run_dir(run_dir)
        self.assertTrue(run_dir.is_dir(), run_dir)


class BannerOrdering(RunnerTestBase):
    def test_tower_test_tmp_printed_before_child_output(self):
        scratch, suite = self.make_suite()
        self.write(suite, "test_smoke.py", SMOKE_TEST)

        cp = self.run_runner(
            "--suite", str(suite),
            "--pattern", "test_smoke.py",
            "--tmp-root", str(scratch / "tmp"),
            merge_streams=True,
        )
        self.assertEqual(cp.returncode, 0, cp.stdout)
        lines = [line for line in cp.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, cp.stdout)
        self.assertTrue(lines[0].startswith("TOWER_TEST_TMP="), cp.stdout)
        self.assertTrue(any("Ran 1 test" in line for line in lines[1:]), cp.stdout)
        run_dir = self.parse_tower_tmp(cp.stdout)
        self.cleanup_run_dir(run_dir)
        # The runner must not delete the sandbox it just advertised.
        self.assertTrue(run_dir.is_dir(), run_dir)


class GitIgnore(RunnerTestBase):
    def test_test_tmp_is_gitignored(self):
        probe = TOWER / ".test-tmp" / f"probe-{uuid.uuid4().hex[:8]}.txt"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ignored\n", encoding="utf-8")
        self.addCleanup(probe.unlink)

        rel_probe = probe.relative_to(ROOT).as_posix()
        checked = run_process(
            ["git", "-C", str(ROOT), "check-ignore", "-v", rel_probe], cwd=ROOT)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn(".test-tmp", checked.stdout)

        status = run_process(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "--untracked-files=all"], cwd=ROOT)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertNotIn(".test-tmp", status.stdout)


class Defaults(RunnerTestBase):
    def test_default_suite_resolves_inside_tower_root(self):
        tower = run_tests.TOWER_ROOT.resolve()
        default_suite = (run_tests.TOWER_ROOT / run_tests.DEFAULT_SUITE).resolve()
        self.assertEqual(default_suite, (TOWER / "tools" / "tests").resolve())
        self.assertIn(tower, [default_suite, *default_suite.parents], default_suite)
        self.assertEqual(run_tests.DEFAULT_PATTERN, "test*.py")
        default_tmp = Path(run_tests.DEFAULT_TMP_ROOT).resolve()
        self.assertEqual(default_tmp, (TOWER / ".test-tmp").resolve())
        self.assertIn(tower, [default_tmp, *default_tmp.parents], default_tmp)


if __name__ == "__main__":
    unittest.main()
