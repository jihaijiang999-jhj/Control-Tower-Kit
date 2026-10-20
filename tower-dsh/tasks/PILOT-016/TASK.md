# PILOT-016 — PR 合并上真机：gh 认证预检 + checks 注册竞态重试，并用 --mode pr 合并本卡

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-016`

## Scope

- merge --mode pr 在置 MERGING 之前执行 gh auth status 预检；未认证或 token 无效时 exit 2、phase=gh-auth，并提示 gh auth login
- gh pr checks 返回『no checks reported』（PR 刚建、CI 尚未注册）时不判失败，按间隔重试直到超时；只有真实失败才置 CORRECTION_REQUIRED
- 重试间隔可通过 --check-interval 配置，默认 10 秒；重试总时长仍受 --check-timeout 约束
- local 模式与既有 PR 模式语义保持不变；既有 174 个测试断言零修改
- 新增测试覆盖：未认证预检、checks 从无到有的竞态、真实失败仍 block
- 本卡自身合并使用 --mode pr（首次真实端到端），closeout 记录实际 PR 号与 merge commit

## Allowed paths

- `pilot/worktrees/PILOT-016/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-016/tower-dsh/tools/tests/test_merge_pr_mode.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing existing test assertions

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，既有 174 个测试断言零修改，总数 >= 178
- gh auth status 返回非零时：exit 2、信封与队列均为 CORRECTION_REQUIRED、phase=gh-auth、且未置 MERGING
- checks 首次返回 no checks reported、随后出现并全部通过时：流程继续到 merge 并成功，不产生 MERGE_BLOCKED
- checks 真实失败（非 no-checks）仍置 CORRECTION_REQUIRED，且不会因重试而无限等待
- 空全局 git 配置下全量仍全部通过
- spec-coverage 仍 27/27、tool_gaps 为空；spec-lint --strict 仍 6/6
- git diff --name-only main..HEAD 恰好是两个 allowed 文件
