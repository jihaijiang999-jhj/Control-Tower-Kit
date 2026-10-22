# PILOT-032 — 完成卡不得静默重建：TASK_NEW 从 accepted/closed 记 illegal_transition

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-032`

## Scope

- 把 TASK_TRANSITIONS 中 TASK_NEW 的允许来源从 ANY 收紧为 {None, ready, dispatched, delivered, reviewed, rework}：首次建卡与在途重建（PILOT-025 先例：dispatched→ready）仍合法
- TASK_NEW 来自 accepted 或 closed → 产生 illegal_transition（复用 028 的 drift 形状：kind/target/event/expected/actual，expected 为排序后的允许来源列表）
- 其余事件表、未知事件忽略、最终状态折叠、计数与既有 drift 行为不变
- 更新 tools/tests/test_state_verify.py：dispatched→TASK_NEW 合法；closed→TASK_NEW 判红；accepted→TASK_NEW 判红；首次 TASK_NEW（None）合法；错误形状与排序断言

## Allowed paths

- `pilot/worktrees/PILOT-032/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-032/tower-dsh/tools/tests/test_state_verify.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- allowing a completed card to be reset by a bare TASK_NEW

## Acceptance

- cd pilot/worktrees/PILOT-032/tower-dsh && python -B tools/run_tests.py 全部通过，总数 >= 266（main 基线 266）
- 临时塔：closed→TASK_NEW → exit 2，drift 含 illegal_transition，event=TASK_NEW，actual=closed，expected 含 dispatched/delivered/ready/reviewed/rework（不含 accepted/closed）
- accepted→TASK_NEW 同样判红；dispatched→TASK_NEW 与首次 TASK_NEW（None）保持合法、drift 为空
- 真实塔 state-verify：exit 0、drift=[]（历史只有 None→ready 与 dispatched→ready）
- 既有 028 迁移测试与全部 state-verify 测试全绿
- python tools/towerctl.py spec-coverage 27/27、spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-032 diff --name-only main..HEAD 恰好两个 allowed_paths 文件
