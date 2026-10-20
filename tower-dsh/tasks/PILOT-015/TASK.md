# PILOT-015 — 实现合并 PR 化：merge --mode pr 走 GitHub PR 与 CI 检查，本地模式保持原样

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-015`

## Scope

- towerctl merge 新增 --mode {local,pr}，默认 local；--remote（默认 origin）与 --check-timeout（默认 900 秒）
- pr 模式：git push <remote> <branch> → gh pr create --base <base> --head <branch> --json number,url → gh pr checks <n> --watch --fail-fast（受超时约束）→ gh pr merge <n> --merge → git fetch <remote> <base> → git merge --ff-only <remote>/<base>
- 任一步失败或超时：队列置 CORRECTION_REQUIRED、记录 MERGE_BLOCKED，绝不写 MERGED，并保留原始错误
- 信封记录 merge_mode / pr_number / pr_url / check_conclusion；merge-ledger 同步这些字段
- gh 可执行文件可用环境变量 TOWERCTL_GH 覆盖（默认 gh），便于测试注入桩；不存在时给出明确错误
- local 模式行为与现状逐字段一致，既有 163 个测试不得修改断言
- 新增 tools/tests/test_merge_pr_mode.py 覆盖 PR 流程编排与失败路径

## Allowed paths

- `pilot/worktrees/PILOT-015/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-015/tower-dsh/tools/tests/test_merge_pr_mode.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing existing tests or WF-MERGE spec

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，既有 163 个测试断言零修改，总数 >= 169
- pr 模式 happy path：桩 gh 下 merge exit 0，信封含 merge_mode=pr、pr_number 与 pr_url，且队列为 MERGED
- gh pr checks 返回非零时：队列与信封均为 CORRECTION_REQUIRED，不得出现 MERGED，ledger 含 MERGE_BLOCKED
- 超时（--check-timeout 1 配合桩进程挂起）时同样置 CORRECTION_REQUIRED，不挂死
- TOWERCTL_GH 指向不存在路径时 exit 2，错误信息含 gh 字样
- local 模式的输出字段与队列/信封状态与改动前一致（回归）
- spec-coverage 仍 27/27、tool_gaps 为空；spec-lint --strict 仍 6/6
- git diff --name-only main..HEAD 恰好是两个 allowed 文件
