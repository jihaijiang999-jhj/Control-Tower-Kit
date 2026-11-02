# PILOT-063 — base-side envelope：PR head 恒等于 implementation

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-063`

## Scope

- envelope-new 新增 --base-side：envelope 文件提交在 main（parent==main head，只改 envelope path），implementation 分支 head 单独记录；写 ENVELOPE_NEW/QUEUE_ADD；不要求在实现分支上
- envelope_checks：base-side 信封要求 branch head == implementation_head_sha、review.head == implementation、envelope 文件在 base；不再要求 branch head == envelope head；branch-side 旧信封保持旧检查
- merge --mode pr：base-side 用 --match-head-commit implementation；branch 只含实现；CI 的 PR base 已有 envelope/queue 事件
- post-merge：envelope 文件在 base；implementation 合并后 ancestor；063 自身用 PR merge 验证
- 测试：base-side happy path（main envelope + impl branch，PR stub 0）、branch head != impl 拒绝、review head 不匹配拒绝、branch-side legacy 仍 0、额外文件拒绝
- 不改 058 review/059 acceptance/060 MERGE_START/062 abandon

## Allowed paths

- `pilot/worktrees/PILOT-063/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-063/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-063/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-063/tower-dsh/tools/tests/test_envelope_base_side.py`
- `pilot/worktrees/PILOT-063/tower-dsh/tools/tests/test_merge_head.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- rewriting/removing existing envelopes
- using local merge for 063
- weakening review head/base or acceptance gates

## Acceptance

- cd pilot/worktrees/PILOT-063/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 715 + 新增用例数（main 基线 715）
- base-side：envelope 在 main、branch head==implementation、review.head==implementation，merge --mode pr 0；--match-head-commit implementation
- branch head != implementation、review head 不匹配、额外文件 → exit 2 零 MERGED；branch-side legacy 仍 0
- CI 场景：PR base 已有 ENVELOPE_NEW/QUEUE_ADD，branch 只有实现；state-verify 无 unbacked envelope
- 063 自身 merge --mode pr 成功，GitHub merge commit 不是 local；post-merge 9/9
- 真实塔 63/63 drift []；arch gates 18；profile 11/0；shape 0
