# ADR 模板 — 架构决策记录

> 复制本文件为 `adr/ADR-00NN-<slug>.md`，填入 front-matter 与正文。
> 决策一旦落地：`status: accepted`；被后续 ADR 取代后改 `superseded` 并链接新 ADR；
> 历史提案归档用 `archived`。`towerctl arch-check` 校验 front-matter 与 `related_files` 是否存在。

## 模板

```yaml
---
schema: tower/adr@1
id: ADR-00NN
title: "一句话标题"
status: proposed          # proposed | accepted | superseded | archived
date: YYYY-MM-DD
deciders:
  - mac
related_cards:
  - PILOT-0NN
related_files:
  - tower-dsh/tools/towerctl.py
---
```

## 背景

问题与约束：现在是什么状态、为什么会痛、不做会怎样。引用 RED-LINES / ARCHITECTURE 的对应章节，不重复它们。

## 决策

选了什么，边界是什么，怎么被执行（命令、门、测试、CI）。写清“不做”的部分同样重要。

## 替代方案

至少一个被否掉的方案，以及否掉的具体理由（成本/风险/不可验证），不要写“没想到”。

## 后果

正面：得到什么可验证的能力。
负面：新增的维护面、兼容性负担、已知边界；需要补的卡（PILOT-0NN）。

## 关联卡

- `PILOT-0NN` — 落地本决策的卡（必须是 `tasks/` 里真实存在的卡）。

## 关联文件

- `tower-dsh/tools/towerctl.py` — 决策的执行点（`arch-check` 会校验文件存在）。
