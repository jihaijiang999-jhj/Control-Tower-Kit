---
schema: tower/adr@1
id: ADR-0004
title: "depends_on 硬校验：存在、闭合、无环"
status: accepted
date: 2026-10-30
deciders:
  - mac
related_cards:
  - PILOT-051
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/specs/WF-TASK.md
  - tower-dsh/ARCHITECTURE.md
---

# ADR-0004 — depends_on 硬校验：存在、闭合、无环

## 背景

`tower/spec@2` 有 `depends_on`，但只被 `task-new` 当作“字段存在”复制进 record；`check --phase ready` 与 `dispatch` 都不验证。结果是：一张卡可以在依赖未合并时进入 ready/被派发，依赖链只存在于人的脑子里。050 的 spec 依赖 049、049 依赖 048，但即使 049 没合并，050 也能 ready——这正是“写了不生效”。

## 决策

1. **task-new（结构层）**：`depends_on` 必须是非空字符串列表（可为空）；不得自依赖；每个 id 必须能在 board/tasks 中找到；重复 id 去重后报错。失败 exit 2，零写入。
2. **check --phase ready（调度层）**：每个依赖的目标状态必须是 `closed`；否则 exit 2，错误点名 `depends_on.<id>: <status>`。
3. **dispatch（执行层）**：再次校验闭合；不信任 ready 时的状态（可能在等待期间被 VOID/重开）。失败 exit 2，零状态变更。
4. **无环**：沿所有 task record 的 `depends_on` 做 DFS；发现环 → exit 2，列出环上的 id。自依赖也算环。
5. **不做**：不引入 spec/contract 图（留给 052/053 的 `contracts` + `spec-graph`）；不新增事件类型；不修改 `spec@2` 字段；不在 `task-new` 要求依赖已闭合（允许先建卡后等依赖）。

## 替代方案

- **只在 task-new 校验闭合**：否。建卡时依赖可能还在 ready/merged 过程中；会把“排期”与“可派发”混在一起。
- **只靠 reviewer 记得看 depends_on**：否。不可机检，等于没有。
- **现在就做完整 spec-graph**：否。先把卡级依赖跑通；契约级（schema/event/command）依赖另开卡。

## 后果

正面：ready/dispatch 会拒绝未闭合依赖；环在入口就被抓；错误可定位到具体 id；050/051 这类顺序卡不再靠人记。

负面：历史卡 `depends_on` 多为空，不受影响；新卡若依赖 ready 卡需要等关闭；错误码多四种（self/missing/unmet/cycle）；没有契约版本概念（留给后续卡）。

## 关联卡

- `PILOT-051` — 落地本决策的卡。

## 关联文件

- `tower-dsh/tools/towerctl.py` — task-new / check / dispatch。
- `tower-dsh/specs/WF-TASK.md` — 前置不变量。
- `tower-dsh/ARCHITECTURE.md` — 卡依赖契约。
