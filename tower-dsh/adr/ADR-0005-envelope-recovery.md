---
schema: tower/adr@1
id: ADR-0005
title: "失败后重封信封：保留状态，merge 校验信封"
status: accepted
date: 2026-10-31
deciders:
  - mac
related_cards:
  - PILOT-053
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/ARCHITECTURE.md
---

# ADR-0005 — 失败后重封信封：保留状态，merge 校验信封

## 背景

052 首轮 PR CI 失败（WIRING probe 在 GitHub runner 上 exit 2），merge 记录 `MERGE_START` + `MERGE_BLOCKED`，信封进入 `CORRECTION_REQUIRED`。修 CI 后重新 `envelope-new`，新 `ENVELOPE_NEW` 把信封折成 `DRAFT`；队列里已有 `QUEUE_ADD`，`queue-add` 拒绝重加，第二次 `MERGE_START` 从 `DRAFT` 开始。`merge` 只看队列 `WAITING`，不看信封状态，于是放行；`state-verify` 重放报 `illegal_transition`（MERGE_START 来源 DRAFT），PROFILE 的 STATE probe 连带失败，052 post-merge 红。

## 决策

1. **重放**：`ENVELOPE_NEW` 命中已有信封时**保留已有状态**（`WAITING`/`CORRECTION_REQUIRED`/`MERGED`），只有全新信封才置 `DRAFT`。
2. **重信命令**：`envelope-new` 对 `MERGED` 信封 exit 2（不能重开已合并）；对已有 `WAITING`/`CORRECTION_REQUIRED` 保留状态并更新 head；新信封写 `DRAFT`。
3. **入队命令**：`queue-add` 首次入队或修复半写时，把 envelope 文件状态从 `DRAFT` 置 `WAITING`；正常首次 merge 走 `DRAFT → queue-add WAITING → merge`。
4. **merge 入口**：在读队列之后、写 `MERGE_START` 之前，要求信封文件状态 ∈ {`WAITING`, `CORRECTION_REQUIRED`}，且队列条目 WAITING；`DRAFT`/`MERGED` → exit 2，零 ledger 写入。
5. **不加事件类型、不改 ledger**：修复的是折叠/入口语义，不重写历史。

## 替代方案

- **允许 MERGE_START 从 DRAFT**：否。会把“未入队的草稿”也放进来，是放宽门。
- **重写 supervision ledger 删除第二次 MERGE_START**：否。哈希链不可改。
- **重建 052 卡**：否。代码已合并，重建不能修历史状态，且代价更大。

## 后果

正面：失败→修复→重封信封→再 merge 的恢复路径可走通；state-verify 不再误报；merge 不会从 DRAFT 开始。

负面：重封信封必须保留状态，`envelope-new` 的“重写”语义变复杂；`MERGED` 信封不能重开（只能新卡）。

## 关联卡

- `PILOT-053` — 落地本决策的卡（052b 热修）。

## 关联文件

- `tower-dsh/tools/towerctl.py` — replay / envelope-new / merge。
- `tower-dsh/ARCHITECTURE.md` — 信封恢复契约。
