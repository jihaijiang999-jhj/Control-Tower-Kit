# PILOT-047 — 双视图位置图：campaign roadmap/current + where --json|--md + 注入

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-047`

## Scope

- 编辑 command/campaigns/C-2026-Q4-01.md：保留现有内容，增加 roadmap: [PILOT-045, PILOT-046, PILOT-047, PILOT-048, PILOT-049, PILOT-050]、current: PILOT-047；task_forces 补 PILOT-046、PILOT-047；sequence 更新为 045→046→047→048→049→050；其余字段不动
- 新增 towerctl where：读 active campaign 的 roadmap/current 与 tasks/*/record.json，生成 position 模型——nodes 顺序=roadmap 顺序；status 枚举 done|active|blocked|planned|skipped（record closed→done；dispatched/delivered/reviewed/accepted→active；rework 或 review.verdict=FAIL→blocked；id==current 且无 record→active；仅 spec→planned；其余 planned）；index=第一个非 done 的 1-based 位置；total=len(roadmap)；next=current（若未 done）否则第一个 planned；全 done 时 index=total、next=null
- where 校验：roadmap 缺失/空/重复、current 不在 roadmap → exit 2（E8 position invalid），不猜；无 active campaign → exit 2（E9 no active campaign）
- where --json：输出 schema=tower/position@1，字段 {campaign, goal, index, total, current, next, nodes:[{id,status}], wip:{in_flight,limit}, blocked:[ids], stop_conditions:[...], sources:[...]}；枚举固定、顺序=roadmap、无时间戳、键排序；stdout 只输出 JSON
- where（默认/--md）：人视图 ≤20 行——一行战役名 + 位置条（✅ ▶ · ⛔）、位置 x/y、下一站、为什么是这仗（objective）、本节点交付、风险/待决（blocked/未回填）、建议（blocked 非空→先处理阻塞；否则继续）；--md 用 Markdown 标题，内容同源
- 注入：checkback 输出 JSON 增加 position 对象（无 roadmap 时省略，保持既有夹具兼容）；REVIEW.md 增加 '## Position' 段（有 position 时）；close 输出增加 position；post-merge 输出增加 position；status-snapshot 条目增加 '- position: x/y'（无 roadmap 时 '-'）；brief 的“当前战役”进度优先用 roadmap（closed/total），无 roadmap 回退 task_forces
- campaign-check 扩展：roadmap 必须是 id 列表且唯一、current 必须在 roadmap；roadmap 中尚无 tasks/<id>/ 也无 pilot/<id>.spec.json 的项发 W4（info，默认 exit 0、--strict 2）；task_forces 的 E5 语义不变
- 新增 tools/tests/test_position.py：position 模型（done/active/blocked/planned/current 无 record/all done）、roadmap 缺失/空/重复/current 不在 → E8、无 campaign → E9、--json schema/枚举/顺序、人视图含 x/y 与下一站、checkback/close/post-merge 注入、status-snapshot position 行、brief 进度用 roadmap、无 campaign 夹具保持旧输出（无 position 键）
- 真实塔文档：status/2026-10-29.md 由 status-snapshot 生成（含 position 行）、status/index.json 由 status-index 重算；内容基于 worktree 状态，不手写
- 真实塔验证：worktree 新工具 where --json 显示 2/6、next=PILOT-047、current=PILOT-047；where 人视图含位置条与下一站；campaign-check exit 0；authority-check exit 0、state-verify drift []；建信封前 tasks=47/envelopes=45，建信封后 47/46
- 不改 036–046 的信任边界/授权/前置链/空账本/范围门/completion/base_sha/shape/命令层语义（除 where 与注入）；不写 primary/supervision/ledger；不引入依赖

## Allowed paths

- `pilot/worktrees/PILOT-047/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-047/tower-dsh/tools/tests/test_position.py`
- `pilot/worktrees/PILOT-047/tower-dsh/command/campaigns/C-2026-Q4-01.md`
- `pilot/worktrees/PILOT-047/tower-dsh/status/2026-10-29.md`
- `pilot/worktrees/PILOT-047/tower-dsh/status/index.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- guessing position when roadmap/current is invalid (must exit 2)
- writing primary/supervision/ledger state from where/brief/status commands
- parsing the human view as machine input inside the tool

## Acceptance

- cd pilot/worktrees/PILOT-047/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 487 + 新增用例数（main 基线 487）
- where --json 在真实 worktree：schema=tower/position@1、index=2、total=6、current=PILOT-047、next=PILOT-047、nodes 顺序=roadmap、status 枚举合法、exit 0
- where 人视图 ≤20 行，含位置条（✅045/✅046/▶047）、'位置 2/6'、'下一站 047'、为什么/交付/风险/建议五段；--md 同源
- roadmap 缺失/空/重复/current 不在 roadmap → exit 2（E8）；无 active campaign → exit 2（E9）；均无 Traceback
- 注入：checkback 输出含 position、REVIEW.md 含 '## Position'；close 输出含 position；post-merge 输出含 position；status-snapshot 条目含 '- position: 2/6'；无 roadmap 的旧夹具保持原输出（无 position 键）
- brief 的当前战役进度显示 2/6（roadmap 口径），不再 1/1；无 roadmap 时回退 task_forces
- campaign-check：roadmap/current 校验通过；roadmap 中未创建的 048–050 发 W4（默认 0，--strict 2）；E1–E7/W1–W3 行为不变
- status 命令与位置命令只读：运行前后 primary/supervision/ledger/tasks 哈希不变（status-snapshot 仅写 status/）
- 旧码对照：main 版无 where 子命令（argparse invalid choice, exit 2）；campaign 无 roadmap 时旧 brief 仍 1/1，新码 2/6。证据写进 scratch/probe-old-code.txt
- shape-check 在 worktree exit 0（新增函数全部 ≤80 行/≤12 分支）
- 真实塔：worktree 新工具 where/campaign-check/authority-check exit 0、state-verify drift []；建信封前 tasks=47/envelopes=45，建信封后 47/46；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-047 diff --name-only main..HEAD 恰五个 allowed_paths
