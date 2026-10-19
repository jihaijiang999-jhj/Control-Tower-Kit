---
schema: tower/policy@1
id: POL-RED-LINES
title: 红线清单 — 触碰即停
owner: mac
version: 1
enforcement_legend: tool-check | review-check | owner-gate
---

# POL-RED-LINES — 红线清单

## 1. 范围

适用于 `tower-dsh` 的所有角色（owner / primary / supervision / executor / reviewer），
覆盖四闸与硬停条款。任何条款被触碰：**立即停止**，不得自行修复、不得重试、不得“先做了再报”。
本文件是 L0 政策；`towerctl spec-lint` 校验其结构。

## 2. 条款

| ID | 条款 | 级别 | enforcement | 判定方法 |
|---|---|---|---|---|
| C-01 | merge 只能由 owner 逐次授权；Phase 2 起由 supervision 执行 | MUST | owner-gate | 检查 merge 是否 `--role supervisor` 且 supervisor ≠ primary，并有 owner 授权记录 |
| C-02 | 任何离开本机的调用只能由 owner 逐次授权 | MUST | owner-gate | 检查外部调用是否有 owner 授权；未授权即红线 |
| C-03 | 部署、发布、生产读写、数据迁移、退役默认 `no_access` | MUST NOT | owner-gate | 检查 `PROJECT_PROFILE.automatic_authority_ceiling.production_track` 是否为 `no_access` |
| C-04 | 写 L0 文档到 main 只能由 owner 逐次授权 | MUST | owner-gate | 对照 `CHANGE-LEVELS.md` 的 L0 清单与 owner 授权记录 |
| C-05 | 未授权 merge、强推、改远端受保护分支 | MUST NOT | owner-gate | 检查 git 操作与授权记录 |
| C-06 | 未授权外部调用，含把本地内容上传到未批准服务 | MUST NOT | owner-gate | 检查网络/上传行为与授权记录 |
| C-07 | 部署、生产读写、数据迁移、退役 | MUST NOT | owner-gate | 检查命令与目标环境 |
| C-08 | 手改 `primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、`supervision/*.json`、`ledger/*.jsonl`、`tasks/*/record.json` | MUST NOT | review-check | 检查变更是否全部经 `towerctl`；`git diff` 中状态文件是否由工具产生 |
| C-09 | 伪造证据：改证据文件、补造 ledger 事件、用“文件存在”代替“检查通过” | MUST NOT | tool-check | `check_evidence` 与 `verify-ledger` 复算哈希；ledger 链校验 |
| C-10 | executor 写 `allowed_paths` 之外的文件；reviewer 改工作树 | MUST NOT | review-check | 对比 `git diff --name-only` 与 `allowed_paths`；reviewer 只读自证 |
| C-11 | 自审自批：executor = reviewer；primary = merge 批准者；作者 = 验收者 | MUST NOT | tool-check | `checkback` 拒绝 reviewer == executor；merge 拒绝 supervisor == primary |
| C-12 | 读取或回显凭据（token、私钥、密码、cookie） | MUST NOT | review-check | 检查命令与输出；凭据零回显 |
| C-13 | 把聊天记录当状态，或在没有证据时声明“完成” | MUST NOT | review-check | 完成声明必须引用 ledger 事件与证据哈希 |
| C-14 | 跳过闸点：`spec_gate != PASS` 时 dispatch、未 queued 时 merge、未 `POST_MERGE_VERIFIED` 时宣布完成 | MUST NOT | tool-check | `dispatch` 校验 spec_gate；`merge` 校验 queue；`post-merge` 校验完成态 |
| C-15 | 触碰红线后必须停止、记录、报告 owner，并等待口令 | MUST | owner-gate | 检查是否有 STOP 记录与 owner 报告 |
| C-16 | 已产生副作用时必须保留现场，不清理、不回滚 | MUST | owner-gate | 检查现场是否保留，处置是否由 owner 决定 |

## 3. 证据

- 授权记录：`primary/registries/`、`supervision/registries/` 与 ledger 中的 owner 决定；
- 红线条款的执行证据：`dispatch` / `merge` / `checkback` / `verify-ledger` 的输出；
- 触碰记录：ledger 事件 + 报告 owner 的原始消息（附证据）。

## 4. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | 触碰任一条款 | STOP：不修、不重试、不掩盖；记录后报告 owner |
| FM-02 | 已产生副作用 | 保留现场，由 owner 决定处置；不得自行回滚 |
| FM-03 | 条款与分级冲突 | 按红线优先；分级不得豁免红线 |
| FM-04 | 不确定是否触碰 | 按“已触碰”处理，先停再问 |

## 5. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版（散文）；同日改为 `tower/policy@1` 条款表 | owner |
