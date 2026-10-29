---
schema: tower/adr@1
id: ADR-0002
title: "spec@2：施工目标四要素硬门"
status: accepted
date: 2026-10-29
deciders:
  - mac
related_cards:
  - PILOT-049
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/tools/spec_lint.py
  - tower-dsh/templates/task.spec.json
  - tower-dsh/specs/WF-TASK.md
  - tower-dsh/arch/GATES.json
---

# ADR-0002 — spec@2：施工目标四要素硬门

## 背景

`tower/spec@1` 只有 `title / why_now / scope / acceptance`，没有可机检的"施工目标"。复杂卡可以被写成一个标题加一串文件路径，施工时被收窄成清状态、调参或单点补丁；`task-new` 不检查、`spec-lint` 也不扫 `pilot/*.spec.json`。owner 于 2026-10-29 要求"所有塔台的施工卡都必须带四要素目标"，本塔需要原生落地，而不是依赖外部校验器或 reviewer 记忆。

## 决策

新增 `tower/spec@2`，在 spec 顶层增加对象：

```json
"objective": {
  "problem": "遇到了什么（事故/缺陷、受影响对象、可证明的业务影响）",
  "outcome": "要解决什么（交付后应出现的可验收业务结果）",
  "approach": "为什么这样解决（方案、取舍、为什么不是单点补丁）",
  "non_goals_and_done": "不解决什么／怎么算完成（非目标、边界、证据、停点）"
}
```

执行点：

1. `templates/task.spec.json` 升级为 `tower/spec@2` 并带四字段示例。
2. `task-new` 对**所有新 spec**（@1 与 @2）校验 objective；缺对象、缺字段、非字符串、trim 后 <8 字符、`__FILL__`、`<...>` 占位 → exit 2，且在写 record/TASK/ledger 之前失败（零写入）。
3. `spec-lint` 扫描 `pilot/*.spec.json`：对 `@2` 强制 objective；`@1` 视为冻结旧卡，跳过（不回溯、不改哈希）。
4. `arch/GATES.json` 增加 `GATE-SPEC-OBJECTIVE`；`specs/WF-TASK.md` 增加 objective 前置不变量。
5. 校验规则原生实现，不依赖 `D:\game os` 的外部 checker；外部工具仅作对照。

**不做**：不回写 044–048 的冻结 spec；不改四闸、状态机、证据与合并语义；不在本卡改 `TOWER.md`（L0 由 owner 单独提交一行不变量）。

## 替代方案

- **只保留 why_now/scope 散文**：否。不可机检，reviewer 记忆不稳定。
- **把 objective 塞进 @1 并追溯旧卡**：否。旧卡已冻结，追溯会改哈希、破坏"spec 冻结"判例。
- **依赖外部 checker 作为门**：否。跨环境路径不可复现，且违反"门在塔内"。

## 后果

正面：新卡在创建入口就带四要素；缺项零写入；旧卡不受影响；ADR 体系第一次真实用于 schema 变更。

负面：`task-new` 与 `spec-lint` 两处校验需要同步维护；049 自身是 bootstrap（它的 spec 仍是 @1 + objective，因为创建它时 task-new 还不认识 @2）；机器检查只证结构与最低内容量，不证目标真实性与 AC 对齐——reviewer 仍要审。

## 关联卡

- `PILOT-049` — 落地本决策的卡。

## 关联文件

- `tower-dsh/tools/towerctl.py` — task-new 校验入口。
- `tower-dsh/tools/spec_lint.py` — spec-lint @2 规则。
- `tower-dsh/templates/task.spec.json` — 模板。
- `tower-dsh/specs/WF-TASK.md` — 前置不变量。
- `tower-dsh/arch/GATES.json` — 门表。
