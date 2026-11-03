# PILOT-067 — base 同步策略：state-only 可审计 admin，code 变更必须 rebase + 重审

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-067`

## Scope

- merge --mode pr 前检测 origin/main 是否含 HEAD 未包含的提交；base 前进才进入策略
- base-only 变更分类：仅 `ledger/**`、`primary/**`、`supervision/**`、`tasks/**`、`state/**` 视为 state-only；任何 `tools/**`、`arch/**`、`EVENT_CATALOG.json`、`pilot/**`、`*.md` 根文档视为 code/docs
- state-only + `--allow-state-ahead`：允许 `gh pr merge --admin --match-head-commit <PR head>`，写审计（merge ledger/ envelope payload: base_sync=state-only, base_ahead_paths, admin=true）；无 flag exit 2
- code/docs 变更：exit 2，要求 `git rebase origin/main`、更新 envelope implementation_head_sha + review head + 重新 review；绝不允许 admin
- 测试：state-only+flag 0 且审计；state-only 无 flag 2；code 变更 2；base 未前进正常 0；review head 仍绑 implementation
- 不改 local merge；不放宽 review/acceptance

## Allowed paths

- `pilot/worktrees/PILOT-067/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-067/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-067/tower-dsh/tools/tests/test_base_sync.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- automatic admin without flag
- admin on code/docs base changes
- weakening review head/base

## Acceptance

- cd pilot/worktrees/PILOT-067/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 736 + 新增用例数（main 基线 736）
- base 未前进：正常 merge 0，不写 admin 审计
- base 仅 state 前进 + --allow-state-ahead：merge 0，admin=true 审计含 base_ahead_paths
- base 仅 state 前进无 flag：exit 2；base 含 code/docs：exit 2，提示 rebase/re-review
- review head 仍 == envelope implementation；rebase 后旧 review 必须 stale
- 067 自身 merge --mode pr 成功；真实塔 67/66 drift []；arch 18；profile 11/0；shape 0
