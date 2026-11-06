# PILOT-076 — owner GitHub 批准 + REVIEW/CHECKBACK 对账 + 删除硬编码 actor

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-076`

## Scope

- shared/AUTHORITY_MODEL.json：owner.github_login 与 primary.github_login 必填且不同；authority-check 校验
- merge --mode pr：gh pr view reviews/author；要求 owner login 的 APPROVED review，且 approver != primary.github_login、approver != PR author；缺失/同 primary/自批 exit 2 零 MERGE
- accept/post-merge：删除 actor:"owner" 硬编码；写 --by（默认 authority owner.name）与 git author 一致性；不匹配拒绝
- state-verify：REVIEW.json 的 reviewer/verdict/head/base 必须等于最后一条 CHECKBACK 事件；不匹配/缺失 → review_unbacked drift
- merge-check：以最后一条 CHECKBACK 为准，REVIEW.json 只作快照；stale 仍拒
- 076 自身标记 legacy bootstrap（owner approval 未启用前）；077+ 强制；测试覆盖缺失/同 primary/自批/对账 drift
- 不改 058 的 PASS/stale 语义、059 acceptance、070/073/074/075 行为

## Allowed paths

- `pilot/worktrees/PILOT-076/tower-dsh/shared/AUTHORITY_MODEL.json`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tower_post_merge.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tower_state_verify.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tests/test_owner_approval.py`
- `pilot/worktrees/PILOT-076/tower-dsh/tools/tests/test_review_checkback.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- same GitHub login for owner and primary
- self-approval
- keeping actor:"owner" default
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-076/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 811 + 新增用例数（main 基线 811）
- owner/primary github_login 缺失/相同 → authority-check 2
- PR 无 owner APPROVED / owner==primary / owner==PR author → merge 2 零 MERGE；有 owner APPROVED 且不同 → 0
- REVIEW.json 与最后 CHECKBACK 的 reviewer/head/base/verdict 不符 → review_unbacked drift；merge-check 2
- accept/post-merge 不再写 actor:"owner"；--by 与 owner 不一致拒绝
- 076 legacy bootstrap 合并；077+ 强制；真实塔 76/72 drift []；arch 18；profile 11/0；shape 0
