# PILOT-018 — 修复 deliver 重复投递产生的重复证据 ID：每次投递后按序重排 E-001..E-00N

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-018`

## Scope

- cmd_deliver 在合并完本次证据后，把 record.evidence 的 id 统一重排为 E-001..E-00N（顺序为当前列表顺序）
- 重投递同一路径时更新该条目的 sha256/bytes/at，不追加重复条目，重排后 ID 仍连续唯一
- deliver 的 JSON 输出与 DELIVERY.md 内容随之使用重排后的 ID
- 不改既有命令的其它字段语义；既有测试断言零修改
- 新增 tools/tests/test_deliver_ids.py 固定以上行为

## Allowed paths

- `pilot/worktrees/PILOT-018/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-018/tower-dsh/tools/tests/test_deliver_ids.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- changing existing test assertions

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总数 >= 187
- 对同一路径连续 deliver 两次后，record.evidence 的 id 严格等于 [E-001, E-002, ...]，无重复
- 一次 deliver 三个不同文件后，id 为 E-001/E-002/E-003，且 path 与 sha256 与源文件一致
- 重投递同一路径后条目数量不变、该条目 sha256 更新为新文件哈希
- DELIVERY.md 中的 ID 与 record.evidence 一致
- spec-coverage 27/27、tool_gaps 空；spec-lint --strict 6/6
- git diff --name-only main..HEAD 恰好两个 allowed 文件
