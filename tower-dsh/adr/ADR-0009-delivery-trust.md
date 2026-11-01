---
schema: tower/adr@1
id: ADR-0009
title: "交付信任加固：ID 不复用、结构化 REVIEW、验收分项"
status: accepted
date: 2026-11-01
deciders:
  - mac
related_cards:
  - PILOT-057
  - PILOT-058
  - PILOT-059
related_files:
  - tower-dsh/tools/towerctl.py
---

# ADR-0009 — 交付信任加固

## 背景

043/055 复用旧 id 导致旧 `TASK_NEW` 留在 ledger、worktree/CI `record_missing`、二次 `DISPATCH` `illegal_transition`，最后靠改号绕开。055 又出现 reviewer PASS 后证据仍是旧 HEAD 的返工。checkback/accept 没有 A/M 分项，非关键人工项会卡整卡，失败与待验也容易混在 prose 里。

SteerLine 的三条做法值得借（不复制代码/文本）：Task ID 永不复用；review/validation/merge gate 绑同一 head/base；acceptance 分自动/人工、非关键人工可显式后置。

## 决策

1. **PILOT-057 — ID 注册表**：`state/TASK_IDS.json` 记录所有已用/保留 ID（reserved/active/closed/void）；`task-new` 对任何已注册 ID exit 2 零写入；`task-ids-init` 回填历史，`task-ids-reserve` 为草稿占号；条目永不删除。
2. **PILOT-058 — 结构化 REVIEW**：`checkback` 写 `REVIEW.json`（head/base/scope/findings/verdict/reviewer/at）；`merge-check` 要求 PASS 且 `review.head == envelope head`；`merge --mode pr` 使用 `--match-head-commit`；head 变化后旧 review 失效。
3. **PILOT-059 — 验收分项**：每张新卡 `ACCEPTANCE.json` + `ACCEPTANCE.md`（A/M）；`accept` 要求所有 auto passed、任何 failed 拒绝；manual pending 仅在 owner 显式 `--allow-manual-pending` 且每项有 note 时允许。旧卡不回溯。

## 替代方案

- **只加文档规则**：否。043/055 已证明 prose 不够，必须有工具门。
- **引入 SteerLine 的 Go/SQLite/Web/Runner 栈**：否。木塔的账本/双塔/四闸更重，不增加服务面。
- **manual pending 默认放行**：否。owner 四闸不能降级。

## 后果

正面：ID 复用类返工消失；review 与 envelope/PR head 硬绑定；验收可读、可机检，人工项不再整卡阻塞。

负面：每张新卡多两个文件；`task-new`/`checkback`/`accept` 多一道读写；旧卡与 057 前已合并卡不回溯，存在一段“无 REVIEW/ACCEPTANCE”的历史。

## 关联卡

- `PILOT-057`、`PILOT-058`、`PILOT-059`。

## 关联文件

- `tower-dsh/tools/towerctl.py` — 三个命令/门。
- `tower-dsh/state/TASK_IDS.json` — ID 注册表。
- `tower-dsh/tasks/PILOT-057/ACCEPTANCE.md` — 059 的样例。
