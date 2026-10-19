---
schema: tower/workflow@1
id: WF-HANDOFF
title: 交接流 — project-handoff v2.1 包的生成、接收与激活
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-HANDOFF — 交接流

## 1. 范围

适用于 `tower-dsh` 的一次控制塔交接：交出方生成 v2.1 包 → 接收方 claim → 首验回执 →
交出方 accept → 接收方 activate 成为新 controller。
不覆盖任务执行（见 `WF-TASK`）与合并（见 `WF-MERGE`）。

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `PREPARED` | 包已生成，含 §0/§0a/§1–§7 与自查 | 否 |
| `READY_FOR_RECEIVER` | 接收方已 claim，包自检通过 | 否 |
| `RECEIVED` | 接收方已写首验回执 | 否 |
| `ACCEPTED` | 交出方已接受接收方 | 否 |
| `ACTIVE` | 接收方已激活，成为新 controller | 是 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `PREPARED` | 当前状态可交接；`handoff-check` 全过 | `handoff-new` | `HANDOFF.md`、`SELF-CHECK.md`、`package.json` | 拒绝生成 |
| TR-02 | `PREPARED` | `READY_FOR_RECEIVER` | receiver ≠ source；21 项自检全过 | `handoff-claim` | `CLAIM.json` | 拒绝 claim |
| TR-03 | `READY_FOR_RECEIVER` | `RECEIVED` | controller 与 claim 一致；自检仍过 | `handoff-receipt` | `RECEIPT.md` | 拒绝回执 |
| TR-04 | `READY_FOR_RECEIVER`\|`RECEIVED` | `ACCEPTED` | controller 与 claim 一致 | `handoff-accept` | `ACCEPTANCE.json` | 拒绝接受 |
| TR-05 | `ACCEPTED` | `ACTIVE` | `acceptance.receiver` 与 controller 一致 | `handoff-activate` | `ACTIVATION.json` + primary 状态 | 拒绝激活 |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | 接收方 controller 不得等于交出方 controller | tool-check |
| INV-02 | `HANDOFF.md` 与 `SELF-CHECK.md` 的 SHA-256 必须与 package 记录一致 | tool-check |
| INV-03 | §0 的 main SHA / worktree head / queue / task / clean 必须与生成时一致 | tool-check |
| INV-04 | 必须经过 claim → receipt → accept → activate，不得跳步 | tool-check |
| INV-05 | 只有 ACTIVE 之后，接收方才是新 controller | owner-gate |
| INV-06 | 任何 §0 漂移必须如实上报，不得自行修正权威事实 | review-check |
| INV-07 | claim / accept / activate 不得重复执行 | review-check |

## 5. 证据

- 包：`handoffs/<pkg>/HANDOFF.md`、`SELF-CHECK.md`、`package.json`（含文件哈希与 state 快照）；
- 状态：`CLAIM.json`、`RECEIPT.md`、`ACCEPTANCE.json`、`ACTIVATION.json`；
- 事件：`ledger/primary.jsonl` 的 `HANDOFF_NEW` / `HANDOFF_CLAIM` / `HANDOFF_RECEIPT` / `HANDOFF_ACCEPT` / `HANDOFF_ACTIVATE`；
- 自检：`handoff-check --package <pkg>` 的 21 项清单。

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | 包哈希不符 | 重建整包；不得局部修补 |
| FM-02 | §0 任一锚点漂移 | 停止，报告 owner；不得改 §0 掩盖 |
| FM-03 | receiver 与 source 相同 | 换 controller |
| FM-04 | controller 与 claim 不一致 | 用 claim 的 controller 或重新 claim |
| FM-05 | 未 accept 就 activate | 拒绝；补 accept |
| FM-06 | 重复 claim | 停止；报告 owner，不重复执行 |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版，按 HANDOFF-PILOT-001 实际流转编写 | owner |
