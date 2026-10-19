---
schema: tower/policy@1
id: POL-CHANGE-LEVELS
title: 变更分级 — L0 / L1 / L2 / L3
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# POL-CHANGE-LEVELS — 变更分级

## 1. 范围

适用于 `tower-dsh` 的所有变更：从文档到门禁代码到任务实现。
分级决定“走哪条审批链”，**不豁免红线**。本文件自身是 L0。

## 2. 条款

| ID | 条款 | 级别 | enforcement | 判定方法 |
|---|---|---|---|---|
| C-01 | L0 变更（`TOWER.md`、`AGENTS.md`、`shared/AUTHORITY_MODEL.json`、`shared/PROJECT_PROFILE.json`、`RED-LINES.md`、`CHANGE-LEVELS.md`、`primary/CURRENT_STATE.json`、`supervision/CURRENT_STATE.json`、`ledger/*`）必须 owner 逐次批准 | MUST | owner-gate | 检查变更文件是否在 L0 清单内，且有 owner 授权 |
| C-02 | L1 变更（`tools/towerctl.py`、`tools/spec_lint.py`、模板、schema、门禁逻辑、`handoffs/*/package.json`）必须经任务卡 + 独立 reviewer + 合并门 | MUST | tool-check | 检查任务卡、review PASS、envelope 与 post-merge |
| C-03 | L2 变更（单任务实现、任务卡、交付/评审/收口、`tasks/*`）必须经任务卡，closeout 前需 PASS review | MUST | tool-check | 检查 `record.json` 的 review verdict 与状态 |
| C-04 | L3 变更（错字、链接、格式、注释、非语义说明）可直接改，但必须留 commit 说明 | MAY | review-check | 检查 commit message 与变更范围 |
| C-05 | 判级有争议时就高不就低 | MUST | review-check | 检查争议项的最终级别是否不低于合理级别 |
| C-06 | 自报级别必须由 reviewer 复核；复核不一致按更高级处理 | MUST | review-check | 检查 review 是否记录级别与复核结论 |
| C-07 | L0 变更不得直接写 main | MUST NOT | owner-gate | 检查是否存在 owner 闸记录 |
| C-08 | L1 变更不得绕过 envelope + merge 门直接写 main | MUST NOT | tool-check | 检查 merge 是否有 envelope 与 queue 记录 |
| C-09 | L3 变更不得触碰 L0/L1 文件 | MUST NOT | review-check | 检查 L3 commit 的变更清单 |
| C-10 | 分级不得被用来绕过红线 | MUST NOT | owner-gate | 对照 `RED-LINES.md` 逐条检查 |

## 3. 证据

- 级别声明：任务卡 `authority` 与 `CHANGE-LEVELS.md` 的对应关系；
- 审批链：spec 批准、review verdict、envelope、merge、post-merge 事件；
- 复核：reviewer 在 `REVIEW.md` 中写明级别复核结论。

## 4. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | 级别报低 | 按更高一级重走审批链 |
| FM-02 | L0 未授权 | 停止，报告 owner |
| FM-03 | L1 绕过合并门 | 停止，补 envelope 或回滚（由 owner 决定） |
| FM-04 | L3 触碰 L0/L1 | 按 L1/L0 重走 |

## 5. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版（散文）；同日改为 `tower/policy@1` 条款表 | owner |
