# PILOT-053 — re-envelope 热修：ENVELOPE_NEW 保留已有状态 + merge 校验信封

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-053`

## Scope

- replay_envelope_statuses：ENVELOPE_NEW 命中已有状态时保留原状态（WAITING/CORRECTION_REQUIRED/MERGED），只有全新信封置 DRAFT；不改其他事件的折叠表
- cmd_envelope_new：已存在且 status=MERGED → exit 2（不能重开已合并）；已有 WAITING/CORRECTION_REQUIRED → 保留状态并更新 head/implementation；新信封 → DRAFT；仍 append ENVELOPE_NEW，不手改 ledger
- merge 入口：在队列/信封读取之后、写 MERGE_START 之前，要求信封 status ∈ {WAITING, CORRECTION_REQUIRED}；DRAFT/MERGED → exit 2 单 JSON，零 MERGE_START/零 ledger 写入
- 新增 tools/tests/test_envelope_recovery.py：失败 merge→MERGE_BLOCKED→重信→状态保留→state-verify drift 0→二次 merge 成功；DRAFT 信封 merge exit 2；MERGED 重信 exit 2；WAITING 重信保留；replay 单元（ENVELOPE_NEW 两次不重置状态）
- ARCHITECTURE.md §4 增加“信封恢复”契约：ENVELOPE_NEW 保留状态、merge 入口断言、MERGED 不可重开
- 不改 036–052 的信任边界/授权/前置链/范围门/completion/shape/objective/campaign/depends_on 语义；不新增事件类型；不改 spec@2；不写 primary/supervision/ledger

## Allowed paths

- `pilot/worktrees/PILOT-053/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-053/tower-dsh/tools/tests/test_envelope_recovery.py`
- `pilot/worktrees/PILOT-053/tower-dsh/ARCHITECTURE.md`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening existing gates
- rewriting the supervision ledger
- reopening a MERGED envelope
- allowing MERGE_START from DRAFT
- new ledger event types
- changing tower/spec@2 fields
- touching TOWER.md (L0)

## Acceptance

- cd pilot/worktrees/PILOT-053/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 601 + 新增用例数（main 基线 601）
- 失败夹具：首轮 MERGE_BLOCKED → envelope CORRECTION_REQUIRED；envelope-new 重写后状态仍 CORRECTION_REQUIRED；再 merge 成功；state-verify drift []
- DRAFT 信封直接 merge → exit 2 单 JSON、无 MERGE_START、ledger 不变；MERGED 信封 envelope-new → exit 2
- WAITING 信封重写保留 WAITING；新信封仍 DRAFT；正常首次 merge 不回归
- replay 单元：ENVELOPE_NEW 两次不把 WAITING/CORRECTION_REQUIRED/MERGED 重置为 DRAFT；未知状态不崩
- ARCHITECTURE.md 含信封恢复契约且 arch-check exit 0；shape-check exit 0；spec-lint 6/6
- 旧码对照：main 对 DRAFT 信封 merge 放行、重信把状态折成 DRAFT；新码拒绝/保留。证据写进 scratch/probe-old-code.txt
- 真实塔：053 合并后重跑 `post-merge --envelope ENV-PILOT-052 --result PASS` → 9/9、state-verify drift []、profile-check exit 0
- 真实塔：建信封前 tasks=53/envelopes=51，建信封后 53/52；verify-ledger 0 error；coverage 27/27
- git -C pilot/worktrees/PILOT-053 diff --name-only main..HEAD 恰三个 allowed_paths
