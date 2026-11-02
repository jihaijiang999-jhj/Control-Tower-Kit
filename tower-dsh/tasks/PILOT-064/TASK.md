# PILOT-064 — base-side envelope 重建（tower 子目录前缀 + PR 首验）

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-064`

## Scope

- 以 063 `c2a1cc5` 为起点（cherry-pick 50d1844 + c2a1cc5），保留 5 路径：tower_envelope/tower_merge/tower_cli/test_envelope_base_side/test_merge_head
- base-side 路径必须用 git `--show-prefix`（tower-dsh/）+ envelope_path 比较；envelope 文件在 `tower-dsh/merge-envelopes/<ENV>.json`
- envelope-new --base-side：main envelope-only commit（parent main）、branch head == implementation、review.head == implementation；写 ENVELOPE_NEW/QUEUE_ADD
- envelope_checks：base-side 不要求 branch head == envelope head，要求 branch head==implementation/review.head==implementation/envelope 在 base；branch-side legacy 保持
- merge --mode pr：--match-head-commit implementation；CI base 有信封事件；064 自身 PR merge 首验
- 测试：base-side 子目录 prefix happy path；branch head 偏移/review 偏移/额外文件拒绝；legacy 0；725+
- 不改 058 review / 059 acceptance / 060 MERGE_START / 062 abandon

## Allowed paths

- `pilot/worktrees/PILOT-064/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-064/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-064/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-064/tower-dsh/tools/tests/test_envelope_base_side.py`
- `pilot/worktrees/PILOT-064/tower-dsh/tools/tests/test_merge_head.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- reopening/rewriting PILOT-063
- using local merge for 064
- weakening review/acceptance gates

## Acceptance

- cd pilot/worktrees/PILOT-064/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 715 + 新增用例数（main 基线 715；064 采用 063 代码后应 725+）
- base-side 子目录：main envelope commit + impl 分支，branch head==impl、review.head==impl，merge-check 0；envelope 文件在 tower-dsh/merge-envelopes
- branch head 偏移/review 偏移/额外文件 → exit 2 零 MERGED；branch-side legacy 仍 0
- 064 自身 merge --mode pr 成功；PR head == implementation；GitHub merge commit 不是 local；post-merge 9/9
- 真实塔 64/64 drift []；arch gates 18；profile 11/0；shape 0
