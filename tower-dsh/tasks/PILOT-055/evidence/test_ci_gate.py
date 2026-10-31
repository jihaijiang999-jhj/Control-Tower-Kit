"""Server-side gate regression tests (PILOT-012, hardened by PILOT-014).

The tower's verification used to live only in local habits.  ``PILOT-012``
moves it into GitHub Actions and pins the contract down with these tests:
``.github/workflows/tower-gate.yml`` must keep running the four hard gates on
``windows-latest`` / Python 3.12 under ``tower-dsh``, must keep ``status`` as
the last step, and ``.github/CODEOWNERS`` must keep a default owner.

``PILOT-014`` closed the hole that ``continue-on-error`` opened: the status
step used to be swallowed on a non-UTF-8 runner code page, so the gate stayed
green while the command crashed.  ``towerctl`` now pins stdio to UTF-8 and the
workflow must not carry ``continue-on-error`` at all - a real failure turns the
build red.

``PILOT-055`` grows the gate from seven to eight steps: ``shape-check`` runs
after ``campaign-check`` and before ``status``, which stays last.  The step
table and the step count below pin that order.

These tests only read files inside the repository.  They never touch the
network, never call ``gh`` and never depend on the live working-tree state, so
they run unchanged locally and in CI.

Run from the tower root (``tower-dsh``)::

    python -B -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

# <repo>/tower-dsh/tools/tests/test_ci_gate.py -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tower-gate.yml"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"

CHECKOUT = "actions/checkout@v7"
SETUP_PYTHON = "actions/setup-python@v7"
PYTHON_VERSION = 'python-version: "3.12"'
WORKING_DIRECTORY = "working-directory: tower-dsh"
CONTINUE_ON_ERROR = "continue-on-error"

COMMANDS = {
    "unit tests": "python -B -m unittest discover -s tools/tests -v",
    "spec lint": "python tools/towerctl.py spec-lint --strict",
    "spec coverage": "python tools/towerctl.py spec-coverage",
    "verify ledger": "python tools/towerctl.py verify-ledger",
    "arch check": "python tools/towerctl.py arch-check",
    "campaign check": "python tools/towerctl.py campaign-check",
    "shape check": "python tools/towerctl.py shape-check",
    "status": "python tools/towerctl.py status",
}
# PILOT-055: seven gates plus the informational status step.
GATE_STEP_COUNT = 8
HARD_GATE_COMMANDS = [COMMANDS[name] for name in
                      ("unit tests", "spec lint", "spec coverage", "verify ledger",
                       "arch check", "campaign check", "shape check")]

STEP_RE = re.compile(r"(?m)^\s*-\s+name:")


def read_text(path: Path) -> str:
    """Read a repository file, failing loudly when it is missing."""
    if not path.is_file():
        raise AssertionError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def step_blocks(workflow: str) -> list[str]:
    """Split the workflow into per-step chunks, each starting at ``- name:``."""
    starts = [match.start() for match in STEP_RE.finditer(workflow)]
    return [workflow[start:starts[index + 1] if index + 1 < len(starts) else len(workflow)]
            for index, start in enumerate(starts)]


class CiGateWorkflowTestCase(unittest.TestCase):
    """``.github/workflows/tower-gate.yml`` contract."""

    def setUp(self) -> None:
        self.workflow = read_text(WORKFLOW)
        self.steps = step_blocks(self.workflow)

    # -- 1. the file itself ----------------------------------------------
    def test_workflow_exists_and_is_not_empty(self) -> None:
        self.assertTrue(WORKFLOW.is_file(), msg=f"workflow missing at {WORKFLOW}")
        self.assertGreater(len(self.workflow.strip()), 0,
                           msg=f"workflow at {WORKFLOW} is empty")
        self.assertIn("name: tower-gate", self.workflow,
                      msg=f"workflow name missing, head={self.workflow[:200]!r}")

    # -- 2. triggers ------------------------------------------------------
    def test_workflow_triggers_are_all_present(self) -> None:
        for trigger in ("pull_request", "push", "workflow_dispatch"):
            self.assertIn(trigger, self.workflow,
                          msg=f"trigger {trigger!r} missing from workflow:\n{self.workflow}")
        self.assertRegex(
            self.workflow, r"(?m)^\s*branches:\s*\[?\s*main\s*\]?\s*$",
            msg=f"push branch filter for main missing:\n{self.workflow}")

    # -- 3. runtime -------------------------------------------------------
    def test_workflow_runs_on_windows_with_python_312(self) -> None:
        self.assertIn("runs-on: windows-latest", self.workflow,
                      msg=f"windows-latest runner missing:\n{self.workflow}")
        self.assertIn(PYTHON_VERSION, self.workflow,
                      msg=f"python-version 3.12 missing:\n{self.workflow}")
        self.assertNotIn("ubuntu-", self.workflow.lower(),
                         msg=f"workflow must not use an ubuntu runner:\n{self.workflow}")

    # -- 4. the four hard gates plus the informational status ------------
    def test_all_gate_commands_are_present(self) -> None:
        for label, command in COMMANDS.items():
            self.assertIn(command, self.workflow,
                          msg=f"{label} command {command!r} missing from workflow:\n"
                              f"{self.workflow}")

    def test_gate_commands_run_in_order(self) -> None:
        positions = [self.workflow.index(command) for command in COMMANDS.values()]
        self.assertEqual(
            positions, sorted(positions),
            msg="workflow steps are out of order; commands found at "
                f"{dict(zip(COMMANDS, positions))}:\n{self.workflow}")

    def test_gate_runs_eight_steps_with_shape_after_campaign(self) -> None:
        """PILOT-055: seven gates + status = eight steps; shape before status."""
        run_steps = [block for block in self.steps
                     if re.search(r"(?m)^\s+run:\s", block)]
        self.assertEqual(
            len(run_steps), GATE_STEP_COUNT,
            msg=f"expected {GATE_STEP_COUNT} steps that run a command, found "
                f"{len(run_steps)}:\n{self.workflow}")
        self.assertEqual(
            len(COMMANDS), GATE_STEP_COUNT,
            msg=f"COMMANDS must describe all {GATE_STEP_COUNT} steps, "
                f"found {len(COMMANDS)}")

        campaign = self.workflow.index(COMMANDS["campaign check"])
        shape = self.workflow.index(COMMANDS["shape check"])
        status = self.workflow.index(COMMANDS["status"])
        self.assertLess(campaign, shape,
                        msg=f"shape check must follow campaign check:\n{self.workflow}")
        self.assertLess(shape, status,
                        msg=f"shape check must precede status:\n{self.workflow}")

    # -- 5. every command runs inside tower-dsh ---------------------------
    def test_workflow_uses_tower_dsh_working_directory(self) -> None:
        matches = re.findall(r"(?m)^\s*working-directory:\s*(\S+)\s*$", self.workflow)
        self.assertIn("tower-dsh", matches,
                      msg=f"working-directory: tower-dsh missing, found {matches!r}:\n"
                          f"{self.workflow}")

    # -- 6. a failing status fails the build; status stays the last step --
    def test_continue_on_error_is_gone_and_status_is_last(self) -> None:
        self.assertEqual(
            self.workflow.count(CONTINUE_ON_ERROR), 0,
            msg="continue-on-error must not appear anywhere; a crashing gate "
                "step has to turn the build red:\n" + self.workflow)

        status_command = COMMANDS["status"]
        status_blocks = [block for block in self.steps if status_command in block]
        self.assertEqual(len(status_blocks), 1,
                         msg=f"expected one status step, found {len(status_blocks)}:\n"
                             f"{self.workflow}")

        status_block = status_blocks[0]
        self.assertIn(status_command, status_block,
                      msg=f"status step lost its command:\n{status_block}")
        # ``status`` may stay informational in content, but it is still the
        # last thing the gate runs, so its exit code decides the build.
        self.assertEqual(self.steps[-1], status_block,
                         msg=f"status must remain the last step:\n{self.workflow}")

        for command in HARD_GATE_COMMANDS:
            matching = [block for block in self.steps if command in block]
            self.assertEqual(len(matching), 1,
                             msg=f"expected exactly one step running {command!r}, "
                                 f"found {len(matching)}:\n{self.workflow}")
            self.assertNotIn(CONTINUE_ON_ERROR, matching[0],
                             msg=f"hard gate step must fail the build:\n{matching[0]}")

    # -- 7. actions -------------------------------------------------------
    def test_workflow_checks_out_before_setting_up_python(self) -> None:
        for action in (CHECKOUT, SETUP_PYTHON):
            self.assertIn(action, self.workflow,
                          msg=f"{action} missing:\n{self.workflow}")
        self.assertLess(self.workflow.index(CHECKOUT),
                        self.workflow.index(SETUP_PYTHON),
                        msg=f"checkout must precede setup-python:\n{self.workflow}")

    def test_workflow_uses_v7_actions(self) -> None:
        """PILOT-020: the Node.js 20 deprecation notices are gone."""
        self.assertNotIn("actions/checkout@v4", self.workflow,
                         msg=f"stale actions/checkout@v4 still present:\n{self.workflow}")
        self.assertNotIn("actions/setup-python@v5", self.workflow,
                         msg=f"stale actions/setup-python@v5 still present:\n{self.workflow}")
        self.assertEqual(self.workflow.count(CHECKOUT), 1,
                         msg=f"expected exactly one {CHECKOUT}:\n{self.workflow}")
        self.assertEqual(self.workflow.count(SETUP_PYTHON), 1,
                         msg=f"expected exactly one {SETUP_PYTHON}:\n{self.workflow}")

    def test_workflow_requests_read_only_permissions(self) -> None:
        self.assertRegex(
            self.workflow, r"(?m)^permissions:\s*$\n(?:\s+.*\n)*?\s+contents:\s*read\s*$",
            msg=f"permissions: contents: read missing:\n{self.workflow}")


class CodeownersTestCase(unittest.TestCase):
    """``.github/CODEOWNERS`` contract."""

    def test_codeowners_has_default_owner(self) -> None:
        codeowners = read_text(CODEOWNERS)
        self.assertIn("@jihaijiang999-jhj", codeowners,
                      msg=f"default owner missing from CODEOWNERS:\n{codeowners}")
        self.assertRegex(
            codeowners, r"(?m)^\*\s+@jihaijiang999-jhj\s*$",
            msg=f"wildcard ownership line missing/invalid:\n{codeowners}")


if __name__ == "__main__":
    unittest.main()
