# Phase 2 — Dual Tower Pilot Report

- Status: **complete**
- Date: 2026-10-19
- Tower: `tower-dsh`
- Envelope: `ENV-PILOT-001`
- Task: `PILOT-001` — Ledger SHA-256 哈希链模块与篡改检测

## 结果

| 项 | 值 |
|---|---|
| Implementation head A | `c8af539afbba4666d7cbdc6a5f5eb21538e14709` |
| Envelope head B | `ed28ac618f524db7d5db426db3839cd185a6da11` |
| Merge commit | `9fb5ba243f5cf03f7ccafb0eb381793770835db2` |
| Merge mode | `--no-ff` |
| Merge checks | **10/10 PASS** |
| Post-merge tests | **14/14 PASS**，exit 0 |
| Working tree | clean |
| Final status | **POST_MERGE_VERIFIED** |
| Production access | none |

## 合并门（全部通过）

1. repository exists
2. branch head == envelope head
3. envelope parent == implementation head
4. envelope commit only changes envelope path
5. base `main` is ancestor of implementation
6. task accepted/closed
7. review PASS
8. reviewer != executor
9. evidence hashes valid
10. queued in `MERGE_QUEUE.json`

## 本次新增

- `shared/PROJECT_PROFILE.json` → `PHASE_2_DUAL_TOWER`
- `shared/AUTHORITY_MODEL.json` → 双塔角色 + 分离不变量
- `supervision/CURRENT_STATE.json`
- `supervision/MERGE_QUEUE.json`
- `supervision/envelopes/ENV-PILOT-001.json`
- `supervision/registries/merge-ledger.json`
- `supervision/reviews/ENV-PILOT-001-post-merge.txt`
- `ledger/supervision.jsonl`
- `towerctl` 命令：`supervision-init`、`supervision-phase`、`supervision-status`、`envelope-new`、`queue-add`、`merge-check`、`merge`、`post-merge`、`task-next`
- Skill：`control-tower` 更新；新增 `control-tower-supervisor`

## 审计

- `ledger/supervision.jsonl`：`SUPERVISION_INIT` → `ENVELOPE_NEW` → `QUEUE_ADD` → `MERGE_START` → `MERGE` → `POST_MERGE_VERIFIED` → `SUPERVISION_PHASE`
- `supervision/registries/merge-ledger.json`：1 条 merge 记录
- Post-merge 测试输出：`supervision/reviews/ENV-PILOT-001-post-merge.txt`

## 已知缺口

1. **本地 git，不是远端 PR**：本轮用本地 branch + envelope + `--no-ff` merge；没有 GitHub PR、服务端分支保护或 `gh` 流程。真实项目接入时要补 remote binding。
2. **角色是程序性分离**：`merge --role supervisor` 是 CLI 约定，不是密码学身份；生产级要独立 OS 账号或签名信封。
3. **Envelope 证据列表 5 项**：任务 record 有 6 项（含 `commit.txt`）；信封里没列 `commit.txt`，但 `merge-check` 校验的是任务 record，安全门未受影响。
4. **还没有 `tower-primary`/`tower-supervisor` preset**：本轮用 skill + 两个独立会话/子 agent。
5. **Console 未做**：Phase 4。

## 下一步

- Phase 3：project-handoff v2.1（§0/§0a + 七节包 + claim）
- 或接一个真实项目任务，用同一套 `towerctl` 再跑一单
- 或补远端 PR/分支保护绑定
