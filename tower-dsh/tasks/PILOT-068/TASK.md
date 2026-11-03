# PILOT-068 — base-sync 白名单补 merge-envelopes/**；068 自身审计 admin

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-068`

## Scope

- base-sync state-only 白名单增加 `merge-envelopes/**`（tower 前缀内）
- 其余分类不变：tools/arch/EVENT_CATALOG/pilot/根 md 仍是 code/docs，带 flag 也拒绝
- test_base_sync：base 仅 merge-envelopes/ENV-PILOT-068.json + state → flag 0、admin 审计；仅 code 仍 2；无 flag 2
- 068 自身 base-side envelope；合并用 `--allow-state-ahead`，不直接 gh admin
- 合并后审计断言：merge ledger/envelope/MERGE payload 均有 base_sync=state-only、base_ahead_paths 含 merge-envelopes、admin=true
- 不改 065/066/067 历史

## Allowed paths

- `pilot/worktrees/PILOT-068/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-068/tower-dsh/tools/tests/test_base_sync.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- direct gh admin bypass
- allowing tools/arch/docs in state-only
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-068/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 744 + 新增用例数（main 基线 744）
- base 仅 merge-envelopes/ENV-PILOT-068.json + state + flag → merge 0，admin argv，审计字段齐全
- base 仅 code/docs + flag → exit 2；state-only 无 flag → exit 2
- 068 自身 merge --mode pr --allow-state-ahead 成功；不出现直接 gh admin 调用
- 068 合并审计：base_sync=state-only、base_ahead_paths 含 merge-envelopes、admin=true
- 真实塔 68/67 drift []；arch 18；profile 11/0；shape 0
