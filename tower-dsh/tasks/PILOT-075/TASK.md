# PILOT-075 — recover 从 CORRECTION 补 MERGE 的顺序；CI fetch-depth 0；恢复 074

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-075`

## Scope

- envelope-recover 源 CORRECTION_REQUIRED：先 append MERGE_START(recovered=true)，再 append MERGE(recovered=true)；MERGE_START 从 CORRECTION 合法（已有）
- 已存在 MERGE 的 CORRECTION（074 现状）：recover 只把 envelope/queue 置 MERGED，不重复 MERGE；若 MERGE payload recovered=true 且 merge_commit 一致则合法
- tower_ledger_replay：MERGE 的源允许 MERGING，或 CORRECTION_REQUIRED 且 payload.recovered=true 且该 envelope 之前已有 MERGE_START；普通 CORRECTION→MERGE 仍 illegal
- state-verify 074：MERGE 不再 illegal；envelope.status=MERGED；merge_commit=373d42c；post-merge 只接受 MERGED
- CI .github/workflows/tower-gate.yml checkout fetch-depth: 0；test_ci_gate 仍 8 步（不变）
- 测试：CORRECTION recover 写序 MERGE_START→MERGE；已有 MERGE 的恢复不重复；普通 CORRECTION MERGE 仍 illegal；074 真实恢复 drift 0；post-merge 9/9

## Allowed paths

- `pilot/worktrees/PILOT-075/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-075/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-075/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-075/tower-dsh/tools/tests/test_envelope_recover.py`
- `pilot/worktrees/PILOT-075/tower-dsh/.github/workflows/tower-gate.yml`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- allowing ordinary CORRECTION→MERGE
- writing POST_MERGE_VERIFIED in recover
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-075/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 807 + 新增用例数（main 基线 807）
- CORRECTION recover：append MERGE_START(recovered) 后 MERGE(recovered)；state-verify 0
- 已存在 MERGE 的 CORRECTION 恢复：不重复 MERGE，status=MERGED，merge_commit 一致
- 普通 CORRECTION→MERGE（无 recovered）仍 illegal；recover 不写 verified
- CI workflow fetch-depth 0；8 步不变
- 074 真实恢复后 state-verify 74/70 drift []；post-merge 9/9；075 PR 审计 admin
