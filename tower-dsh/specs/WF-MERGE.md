---
schema: tower/workflow@1
id: WF-MERGE
title: 合并流 — 信封、串行队列与合并后验证
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-MERGE — 合并流

## 1. 范围

适用于 `tower-dsh` 中一次代码合并：主塔提交信封 → 监督塔入队 → 合并 → 合并后验证。
本流不生产实现，不修改候选代码；生产轨永远 `no_access`。

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `DRAFT` | 信封已生成，尚未入队 | 否 |
| `WAITING` | 已入唯一串行队列 | 否 |
| `MERGING` | 正在执行 merge（同一时刻只允许一个） | 否 |
| `MERGED` | merge 已完成，尚未验证 | 否 |
| `POST_MERGE_VERIFIED` | 合并后验证通过，才算完成 | 是 |
| `CORRECTION_REQUIRED` | 任一门失败，需纠正 | 否 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `DRAFT` | 任务 accepted/closed、review PASS | `envelope-new` | `supervision/envelopes/<id>.json` | 拒绝建信封 |
| TR-02 | `DRAFT` | `WAITING` | 信封存在且未入队 | `queue-add` | `MERGE_QUEUE.json` | 拒绝入队 |
| TR-03 | `WAITING` | `WAITING` | 结构门全部通过 | `merge-check` | 检查清单 | 报告失败项，不改状态 |
| TR-04 | `WAITING`\|`CORRECTION_REQUIRED` | `MERGING` | 队列项状态合法；当前分支 == base | `merge` | ledger `MERGE_START` | 置 `CORRECTION_REQUIRED` |
| TR-05 | `MERGING` | `MERGED` | `git merge` 返回 0 | `merge` | merge commit + `merge-ledger.json` | 中止并置 `CORRECTION_REQUIRED` |
| TR-06 | `MERGED`\|`CORRECTION_REQUIRED` | `POST_MERGE_VERIFIED` | 测试通过、实现是 base 祖先、信封在 base、工作树干净 | `post-merge --result PASS` | `supervision/reviews/<id>-post-merge.txt` | 置 `CORRECTION_REQUIRED` |
| TR-07 | `MERGED`\|`CORRECTION_REQUIRED` | `CORRECTION_REQUIRED` | 任一检查失败 | `post-merge` | ledger `POST_MERGE_FAILED` | 保留 merge commit，等待纠正 |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | 信封 head `B` 的父提交必须等于实现 head `A` | tool-check |
| INV-02 | `A..B` 的改动只能包含 `envelope_path` | tool-check |
| INV-03 | base 必须是 `A` 的祖先 | tool-check |
| INV-04 | merge 时当前分支必须等于 `base` | tool-check |
| INV-05 | 任务必须 accepted/closed，review PASS，reviewer ≠ executor，证据哈希有效 | tool-check |
| INV-06 | 同一时刻只允许一个 `MERGING`；队列串行 | tool-check |
| INV-07 | `MERGED` 不等于完成，必须 `POST_MERGE_VERIFIED` | tool-check |
| INV-08 | primary 不得执行 merge；merge 只能 `--role supervisor` | owner-gate |
| INV-09 | 生产、部署、外部调用永远不授权 | owner-gate |

## 5. 证据

- 信封：`supervision/envelopes/<id>.json`（A/B、branch、base、证据列表）；
- 队列：`supervision/MERGE_QUEUE.json`；
- 合并账本：`supervision/registries/merge-ledger.json`；
- 合并后验证：`supervision/reviews/<id>-post-merge.txt`；
- 事件：`ledger/supervision.jsonl` 的 `ENVELOPE_NEW` / `QUEUE_ADD` / `MERGE_START` / `MERGE` / `POST_MERGE_VERIFIED`。

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | 结构门失败 | 置 `CORRECTION_REQUIRED`，退回修正；不得带病合并 |
| FM-02 | 当前分支不是 base | 切回 base 或重建信封；不得强行 merge |
| FM-03 | git merge 冲突 | `merge --abort`，置 `CORRECTION_REQUIRED` |
| FM-04 | post-merge 失败 | 置 `CORRECTION_REQUIRED`；修正后可从该状态重试 |
| FM-05 | 队列出现两个 MERGING | 停止，报告 owner；不得并行合并 |
| FM-06 | 误把 MERGED 当完成 | 退回 post-merge；不得对外宣称完成 |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版，按 PILOT-002/003 后的实际行为编写 | owner |
