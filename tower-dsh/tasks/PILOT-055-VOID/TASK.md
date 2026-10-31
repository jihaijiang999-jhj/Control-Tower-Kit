# PILOT-055 — shape 接 CI + towerctl 模块化（单文件 <3000 行）

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-055`

## Scope

- 拆出模块（每个 <600 行）：tower_common（JSON/IO/id/path/emit）、tower_ledger（append/verify/replay/lock）、tower_task（task-new/check/approve/close/board）、tower_delivery（dispatch/deliver/evidence/completion）、tower_merge（envelope/queue/merge/post-merge）、tower_command（campaign/brief/where/status）、tower_arch（arch-check/graph）、tower_profile（profile-check）、tower_cli（parser/handlers/composition）
- towerctl.py 只保留入口（import tower_cli + main），行数 <3000（目标 <500）；所有 CLI 子命令、退出码、单 JSON 输出、证据/状态语义不变
- 依赖方向单向：towerctl → tower_cli → 各域模块 → tower_common/tower_ledger；域模块之间只允许 delivery/merge 依赖 ledger/task；禁止循环 import
- 新增 tools/tests/test_modules.py：towerctl.py <3000；每个 tower_*.py <600；无循环 import；CLI 关键命令 smoke（startup/state-verify/where/profile-check/arch-check/shape-check）仍 exit 0
- arch/GATES.json 增加 GATE-MODULES（command=test-modules 或 shape-check？用 towerctl 现有命令不可表达，test 指向 test_modules 的行数用例）；tools/tests/test_arch.py 的 gates 计数 17→18
- .github/workflows/tower-gate.yml 在 status 之前增加 python tools/towerctl.py shape-check；status 仍最后；不加 continue-on-error；test_ci_gate 不回归
- ARCHITECTURE.md 增加模块图/依赖方向/每个模块职责；arch-check 仍 0
- shape-check 在搬家后仍 exit 0（新模块 <600、无新增长函数/重复块；如基线因路径变化失效，卡内重建基线并说明）
- 真实塔：worktree 新工具 state-verify drift []、profile-check 11/0、arch-check 0；建信封前 tasks=55/envelopes=54，建信封后 55/55；verify-ledger 0、coverage 27/27、spec-lint 6/6
- 不改 036–054 的信任边界/授权/前置链/范围门/completion/shape/objective/campaign/depends_on/记录层/信封恢复语义；不新增事件；不写 primary/supervision/ledger

## Allowed paths

- `pilot/worktrees/PILOT-055/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_common.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_ledger.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_task.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_delivery.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_command.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_arch.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_profile.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tests/test_modules.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tests/test_arch.py`
- `pilot/worktrees/PILOT-055/tower-dsh/.github/workflows/tower-gate.yml`
- `pilot/worktrees/PILOT-055/tower-dsh/ARCHITECTURE.md`
- `pilot/worktrees/PILOT-055/tower-dsh/arch/GATES.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening existing gates
- behavior changes disguised as refactor
- new ledger event types
- changing tower/spec@2 fields
- touching TOWER.md (L0)
- deleting tests to make the split pass

## Acceptance

- cd pilot/worktrees/PILOT-055/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 630 + 新增用例数（main 基线 630）
- towerctl.py 行数 <3000（目标 <500）；每个 tower_*.py <600；test_modules 校验无循环 import 且 CLI smoke 全 0
- 所有既有 CLI 子命令行为不变：state-verify/authority-check/arch-check/profile-check/campaign-check/where/shape-check/spec-lint --strict 均 exit 0
- arch/GATES.json 含 GATE-MODULES 且 test 真实存在；test_arch gates 18；arch-check 0
- workflow 在 status 前含 shape-check，status 最后，无 continue-on-error；test_ci_gate 不回归
- ARCHITECTURE.md 含模块图/依赖方向/职责；与实体文件一致
- shape-check 在 worktree exit 0；新模块无 >600 行、无新增长函数/重复块
- 旧码对照：main towerctl.py 8,863 行、无 tower_* 模块；新码 <3000、CLI 等价。证据写进 scratch/probe-old-code.txt
- 真实塔：worktree 新工具 state-verify drift []、profile-check 11/0、arch-check 0；建信封前 tasks=55/envelopes=54，建信封后 55/55；verify-ledger 0 error；spec-coverage 27/27；spec-lint 6/6
- git -C pilot/worktrees/PILOT-055 diff --name-only main..HEAD 恰 15 个 allowed_paths
