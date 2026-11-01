# PILOT-060 — 信封 MERGE_START 允许 MERGING 重试

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-060`

## Scope

- tools/tower_ledger_replay.py：ENVELOPE_TRANSITIONS['MERGE_START'] 加 'MERGING'（仅重试语义）
- 新增 tools/tests/test_envelope_retry.py：WAITING→MERGING→MERGING 合法；CORRECTION→MERGING 合法；DRAFT/MERGED 仍拒；重复 MERGE_START 不报 illegal_transition
- 真实塔 056 的 state-verify drift 归零；其它信封事件不变
- 不改 merge/queue/envelope-new 行为；不放宽其它转移

## Allowed paths

- `pilot/worktrees/PILOT-060/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-060/tower-dsh/tools/tests/test_envelope_retry.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- allowing MERGE_START from DRAFT/MERGED/POST_MERGE_VERIFIED
- weakening other envelope transitions

## Acceptance

- cd pilot/worktrees/PILOT-060/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 683 + 新增用例数（main 基线 683）
- MERGE_START 源状态 = {WAITING, CORRECTION_REQUIRED, MERGING}；DRAFT/MERGED/POST_MERGE_VERIFIED 仍拒
- 真实塔 state-verify 0（056 的重复 MERGE_START 合法），59/59；profile 11/0；arch gates 18
- 其它 055 re-dispatch/058 review/059 acceptance 测试不回归
- git -C pilot/worktrees/PILOT-060 diff --name-only main..HEAD 恰 2 个 allowed_paths
