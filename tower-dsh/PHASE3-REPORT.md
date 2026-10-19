# Phase 3 — project-handoff v2.1 Pilot Report

- Status: **complete**
- Date: 2026-10-19
- Package: `HANDOFF-PILOT-001`
- Mechanism: `project-handoff v2.1`
- Source controller: `ctl-8cd51ef9-2972-415a-b1db-d8d37afdde82`
- Receiver controller: `ctl-phase3-receiver-001`
- Final state: **ACTIVE**（receiver 已接管 primary）

## 结果

| 项 | 值 |
|---|---|
| 包目录 | `handoffs/HANDOFF-PILOT-001/` |
| HANDOFF.md | §0 / §0a / §1–§7 全齐 |
| SELF-CHECK.md | 7/7 已勾选 |
| handoff-check | **21/21 PASS** |
| claim | `READY_FOR_RECEIVER` |
| receipt | `RECEIVED` |
| accept | `ACCEPTED` |
| activate | **ACTIVE** |
| startup / wiring | 通过；`WIRED` |
| primary | `ctl-phase3-receiver-001` |
| phase | `HANDOFF_ACTIVE` |

## 状态机

```text
PREPARED
  → READY_FOR_RECEIVER   (receiver claim)
  → RECEIVED             (receiver receipt)
  → ACCEPTED             (source accept)
  → ACTIVE               (receiver activate)
```

## 包内容

```text
handoffs/HANDOFF-PILOT-001/
├─ HANDOFF.md        # §0 实值 / §0a 漂移 / §1–§7
├─ SELF-CHECK.md     # 交出前自查
├─ package.json      # 包身份、文件哈希、state 快照、状态机
├─ CLAIM.json        # receiver claim
├─ RECEIPT.md        # receiver 首验回执
├─ ACCEPTANCE.json   # source 接受
└─ ACTIVATION.json   # receiver 激活
```

## Ledger

`ledger/primary.jsonl`：

- seq 13 `HANDOFF_NEW`
- seq 14 `HANDOFF_CLAIM`
- seq 15 `HANDOFF_RECEIPT`
- seq 16 `HANDOFF_ACCEPT`
- seq 17 `HANDOFF_ACTIVATE`（首次）
- seq 18 `HANDOFF_ACTIVATE`（幂等重跑，修正 package status）

## 新增能力

`towerctl`：

- `handoff-new` — 从当前状态生成 v2.1 包
- `handoff-check` — 校验 §0/§0a/§1–§7、self-check、哈希、漂移
- `handoff-claim` — receiver claim
- `handoff-receipt` — receiver 首验回执
- `handoff-accept` — source 接受
- `handoff-activate` — receiver 激活（幂等）
- `handoff-status` — 包状态

## 已知缺口

1. **receiver 是 staged controller**：`ctl-phase3-receiver-001` 由 receiver subagent 承担，不是持久 DSH 会话；真实换窗需要新开一个 DSH session，再跑 `startup`。
2. **文档未同步**：`TOWER.md` / `README.md` 仍写 Phase 2；新 controller 接管后应更新为 Phase 3 / HANDOFF_ACTIVE。
3. **本地 git**：没有远端 PR/分支保护，handoff 只覆盖本地状态。
4. **程序性身份**：controller id 是文件约定，不是密码学身份；生产级要独立 OS 账号或签名。
5. **`handoff-activate` 幂等性**：首次实现未更新 `package.json` status，已修复并重跑；后续不会再出现。

## 下一步

- 新 DSH 会话：从 `handoffs/HANDOFF-PILOT-001/HANDOFF.md` 起跑，作为 `ctl-phase3-receiver-001` 继续。
- 或 Phase 4：只读 Console。
- 或接真实项目任务，用同一套 `towerctl` 跑第二单。
- 或补远端 PR/分支保护，升级合并门。
