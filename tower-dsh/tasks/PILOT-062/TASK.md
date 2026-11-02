# PILOT-062 — 账本清债：ENVELOPE_ABANDON + 记录豁免 + PR 路径首验

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-062`

## Scope

- 新增 towerctl envelope-abandon --envelope --reason [--by]：只允许 supervisor；源状态 WAITING/CORRECTION_REQUIRED/MERGE_BLOCKED/MERGING；置 envelope.status=ABANDONED、queue.status=ABANDONED、追加 ENVELOPE_ABANDON(supervision)；已 MERGED/POST_MERGE_VERIFIED 拒绝
- tower_ledger_replay：ENVELOPE_ABANDON 折叠为 ABANDONED；ENVELOPE_TRANSITIONS 允许 ABANDONED 从上述源；state-verify 不报 illegal_transition/drift
- EVENT_CATALOG.json 增加 ENVELOPE_ABANDON（supervision，payload envelope/reason/by/at）
- tests/test_envelope_abandon.py：WAITING/CORRECTION 可 abandon；MERGED 拒绝；重复 abandon 幂等或 exit 2；queue/envelope/ledger 同步；state-verify 0
- docs：tasks/PILOT-052/EXCEPTION.md（evidence 快照 07efc9c vs 最终 0a8bf31，受控继承 053 的 609 基线）、tasks/PILOT-056/BASELINE-MIGRATION.md（22 函数 metrics/1080 债务/root 复制说明）、pilot/PILOT-060.spec.json + TASK.md 的 59/59 改 60/59（060 建卡后，信封前）
- controller 合并后：对真实塔 ENV-PILOT-043 执行 envelope-abandon，确认 queue/envelope ABANDONED、state-verify 0；不删历史
- 062 自身：merge --mode pr，记录 GitHub PR merge commit；若仍报 Head branch modified，停下报告，不回退 local
- MAP §6.36 / NEXT-WINDOW 更新到 62/62、704、where 2/2、C-04 完成、PR 路径证据

## Allowed paths

- `pilot/worktrees/PILOT-062/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-062/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-062/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-062/tower-dsh/tools/tests/test_envelope_abandon.py`
- `pilot/worktrees/PILOT-062/tower-dsh/EVENT_CATALOG.json`
- `pilot/worktrees/PILOT-062/tower-dsh/tools/tower_merge.py`
- `pilot/worktrees/PILOT-062/tower-dsh/tools/tests/test_merge_head.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- deleting ledger or queue history
- abandoning MERGED/POST_MERGE_VERIFIED
- using local merge for 062
- weakening review/acceptance gates

## Acceptance

- cd pilot/worktrees/PILOT-062/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 704 + 新增用例数（main 基线 704）
- envelope-abandon 对 WAITING/CORRECTION_REQUIRED 生效；envelope.status=ABANDONED、queue.status=ABANDONED、ENVELOPE_ABANDON 写入；MERGED/VERIFIED exit 2
- state-verify 对 ABANDONED 无 illegal_transition；重复 abandon 幂等或明确 exit 2；ENVELOPE_TRANSITIONS 只加 ABANDONED
- 043 真实塔合并后 ABANDONED；state-verify 61/61 drift []（062 信封前 62/61）
- 052 EXCEPTION / 056 BASELINE-MIGRATION / 060 文本已落
- 062 merge --mode pr 成功，GitHub PR merge commit != 本地 merge commit；无 local fallback
- 真实塔 62/62 drift []；arch gates 18；profile 11/0；shape 0
