# PILOT-007 — spec-lint：让工作流规范可被机器校验

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-007`

## Scope

- 新增 tools/spec_lint.py：校验 tower/workflow@1 文档
- towerctl 注册 spec-lint 子命令，输出 JSON 并在有错时 exit 2
- 校验 front matter：schema/id/title/owner/version/enforcement_legend
- 校验 7 个必需章节齐全
- 校验状态表：状态唯一，且转移中的 from/to 必须是已声明状态或 —
- 校验每个声明状态至少出现在一条转移中（无不可达状态）
- 校验 INV/FM/TR 编号唯一且符合前缀
- 校验 invariant 的 enforcement 取值在 enforcement_legend 内
- 校验 命令 列引用的 towerctl 子命令真实存在
- 新增 tools/tests/test_spec_lint.py 覆盖合法与各类非法夹具

## Allowed paths

- `pilot/worktrees/PILOT-007/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-007/tower-dsh/tools/spec_lint.py`
- `pilot/worktrees/PILOT-007/tower-dsh/tools/tests/test_spec_lint.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 67
- 对仓库真实 specs/ 目录运行 spec-lint 返回 ok=true，files=4，errors=0
- 缺少章节、未知状态、不可达状态、非法 enforcement、未知命令、重复 ID、缺 front matter 各自使 exit 2
- startup / wiring / handoff-check --package HANDOFF-PILOT-001 不回归
- 不改变既有子命令行为
