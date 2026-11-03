# PILOT-066 — post-merge base-side envelope 路径 + 删除 repo-root shim

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-066`

## Scope

- tower_post_merge：envelope 文件存在性/内容检查对 base_side 使用 git show-prefix（tower-dsh/）+ envelope_path；branch-side legacy 仍 repo 根
- 错误信息带实际 repo_path，便于定位
- 测试：base-side envelope 在 tower-dsh/ 下 post-merge 检查 0；repo 根副本不存在仍 0；legacy branch-side 仍 0；shim 删除后 065 复核 0
- controller 合并后删除 repo 根 `merge-envelopes/ENV-PILOT-065.json`（不是 tower 内文件）
- 066 自身 base-side envelope + merge --mode pr；post-merge 9/9
- 不改 058/059/060/062/065 行为

## Allowed paths

- `pilot/worktrees/PILOT-066/tower-dsh/tools/tower_post_merge.py`
- `pilot/worktrees/PILOT-066/tower-dsh/tools/tests/test_post_merge_envelope_path.py`
- `pilot/worktrees/PILOT-066/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-066/tower-dsh/tools/tower_cli.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- deleting tower-dsh/merge-envelopes/ENV-PILOT-065.json
- rewriting 065 envelope/ledger
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-066/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 730 + 新增用例数（main 基线 730）
- base-side envelope 在 tower-dsh/merge-envelopes/ 下 post-merge 检查 0；repo 根无副本仍 0
- legacy branch-side envelope 仍按 repo 根 0；额外/缺失路径拒绝
- 删除 repo 根 shim 后，065 的 envelope 文件仍可在 base 找到；066 自身 post-merge 9/9
- 066 merge --mode pr 成功；真实塔 66/66 drift []（066 envelope 后）；arch 18；profile 11/0；shape 0
