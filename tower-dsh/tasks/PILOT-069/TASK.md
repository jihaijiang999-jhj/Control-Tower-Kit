# PILOT-069 — base-ahead 用 merge-base..origin/main；069 自身审计 admin

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-069`

## Scope

- base_ahead_paths：mb = merge-base HEAD origin/main；changed = git diff --name-only mb..origin/main；mb == origin/main 即未前进
- 分类逻辑不变：state-only + merge-envelopes/** 可 flag admin；tools/arch/EVENT_CATALOG/pilot/根 md 仍 code
- test_base_sync：分支自带 code + base 仅 state/envelope → flag 0、admin 审计、base_ahead_paths 不含分支 code；base 真新增 tools/ → 2；base 未前进；无 flag；review 仍绑 impl
- 069 自身 base-side envelope；merge 必须 --allow-state-ahead；读取 envelope/merge ledger/MERGE payload 的 base_sync=state-only、base_ahead_paths、admin=true
- 不直接 gh admin；不改 065/066/067/068 历史

## Allowed paths

- `pilot/worktrees/PILOT-069/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-069/tower-dsh/tools/tests/test_base_sync.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- direct gh admin bypass
- using HEAD..origin/main for base-ahead
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-069/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 747 + 新增用例数（main 基线 747）
- 分支自带 code + base 仅 state/envelope + flag → merge 0，admin argv，base_ahead_paths 不含分支 code
- base 真新增 tools/ + flag → exit 2；state-only 无 flag → 2；base 未前进正常
- 069 自身 merge --mode pr --allow-state-ahead 成功；无直接 gh admin
- 069 审计：base_sync=state-only、base_ahead_paths 仅 envelope/state、admin=true
- 真实塔 69/68 drift []；arch 18；profile 11/0；shape 0
