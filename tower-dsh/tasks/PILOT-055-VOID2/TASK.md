# PILOT-055 — shape 接 CI（8 步门）

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-055`

## Scope

- workflow（仓库根 `.github/workflows/tower-gate.yml`）：在 `Campaign check` 之后、`Status` 之前增加 `- name: Shape check` / `run: python tools/towerctl.py shape-check`；status 仍最后；不加 continue-on-error；其它 7 步不变
- tools/tests/test_ci_gate.py：COMMANDS 增加 shape 命令；顺序表/步数断言从 7 改 8；断言 shape 在 campaign-check 之后、status 之前；status 仍唯一且最后；continue-on-error 仍不存在
- ARCHITECTURE.md：把 CI 的“7 步”改成“8 步”，列表加入 shape-check；注明 055 接入；与 workflow 实体一致
- 不修改 towerctl.py、shape-check 规则、state/SHAPE-BASELINE.json、其它测试、GATES/EVENT_CATALOG/ADR 决策

## Allowed paths

- `pilot/worktrees/PILOT-055/.github/workflows/tower-gate.yml`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tests/test_ci_gate.py`
- `pilot/worktrees/PILOT-055/tower-dsh/ARCHITECTURE.md`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tests/test_wiring.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-055/tower-dsh/tools/tests/test_dispatch_repair.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- modifying towerctl.py or shape-check rule
- changing shape baseline
- weakening CI (continue-on-error, removing steps, moving status earlier)
- modifying other tests or ARCHITECTURE sections beyond the CI step list

## Acceptance

- cd pilot/worktrees/PILOT-055/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 630（main 基线 630）
- test-ci-gate：COMMANDS 含 shape；顺序为 unit → spec-lint → spec-coverage → verify-ledger → arch → campaign → shape → status；步数 8；status 唯一且最后；无 continue-on-error
- workflow 中 shape 命令精确为 `python tools/towerctl.py shape-check`；位置在 campaign-check 之后、status 之前；status 最后
- ARCHITECTURE.md 的 CI 段为 8 步并含 shape；与 workflow 实体一致
- shape-check 在 worktree exit 0（不改 baseline/规则）
- 真实塔：worktree 新工具 state-verify drift []、arch-check 0、profile-check 11/0；建信封前 tasks=55/envelopes=54，建信封后 55/55；verify-ledger 0、coverage 27/27、spec-lint 6/6
- 旧码对照：main 的 workflow 7 步且无 shape；新码 8 步且有 shape。证据写进 scratch/probe-old-code.txt
- git -C pilot/worktrees/PILOT-055 diff --name-only main..HEAD 恰 6 个 allowed_paths
