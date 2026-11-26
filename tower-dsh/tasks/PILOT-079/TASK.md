# PILOT-079 — ledger 只追加 CI 守卫 + state/authority/profile 入 CI

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-079`

## Scope

- tools/ledger_guard.py：读取 base 的 ledger/*.jsonl 与当前文件；当前必须逐字节以 base 为前缀；截断/改写/删除历史行 exit 2；新增行允许
- workflow：checkout fetch-depth 0；新增 Ledger prefix、State verify、Authority check、Profile check 四步；顺序在 verify-ledger 之后
- test_ci_gate：GATE_STEP_COUNT 8→12，断言四个新步骤顺序
- test_ledger_guard：合法追加 0；改写历史 2；截断 2；删除文件 2；新增文件允许？ledger 新文件不允许，拒绝
- 不引入网络/密钥；不改变 ledger 链算法

## Allowed paths

- `pilot/worktrees/PILOT-079/tower-dsh/.github/workflows/tower-gate.yml`
- `pilot/worktrees/PILOT-079/tower-dsh/tools/ledger_guard.py`
- `pilot/worktrees/PILOT-079/tower-dsh/tools/tests/test_ledger_guard.py`
- `pilot/worktrees/PILOT-079/tower-dsh/tools/tests/test_ci_gate.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening CI steps
- allowing history rewrite

## Acceptance

- cd pilot/worktrees/PILOT-079/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 854 + 新增用例数（main 基线 854）
- CI 12 步：unit/spec-lint/coverage/verify-ledger/ledger-prefix/state-verify/authority/profile/arch/campaign/shape/status
- 篡改 base ledger 历史行 → ledger_guard 2；截断 → 2；合法追加 → 0
- 真实塔 79/75 drift []；arch 18；profile 11/0；shape 0；079 PR 审计 admin
