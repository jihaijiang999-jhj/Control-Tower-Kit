# PILOT-074 — verified 必须有 MERGE 事实；回填 065–068；新增 verified_without_merge drift

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-074`

## Scope

- post-merge：源状态只允许 MERGED；要求 supervision ledger 存在该 envelope 的 MERGE（或 MERGE_HISTORICAL）；merge_commit 必须非空、可解析、在 origin/main、第二父 == implementation_head_sha（无第二父则拒绝）
- CORRECTION_REQUIRED 不再直接 post-merge；必须先 envelope-recover 补 MERGE 再 post-merge；新卡 CORRECTION→VERIFIED 拒绝
- state-verify 新增 verified_without_merge：VERIFIED 但无 MERGE/MERGE_HISTORICAL 或 merge_commit 空/不匹配 → drift
- 新增 MERGE_HISTORICAL 事件（supervision）：仅 pre-074 envelope + pinned supervisor；payload merge_commit/recovered=true/historical=true/by/reason；只补事实、不改 status、不写 admin
- envelope-recover --historical：源 VERIFIED 且 merge_commit 缺失；校验 merge_commit 第二父==impl 且在 origin/main；补 MERGE_HISTORICAL；不写 POST_MERGE_VERIFIED
- 回填 065 c199928、066 713d709、067 eba7ed3、068 969acdb；回填后 state-verify drift 0，merge_commit 非空
- legacy 兼容：pre-074 的 CORRECTION→VERIFIED 事件仍 replay 通过；074+ 严格 MERGED→VERIFIED
- 测试：新卡 CORRECTION post-merge 2；MERGED 无 MERGE 2；第二父错 2；verified_without_merge drift；historical recover 0/拒绝；legacy replay 0

## Allowed paths

- `pilot/worktrees/PILOT-074/tower-dsh/tools/tower_post_merge.py`
- `pilot/worktrees/PILOT-074/tower-dsh/tools/tower_ledger_replay.py`
- `pilot/worktrees/PILOT-074/tower-dsh/tools/tower_envelope.py`
- `pilot/worktrees/PILOT-074/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-074/tower-dsh/EVENT_CATALOG.json`
- `pilot/worktrees/PILOT-074/tower-dsh/tools/tests/test_verified_merge_fact.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- writing admin=true for historical recovery
- backfilling 065-068 without merge_commit second-parent check
- weakening review/acceptance

## Acceptance

- cd pilot/worktrees/PILOT-074/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 788 + 新增用例数（main 基线 788）
- 新卡 CORRECTION_REQUIRED post-merge → 2；MERGED 但无 MERGE 事件/merge_commit → 2；merge_commit 第二父 != impl → 2；零 VERIFIED 写入
- state-verify 在回填前报 065–068 verified_without_merge；回填后 drift 0；merge_commit 分别为 c199928/713d709/eba7ed3/969acdb
- MERGE_HISTORICAL 仅 pre-074 + supervisor；074+ 拒绝；不写 admin=true、不写 POST_MERGE_VERIFIED
- legacy pre-074 CORRECTION→VERIFIED replay 0；074+ 转移只 MERGED→VERIFIED
- 074 自身 PR 审计 admin；真实塔 74/70 drift []；arch 18；profile 11/0；shape 0
