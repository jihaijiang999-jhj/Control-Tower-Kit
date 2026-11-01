# PILOT-056 — towerctl 模块化（23 模块 / 4 层 DAG）+ 基线迁移

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-056`

## Scope

- 拆 23 个模块（每模块 <600 行，含 header）：tower_common、tower_ledger、tower_ledger_replay；tower_task、tower_authority、tower_authority_cmd、tower_delivery、tower_dispatch、tower_envelope、tower_handoff、tower_merge、tower_post_merge、tower_command、tower_campaign、tower_shape、tower_arch、tower_arch_check、tower_profile；tower_views、tower_status、tower_lookup、tower_state_verify；tower_cli
- towerctl.py 只保留 bootstrap/main，<3000 行（目标 <500）；所有 CLI 子命令/退出码/JSON/证据/状态语义不变
- 4 层依赖 DAG：base → domain → compose → entry；只允许向下 import；禁止循环；test_modules 用 AST 校验
- 基线迁移：state/SHAPE-BASELINE.json 中 22 个长函数（cmd_merge/state_verify_drift/authority_state_check/build_parser 等）从 towerctl.py 条目迁移到新模块条目，lines/branches 保持原值；新增 test_shape_baseline_move 校验迁移前后函数数/metrics 净额不变（不得借机放宽）
- 新增 tools/tests/test_modules.py：towerctl.py <3000、每模块 <600、import DAG 无环、CLI smoke
- arch/GATES.json 加 GATE-MODULES（test 指向 test_modules 行数用例）；test_arch gates 17→18
- ARCHITECTURE.md 加模块图/职责/4 层依赖；与实体文件一致
- 不改 workflow（055 已有 shape 第 8 步）；不改 shape 规则/阈值；不拆长函数（只换文件）
- 真实塔：新建卡后 tasks=56/envelopes=55，建信封后 56/56；state-verify/profile/arch 全绿；638+ tests

## Allowed paths

- `pilot/worktrees/PILOT-056/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_common.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_ledger.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_task.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_authority.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_authority_cmd.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_delivery.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_dispatch.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_handoff.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_post_merge.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_command.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_campaign.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_shape.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_arch.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_arch_check.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_profile.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_views.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_status.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_lookup.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_state_verify.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tests/test_modules.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tests/test_shape_baseline_move.py`
- `pilot/worktrees/PILOT-056/tower-dsh/tools/tests/test_arch.py`
- `pilot/worktrees/PILOT-056/tower-dsh/ARCHITECTURE.md`
- `pilot/worktrees/PILOT-056/tower-dsh/arch/GATES.json`
- `pilot/worktrees/PILOT-056/tower-dsh/state/SHAPE-BASELINE.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- behavior changes disguised as refactor
- splitting or rewriting the 22 long functions (only move them)
- raising shape thresholds or deleting baseline entries to pass
- new ledger event types
- changing tower/spec@2 fields
- touching TOWER.md (L0)
- deleting tests to make the split pass

## Acceptance

- cd pilot/worktrees/PILOT-056/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 675 + 新增用例数（main 基线 675）
- towerctl.py <3000；23 个模块每个 <600；test_modules 校验行数、4 层 DAG、无循环、CLI smoke 全 0
- 基线迁移净债务为 0：SHAPE-BASELINE 中 22 个长函数的 lines/branches 与迁移前逐项相等，只是 file 改变；test_shape_baseline_move 通过；shape-check 0
- 所有 CLI 子命令行为不变：state-verify/authority-check/arch-check/profile-check/campaign-check/where/shape-check/spec-lint --strict 均 exit 0
- arch/GATES.json 含 GATE-MODULES 且 test 真实存在；test_arch gates 18；arch-check 0
- ARCHITECTURE.md 模块图/职责/4 层依赖与 23 个实体文件一致
- 旧码对照：main towerctl.py 8,863 行、无 tower_* 模块；新码 <3000、23 模块、CLI 等价；证据 scratch/probe-old-code.txt
- 真实塔：新建卡后 tasks=59/envelopes=58，建信封后 59/59；worktree 新工具 state-verify drift []、profile-check 11/0、arch-check 0；verify-ledger 0；coverage 27/27；spec-lint 6/6
- git -C pilot/worktrees/PILOT-056 diff --name-only main..HEAD 恰 30 个 allowed_paths
