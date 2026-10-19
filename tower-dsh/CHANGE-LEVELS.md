# 变更分级 — L0 / L1 / L2 / L3

> 性质：L0 级文档（本文件自身也是 L0）。
> 规则：**判级有争议时就高不就低**；自报级别由 reviewer 复核，复核不一致按更高级处理。

## 分级表

| 级别 | 范围 | 谁批 | 证据要求 | 能否直接改 main |
|---|---|---|---|---|
| **L0** | `TOWER.md`、`AGENTS.md`、`shared/AUTHORITY_MODEL.json`、`shared/PROJECT_PROFILE.json`、`RED-LINES.md`、`CHANGE-LEVELS.md`、`primary/CURRENT_STATE.json`、`supervision/CURRENT_STATE.json`、`ledger/*` | owner 逐次 | 变更说明 + 前后 diff + 影响面 | 否（owner 闸） |
| **L1** | `tools/towerctl.py`、`templates/*`、`tools/templates/*`、schema、门禁逻辑、`handoffs/*/package.json` | primary + 独立 reviewer；合并由 supervision | 任务卡 + 测试 + 证据哈希 + 独立复核 | 否（走 envelope + merge 门） |
| **L2** | 单个任务的实现、任务卡、交付/评审/收口文档、`tasks/*` | primary（closeout 前需 PASS review） | 任务卡验收条款逐条可执行 | 否（在 worktree 内，经合并门） |
| **L3** | 纯文档修补：错字、链接、格式、注释、非语义说明 | 执行者直接改 | 变更记录（commit message 足够） | 可以，但不得触碰 L0/L1 文件 |

## 判定示例

| 改动 | 级别 | 理由 |
|---|---|---|
| 改 `cmd_merge` 的分支断言 | L1 | 门禁逻辑 |
| 新增 `towerctl doctor` | L1 | 新命令，改工具面 |
| 给任务卡补一条验收 | L2 | 任务级 |
| 改 `RED-LINES.md` 一条红线 | L0 | 宪法级 |
| 更新 `PROJECT_PROFILE.phase` | L0 | 权威事实 |
| 修 README 错字 | L3 | 非语义 |
| 更新 skill 的 Phase 描述 | L1 | 操作手册，影响所有会话行为 |
| 给 `tasks/PILOT-001/CLOSEOUT.md` 追加补记 | L2 | 任务文档，不改原文 |

## 强制顺序

```text
L0：owner 口令 → 改 → 记 ledger（如适用）→ 报告
L1：任务卡 → spec-approve → dispatch → deliver(证据) → 独立 review → accept → close → envelope → queue → merge → post-merge
L2：任务卡 → dispatch → deliver → review → accept → close
L3：直接改 → commit 说明
```

## 与红线的边界

分级不是绕闸工具：任何 L1/L2/L3 改动都不得触碰 `RED-LINES.md` 第 2 节任一条。
