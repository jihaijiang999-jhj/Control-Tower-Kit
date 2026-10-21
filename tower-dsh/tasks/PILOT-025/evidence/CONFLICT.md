# PILOT-025 v2 decision trace

The fifth post-merge check changes `MERGE.md` from
`Post-merge checks: 4/4` to `5/5`. The base-main test
`tower-dsh/tools/tests/test_hardening2.py:508` hard-coded `4/4`, so the
original v1 scope (two allowed files) could not both satisfy "full suite
green" and "only two files changed".

Resolution (parent/Primary, PILOT-025 v2): `allowed_paths`/scope expanded to
three files, and `test_hardening2.py:508` updated `4/4` -> `5/5` — that single
assertion only tracks the number of checks, no coverage weakened. v1 task card
and spec are archived as `tasks/PILOT-025-VOID/` and
`pilot/PILOT-025.spec.v1.json`.

Result: full suite `Ran 241 tests ... OK (skipped=1)`; exactly three files in
`git diff --name-only main..HEAD`.
