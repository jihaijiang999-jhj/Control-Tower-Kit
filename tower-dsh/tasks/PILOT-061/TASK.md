# PILOT-061 — PR merge head 一致性：只允许 implementation + envelope-only 差量

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-061`

## Scope

- pr_remote_merge：取 PR head 后，若 head != envelope implementation_head_sha，计算 implementation..head 的 diff；只允许恰好一个 `merge-envelopes/<ENV>.json` 变更，其它文件/多个提交 exit 2（MergeBlocked）
- gh pr merge 的 --match-head-commit 使用 PR 实际 head（不是 envelope implementation head）；head 不匹配/额外提交不产生 MERGED
- merge-check 的 review head == envelope implementation、review base == dispatch base 保持不变；envelope-only commit 不被视为实现变更
- merge --mode local 保留为显式 fallback，但默认 PR 卡不得使用；CI/文档记录 PR 路径成功
- tests：implementation-only head 成功；implementation + envelope-only 成功；implementation + 其它文件 exit 2；多个 envelope 提交 exit 2；review head 仍是 implementation；head 不匹配 fail
- 不改 envelope-new/queue/ledger/replay；不改 058 review 门；不改 059 acceptance

## Allowed paths

- `pilot/worktrees/PILOT-061/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-061/tower-dsh/tools/tests/test_merge_head.py`
- `pilot/worktrees/PILOT-061/tower-dsh/tools/tests/test_review_gate.py`
- `pilot/worktrees/PILOT-061/tower-dsh/tools/tests/test_merge_head.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- allowing extra implementation commits in PR head
- using local merge as the default path
- weakening review head/base binding

## Acceptance

- cd pilot/worktrees/PILOT-061/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 688 + 新增用例数（main 基线 688）
- implementation-only PR head：仅 pr_remote_merge 辅助层 0，`--match-head-commit <impl>`；CLI 主路径不适用（envelope_checks 要求 envelope commit）
- implementation + envelope-only PR head：merge --mode pr 0，`--match-head-commit <PR head>`，不报 Head branch modified
- implementation + 额外文件 / 多次 envelope 提交：merge exit 2，零 MERGED；review head 不匹配仍 exit 2
- 真实塔 state-verify 61/60（061 建卡后；建信封后 61/61） drift []；arch gates 18；profile 11/0；shape 0
- git -C pilot/worktrees/PILOT-061 diff --name-only main..HEAD 恰 3 个 allowed_paths
