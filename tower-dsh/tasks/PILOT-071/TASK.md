# PILOT-071 — task-supersede：owner 授权、写 ledger、不伪造 merge

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-071`

## Scope

- task-supersede --task --by-task --reason --by：仅 owner（by == owner）、源 delivered/rework、目标卡存在；refuse accepted/closed/already superseded
- 写 TASK_SUPERSEDE（primary，payload task/by/reason/superseded_by/at）；record.status=superseded、superseded_by；board.status=superseded；TASK_IDS 对应 ID 置 void；不建 envelope、不写 MERGE
- TASK_LIFECYCLE_STATUS 加 TASK_SUPERSEDE→superseded；TASK_TRANSITIONS 允许 delivered/rework→superseded；state-verify fold；不接受 →superseded 后再 accept/close
- position/where：superseded 视为 terminal（done），不要求 envelope；C-04 069 节点不再 active
- EVENT_CATALOG 加 TASK_SUPERSEDE（primary）
- tests：delivered→superseded；重复/closed/accepted 拒绝；owner-only；state-verify 0；where 10/10；069 真实 superseded
- 不改 058 review/059 acceptance/060 MERGE_START/070 base-sync

## Allowed paths

- `pilot/worktrees/PILOT-071/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tower_task.py`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tower_views.py`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tower_lookup.py`
- `pilot/worktrees/PILOT-071/tower-dsh/EVENT_CATALOG.json`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tests/test_task_supersede.py`
- `pilot/worktrees/PILOT-071/tower-dsh/tools/tests/test_modules.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- creating envelope or MERGE for superseded task
- allowing non-owner supersede
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-071/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 753 + 新增用例数（main 基线 753）
- delivered→superseded：record/board/ledger 同步、superseded_by 记录、无 envelope、无 MERGE、state-verify 0
- 重复 supersede、closed/accepted、非 owner、缺失目标 → exit 2 零写入/明确拒绝
- where：superseded 计 terminal done；069 真实 superseded by 070 后 10/10
- 071 自身 merge --mode pr 成功（base-side envelope）；真实塔 71/68 drift []；arch 18；profile 11/0；shape 0
