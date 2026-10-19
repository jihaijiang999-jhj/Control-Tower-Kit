# PILOT-009 — 条款覆盖：把 spec 条款绑定到真实测试并设门

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-009`

## Scope

- 新增 tools/tests/clause_bindings.py：把每条 tool-check 条款映射到至少一个已存在的测试 ID
- 新增 tools/spec_coverage.py：解析 workflow/policy 条款、加载绑定、校验测试存在、输出覆盖矩阵
- towerctl 注册 spec-coverage 子命令，输出 JSON；tool-check 缺口或未知绑定 exit 2
- review-check / owner-gate 条款单独计数为 manual / owner，不判失败
- 新增 tools/tests/test_coverage.py：覆盖真实塔根 gaps=0、未知测试 ID、未知条款、未绑定 tool 条款
- 缺失的 tool-check 测试补在 test_coverage.py 内（不改既有测试行为）

## Allowed paths

- `pilot/worktrees/PILOT-009/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-009/tower-dsh/tools/spec_coverage.py`
- `pilot/worktrees/PILOT-009/tower-dsh/tools/tests/clause_bindings.py`
- `pilot/worktrees/PILOT-009/tower-dsh/tools/tests/test_coverage.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 95
- 对真实塔根运行 spec-coverage 返回 ok=true，specs=6，tool_gaps=0，unknown=0
- 6 份 spec 的每条 tool-check 条款都至少绑定 1 个已存在的测试
- 绑定到不存在的测试 ID → exit 2
- 绑定到不存在的条款 ID → exit 2
- tool-check 条款未绑定 → exit 2（用临时 spec 夹具验证）
- review-check / owner-gate 条款计入 manual/owner，不导致失败
- startup / wiring / handoff-check / spec-lint 不回归
