---
schema: tower/workflow@1
id: WF-LEDGER
title: 账本流 — 追加式事件、哈希链与校验
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-LEDGER — 账本流

## 1. 范围

适用于 `ledger/primary.jsonl` 与 `ledger/supervision.jsonl` 的写入与校验：
单写者锁、哈希链、legacy 前缀兼容、`verify-ledger`。
账本是唯一历史；聊天记录不是历史。

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `empty` | 账本不存在或为空 | 否 |
| `legacy` | 只有无哈希的历史行，或尚未追加第一条哈希行 | 否 |
| `chained` | 至少一条哈希行，且链完整 | 否 |
| `broken` | 校验失败（篡改、断号、链断） | 否 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `empty` | 目录可写 | `init` | `ledger/primary.jsonl` | 拒绝初始化 |
| TR-02 | `empty` | `chained` | 无历史行 | 任意写事件命令 | `prev_hash=GENESIS` 的首条哈希行 | 写入失败 |
| TR-03 | `legacy` | `chained` | legacy 末行完整且以换行结尾 | 任意写事件命令 | 首条哈希行，`prev_hash=legacy 锚点` | 拒绝追加 |
| TR-04 | `chained` | `chained` | 持有单写者锁 | 任意写事件命令 | 新事件 `prev_hash=上一条 hash` | 超时则中止 |
| TR-05 | `empty` | `legacy` | 导入历史无哈希行 | 外部导入（非本工具） | 原始行 | 不适用 |
| TR-06 | `chained`\|`legacy` | `broken` | 校验发现篡改/断号/链断 | `verify-ledger` | 错误清单 | 报告 owner，停止写入 |
| TR-07 | `broken` | `broken` | 未修复 | `verify-ledger` | 错误清单 | 仍报错 |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | `seq` 从 1 连续递增，不得断号或重复 | tool-check |
| INV-02 | `hash = sha256(canonical(event 去掉 hash))`，canonical 为 key 排序、紧凑分隔、UTF-8、不转义非 ASCII | tool-check |
| INV-03 | `prev_hash` = 上一条的 `hash`；上一条无 hash 时 = 该行原始字节的 SHA-256；无上一条时 = `GENESIS` | tool-check |
| INV-04 | 追加必须在单写者锁内完成“读 max(seq) + 写一行” | tool-check |
| INV-05 | legacy 无哈希前缀只计数、不判失败；链开始后出现无哈希行即失败 | tool-check |
| INV-06 | 工具不得重写、截断或删除既有行 | review-check |
| INV-07 | 链断后只有 owner 能决定处置；工具不得自动“修复” | owner-gate |

## 5. 证据

- 事件行：`seq`、`at`、`type`、`actor`、`payload`、`prev_hash`、`hash`；
- 校验输出：`verify-ledger` 的 `ok`、`files.*.events`、`files.*.legacy_unhashed`、`errors`；
- 锁：`ledger/.lock`（瞬时存在，不提交）。

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | 锁等待超时 | 中止本次写入，exit 2；不得绕过锁 |
| FM-02 | 校验发现篡改 | 停止写入，保留现场，报告 owner |
| FM-03 | seq 断号 | 停止；不得补写序号 |
| FM-04 | 链开始后出现无哈希行 | 视为断裂；报告 owner |
| FM-05 | legacy 末行缺少换行 | 拒绝追加；先修复文件尾 |
| FM-06 | 并发写入导致 pending-delete 竞争 | 按锁竞争重试；持续失败则报告 |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版，按 PILOT-005/006 后的实际行为编写 | owner |
