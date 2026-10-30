---
schema: tower/adr@1
id: ADR-0003
title: "命令层接线：dispatch 必填 campaign + 门进 post-merge/CI"
status: accepted
date: 2026-10-30
deciders:
  - mac
related_cards:
  - PILOT-050
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/command/campaigns/C-2026-Q4-01.md
  - tower-dsh/ARCHITECTURE.md
---

# ADR-0003 — 命令层接线：dispatch 必填 campaign + 门进 post-merge/CI

## 背景

045–049 建了命令层（STRATEGY/campaign/brief/where）与架构脊柱（arch-check），但**指挥层没有接进执行路径**：`dispatch` 不要求 `campaign`，卡可以脱离战役被派发；`campaign-check`/`arch-check` 只在人手动跑，post-merge 与 CI 不跑；`campaign-check` 的 W1 把 44 张 campaign 之前的历史卡全报成孤儿，`--strict` 永远红。结果是：地图存在，但施工不受地图约束。

## 决策

1. **dispatch 必填 campaign**：当塔存在 active campaign 时，`dispatch --campaign <id>` 必填；校验 campaign 存在且 active、任务在 roadmap 中；写入 `record.dispatch.campaign` 与 `DISPATCH` payload。缺省/无效 → exit 2，零状态变更。没有 campaign 的夹具塔保持旧行为（legacy）。
2. **W1 的覆盖来源**：`task_forces` ∪ `record.dispatch.campaign` ∪ campaign 的 `legacy_cards`。`legacy_cards` 是 001–044 的**历史记账**（campaign 之前已闭环），不是追溯会员。
3. **W2 只数 open 卡**：`task_forces` 里已 closed 的卡不再占 WIP 预算；否则回填会制造假超限。
4. **post-merge 接线**：存在 `command/campaigns/*.md` / `arch/GATES.json` 时，post-merge 追加 `campaign-check` / `arch-check`；失败 → `CORRECTION_REQUIRED`；不存在 → 记 `skipped`/ok，不影响旧夹具。
5. **CI 接线**：`.github/workflows/tower-gate.yml` 在 `status` 之前增加 `arch-check` 与 `campaign-check`（非 strict），不加 `continue-on-error`。
6. **`--strict` 不在本卡开启**：W1 回填后 W1=0，但 W4 仍有 051/052 未建档；等 051 spec 落地后再决定。

## 替代方案

- **把 44 张历史卡塞进 `task_forces`**：否。它们不属于“命令层 v1”战役，塞进去是伪造会员，也会让 W2 预算失真。
- **把 `campaign` 加进 spec@2 必填**：否（本卡不做）。那是又一次 schema 变更；先用 dispatch 参数 + record 字段，等 051 再评估是否需要 spec 级声明。
- **现在开 `--strict`**：否。W4 未清零，会变成“红着接 CI”。

## 后果

正面：新卡必须挂战役才能派发；post-merge/CI 自动跑设计与战役门；W1 清零、W2 只数 open；历史卡诚实标为 legacy。

负面：dispatch 多一个参数（脚本/夹具需要适配）；`legacy_cards` 是手工维护的名单（本卡一次性回填 001–044）；`--strict` 仍红（W4），CI 只跑非 strict 版本；post-merge 对旧夹具是 opt-in，不能保证所有塔都接线。

## 关联卡

- `PILOT-050` — 落地本决策的卡。

## 关联文件

- `tower-dsh/tools/towerctl.py` — dispatch / campaign-check / post-merge。
- `tower-dsh/command/campaigns/C-2026-Q4-01.md` — legacy_cards 回填。
- `tower-dsh/ARCHITECTURE.md` — CI/post-merge 描述同步。
