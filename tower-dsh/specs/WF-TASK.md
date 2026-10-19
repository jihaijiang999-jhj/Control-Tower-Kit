---
schema: tower/workflow@1
id: WF-TASK
title: 任务流 — 任务卡从创建到收口
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-TASK — 任务流

## 1. 范围

适用于 `tower-dsh` 中单张任务卡（`tasks/<id>/`）的完整生命周期：
创建 → spec 批准 → 派发 → 交付 → 独立复核 → 接受 → 收口。
不覆盖合并（见 `WF-MERGE`）与交接（见 `WF-HANDOFF`）。

所有状态变更必须经 `towerctl`；聊天记录不是状态。

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `ready` | 任务卡已建，等待 spec 批准与派发 | 否 |
| `dispatched` | 已派发给 executor，worktree 已锁定 | 否 |
| `delivered` | executor 已交付，证据已入 `tasks/<id>/evidence/` | 否 |
| `reviewed` | 独立 reviewer 给出 PASS | 否 |
| `rework` | reviewer 给出 FAIL，等待返工 | 否 |
| `accepted` | owner 接受，decision 已记录 | 否 |
| `closed` | closeout 已写，任务结束 | 是 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `ready` | spec 满足 `tower/spec@1`；worktree 存在 | `task-new` | `spec_sha256` 写入 record | 拒绝建卡 |
| TR-02 | `ready` | `ready` | 批准人 ≠ executor | `spec-approve` | ledger `SPEC_APPROVED` | 拒绝批准 |
| TR-03 | `ready` | `ready` | spec 哈希未变 | `check` | `spec_gate=PASS` + ledger `CHECK` | 返回错误，不置 PASS |
| TR-04 | `ready`\|`rework` | `dispatched` | `spec_gate=PASS`、spec 哈希一致、`TASK.md` 存在、worktree 存在 | `dispatch` | ledger `DISPATCH` | 拒绝派发 |
| TR-05 | `dispatched`\|`delivered`\|`rework` | `delivered` | 证据文件存在且可哈希 | `deliver` | `DELIVERY.md` + 证据 SHA-256 | 拒绝交付 |
| TR-06 | `delivered`\|`reviewed`\|`rework` | `reviewed` | reviewer 非空且 ≠ executor | `checkback --verdict PASS` | `REVIEW.md` + ledger `CHECKBACK` | 拒绝复核 |
| TR-07 | `delivered`\|`reviewed`\|`rework` | `rework` | 同上 | `checkback --verdict FAIL` | `REVIEW.md` | 进入返工 |
| TR-08 | `reviewed`\|`accepted` | `accepted` | review PASS；证据 0 项或哈希不符则拒绝 | `accept` | `decision` + ledger `ACCEPT` | 拒绝接受 |
| TR-09 | `accepted` | `closed` | 证据有效；`TASK.md` 存在 | `close` | `CLOSEOUT.md` + ledger `CLOSEOUT` | 拒绝收口 |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | reviewer 必须非空且不等于 executor | tool-check |
| INV-02 | 任务卡创建后 spec 冻结；`spec_sha256` 变化即视为 spec_gate 失效 | tool-check |
| INV-03 | accept / close 时证据非空且逐条 SHA-256 匹配 | tool-check |
| INV-04 | executor 只写 `allowed_paths` 内的文件 | review-check |
| INV-05 | spec 批准人不得是 executor；作者不得自审 | owner-gate |
| INV-06 | 状态只能沿本表转移，不得跳步（如 ready → accepted） | tool-check |
| INV-07 | 每个状态变更都必须留下 ledger 事件 | tool-check |

## 5. 证据

- spec：`pilot/<ID>.spec.json` 的 SHA-256（record 内 `spec_sha256`）；
- 交付：`tasks/<id>/evidence/` 下逐文件 SHA-256 + 字节数；
- 复核：`REVIEW.md`（reviewer、verdict、时间、证据清单）；
- 收口：`CLOSEOUT.md`（范围、证据、决策、merge 状态）；
- 事件：`ledger/primary.jsonl` 的 `SPEC_APPROVED` / `DISPATCH` / `DELIVER` / `CHECKBACK` / `ACCEPT` / `CLOSEOUT`。

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | `dispatch` 报 spec gate 未通过 | 重建任务卡或补 `spec-approve`；不得手改 record |
| FM-02 | spec 哈希不符 | 重建任务卡；不得原地改 spec |
| FM-03 | reviewer 与 executor 相同 | 换独立 reviewer |
| FM-04 | 证据哈希不符 | 重新 `deliver`；不得改证据副本 |
| FM-05 | executor 中途失联 | 以 aborted 记录为证据 → `deliver` → `checkback FAIL` → 重新 `dispatch` |
| FM-06 | 误改状态文件 | 停止，报告 owner；不得用第二次写入掩盖 |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版，按 PILOT-002/003/006 后的实际行为编写 | owner |
