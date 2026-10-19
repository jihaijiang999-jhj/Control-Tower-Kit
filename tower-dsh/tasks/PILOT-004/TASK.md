# PILOT-004 — handoff 参数化：去写死 PILOT-001，改为按 task/envelope 生成与校验

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-004`

## Scope

- current_snapshot(root, task_id=None, envelope_id=None) 支持显式选择，不再写死 PILOT-001 / ENV-PILOT-001
- task 选择：显式 --task 优先；否则取唯一未 closed 任务；否则取最近更新任务
- envelope 选择：显式 --envelope 优先；否则取唯一队列项；否则取最近项
- repo / worktree 从 PROJECT_PROFILE.pilot 读取，缺失时回退到任务 record
- handoff-new 生成 §1/§3/§4/§7 时使用真实 task/envelope/paths，不写死 Phase 2 / PILOT-001
- §4 从 TASK_BOARD 生成在途任务清单（status != closed），无在途时写“无在途任务”
- package.json 顶层记录 task 与 envelope
- handoff-check 使用 package 自带的 task/envelope 做 §0 校验
- 新增 tools/tests/test_handoff_generic.py 覆盖多任务/多 envelope 选择与生成内容

## Allowed paths

- `pilot/worktrees/PILOT-004/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-004/tower-dsh/tools/tests/test_handoff_generic.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 32
- 对非 PILOT-001 任务生成 handoff 时，HANDOFF.md 的 §0/§3/§4/§7 出现该任务 ID，且不出现 PILOT-001
- §4 在存在未 closed 任务时逐条列出，否则写“无在途任务”
- 生成的 §1 不含硬编码 Phase 2 文案，反映当前 phase/queue/task 实值
- handoff-check 对新建包通过，且使用 package 自带的 task/envelope
- 既有 handoff-check --package HANDOFF-PILOT-001 仍 21/21 通过
- startup / wiring 不回归
