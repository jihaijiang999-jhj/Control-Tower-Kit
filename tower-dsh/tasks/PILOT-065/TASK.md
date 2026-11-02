# PILOT-065 — base-side envelope 形状检查用 envelope_head_sha（允许 state 后置）

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-065`

## Scope

- cherry-pick 064 5080a0dd 的 5 路径（tower_envelope/tower_merge/tower_cli/test_envelope_base_side/test_merge_head）
- base-side envelope_git_checks：用 env.envelope_head_sha（或 declared）作为形状提交；diff parent(eh)..eh 恰 [repo_path]；eh 是 base 祖先；cat-file base:repo_path 存在；不再要求 base tip == eh
- 保留 branch head == implementation、review.head == implementation、额外文件/非 envelope commit 拒绝；branch-side legacy 不变
- 测试：envelope 后提交 ledger/queue/task state 仍 merge-check 0；eh 不是 base 祖先/夹带文件仍 2；064 的 prefix 子目录测试保留
- 065 自身 merge --mode pr；CI base 含 state、branch 只含实现；post-merge 9/9
- 不改 058/059/060/062 行为

## Allowed paths

- `pilot/worktrees/PILOT-065/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-065/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-065/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-065/tower-dsh/tools/tests/test_envelope_base_side.py`
- `pilot/worktrees/PILOT-065/tower-dsh/tools/tests/test_merge_head.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- using local merge for 065
- weakening review/acceptance
- rewriting 064 history

## Acceptance

- cd pilot/worktrees/PILOT-065/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 715 + 新增用例数（采用 064 后应 727+）
- base-side：envelope 后再提交 ledger/queue/task state，merge-check 仍 0
- envelope_head_sha 不是 base 祖先 / parent..eh 含额外文件 / branch head != impl / review.head != impl → exit 2
- 065 自身 merge --mode pr 成功；GitHub merge commit 不是 local；post-merge 9/9
- 真实塔 65/65 drift []；arch gates 18；profile 11/0；shape 0
