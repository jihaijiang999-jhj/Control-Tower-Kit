# Reproducing the tower test suite

Clean-environment rerun checklist for `tower-dsh`.  `tools/run_tests.py` points
`TMP`, `TEMP` and `TMPDIR` at a repository-local sandbox, so the suite also
runs in a restricted DSH sandbox where the inherited `%TEMP%` directory carries
ACLs that break `tempfile.mkdtemp`.

## 1. Prerequisites

- Python 3.12 (`python -V` → `Python 3.12.x`; last verified on 3.12.10).
- Git (only used by the `.test-tmp` ignore test).
- No network, no credentials, no `towerctl` state change: this is read-only
  apart from the ignored `.test-tmp` sandbox.

## 2. Exact command

```sh
cd tower-dsh
python -B tools/run_tests.py
```

- `cwd` must be the tower root (the directory containing `tools/`).
- Defaults: suite `tools/tests`, pattern `test*.py`, tmp-root
  `<tower>/.test-tmp`.
- The exit code is the child's exit code; `0` means green.

Optional flags:

```sh
python -B tools/run_tests.py --suite tools/tests --pattern "test*.py"
python -B tools/run_tests.py --suite <dir> --pattern test_smoke.py --tmp-root <dir>
```

Backward-compatible direct discovery (does **not** redirect temp; it uses the
host `%TEMP%`/`$TMPDIR` and can fail under a restricted sandbox):

```sh
cd tower-dsh
python -B -m unittest discover -s tools/tests -v
```

## 3. Where TMP lives

The first stdout line names the sandbox:

```text
TOWER_TEST_TMP=<tower>/.test-tmp/run-YYYYmmdd-HHMMSS-<pid>
```

- The same directory is exported as `TMPDIR`, `TEMP` and `TMP` for the child
  process; the rest of the environment is inherited unchanged.
- The run directory is **never deleted** by the runner (a red run stays
  debuggable).  It is gitignored via `tower-dsh/.test-tmp/`.
- Each run directory carries a one-line `.git` gitfile that points at a
  missing git dir.  The sandbox lives inside the verified repository, but the
  fixtures assume temp directories are outside any repository; the gitfile
  restores the old `not a git repository` result.  Fixtures that run `git init`
  below the run directory are unaffected (the nearest `.git` wins).
- On Windows the runner also exports `core.longpaths=true` through
  `GIT_CONFIG_*` for its descendants: fixture repositories live deep under the
  worktree and would otherwise hit `MAX_PATH` (`Filename too long`).
- A relative `--tmp-root` resolves against the tower root, not the caller's
  current directory.

## 4. Expected result

`Ran 246+ tests` followed by `OK`, exit code `0`.  On this branch (PILOT-027
adds six runner tests) the count is 252:

```text
TOWER_TEST_TMP=.../.test-tmp/run-20261022-190837-4242
...
Ran 252 tests in 90.123s

OK (skipped=1)
```

One skip is expected environment gating (it is reported, not silent).  Any
failure or error is not expected.

## 5. What to preserve on failure

- Full stdout **and** stderr, including the `TOWER_TEST_TMP=` line.
- The run directory it names — keep it until the failure is captured and
  copied into evidence.
- `python -V`, `git status --short`, and the failing test's name/traceback.

## 6. Cleanup

From the **repository root** (one level above `tower-dsh`):

```sh
python -c "import shutil; shutil.rmtree('tower-dsh/.test-tmp', ignore_errors=True)"
```

PowerShell: `Remove-Item -Recurse -Force tower-dsh\.test-tmp`
POSIX: `rm -rf tower-dsh/.test-tmp`

Cleanup is safe at any time: nothing under `.test-tmp` is tracked or needed
after the evidence has been captured.
