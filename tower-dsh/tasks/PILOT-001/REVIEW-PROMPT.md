# PILOT-001 — Independent Reviewer Prompt

You are the independent reviewer for tower-dsh task `PILOT-001`. You are NOT the executor and must not modify the worktree.

## Context

- Worktree: `C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh\pilot\worktrees\PILOT-001`
- Task card: `C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh\tasks\PILOT-001\TASK.md`
- Allowed files: `ledger_chain.py`, `tests/test_ledger_chain.py`, `README.md`
- Forbidden: edits, git commit, merge, network, production access.

## Read-only rules

- Do NOT create, edit, delete, or `git commit` anything in the worktree.
- Run Python with `-B` and set `PYTHONDONTWRITEBYTECODE=1` to avoid `__pycache__`.
- Put any temporary test script under `%TEMP%`, not in the worktree.
- You may read files and run commands.

## Verify

1. Run the suite:
   `python -B -m unittest discover -s tests -v`
2. Check `append_event`:
   - seq starts at 1, increments by 1;
   - first prev_hash is `"GENESIS"`;
   - later prev_hash equals previous hash;
   - hash is SHA-256 over canonical JSON of seq/at/type/payload/prev_hash.
3. Check `verify_chain`:
   - valid chain returns `ok=True`, count correct;
   - tampered payload fails;
   - tampered prev_hash fails;
   - tampered seq fails;
   - tampered hash fails;
   - invalid JSON line fails.
4. Independent tamper probe (in `%TEMP%`, importing the worktree module):
   - build a 3-event chain;
   - mutate one field in a copy;
   - assert `verify_chain` returns `ok=False` with a named error.
5. Compute SHA-256 of the three allowed files.
6. Run `git status --short` and report any file outside the allowed set.

## Return

- Verdict: `PASS` or `FAIL`.
- Per-acceptance checklist (PASS/FAIL + evidence).
- Full test output (or key lines + exit code).
- Independent tamper probe output.
- SHA-256 for the three files.
- Any findings, caveats, or deviations.

Do not accept on the basis of the executor's summary alone. Run the evidence yourself.
