---
schema: tower/adr@1
id: ADR-0006
title: "记录层纵深：deliver 反查 completion，state-verify 审计 base_sha/孤悬"
status: accepted
date: 2026-10-31
deciders:
  - mac
related_cards:
  - PILOT-043
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/tools/tests/test_record_layer.py
  - tower-dsh/tools/tests/test_completion_and_base.py
---

# ADR-0006 — 记录层纵深：deliver 反查 completion，state-verify 审计 base_sha/孤悬

## 背景

042 把 completion 与 base_sha 写进 record/ledger，但 deliver 只信 `record.completions`（手写条目可 0 通过），state-verify 不审计 `dispatch.base_sha`（改成 HEAD 即可空 diff），孤悬 `COMPLETION_ADDED` 被忽略。记录层目前“只存不核”，任何能写 record 的人都能伪造授权补齐。

## 决策

1. **deliver 反查**：对 diff 实际命中的每条 completion，在 primary ledger 找匹配的 `COMPLETION_ADDED`（task+path）；缺失 → exit 2 零写入；事件与 record 条目逐字段一致（path/by/reason/decision/at）；`by` 必须等于 owner.name；字段非空。
2. **base_sha 审计**：`record.dispatch.base_sha` 非空时必须等于对应 `DISPATCH` payload.base_sha，否则 `dispatch_base_mismatch`；事件有而 record 空 → `dispatch_base_missing`；两者都空 → legacy 不报。
3. **孤悬/不匹配**：`COMPLETION_ADDED` 指向不存在的 task → `completion_orphan`；record 条目与事件不一致 → `completion_mismatch`。
4. **skip 不豁免**：因 `no_lifecycle_events` 被 skip 的任务，若 record 有 completions，仍要审计；无 completions 的 legacy 不新增 drift。
5. **不新增事件类型、不改状态机**：只收紧读侧。

## 替代方案

- **只信 record.completions**：否。手写 JSON 即可绕过 owner 授权。
- **只在 deliver 查、不在 state-verify 查**：否。已合并的历史伪造无法在重放时暴露。
- **把 base_sha 写进 envelope**：否。它属于 dispatch 记录层，不是合并层。

## 后果

正面：deliver 与 state-verify 都能发现伪造 completion / 篡改 base_sha；旧卡 legacy 不误报；042 的“手写 record 也 0”用例被新语义改为 exit 2。

负面：deliver 多一次 ledger 扫描；`test_completion_and_base.py` 必须做最小调整；skip 任务的 completions 审计会增加 drift 面。

## 关联卡

- `PILOT-043` — 落地本决策的卡（v2 重建）。

## 关联文件

- `tower-dsh/tools/towerctl.py` — deliver / state-verify。
- `tower-dsh/tools/tests/test_record_layer.py` — 新测试。
- `tower-dsh/tools/tests/test_completion_and_base.py` — 042 冲突用例最小调整。
