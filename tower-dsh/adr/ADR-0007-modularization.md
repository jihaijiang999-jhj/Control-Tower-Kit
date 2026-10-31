---
schema: tower/adr@1
id: ADR-0007
title: "towerctl 模块化 + shape 接 CI"
status: accepted
date: 2026-10-31
deciders:
  - mac
related_cards:
  - PILOT-055
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/ARCHITECTURE.md
---

# ADR-0007 — towerctl 模块化 + shape 接 CI

## 背景

`tools/towerctl.py` 已 8,863 行、单文件承载 ledger/task/delivery/merge/command/arch/profile 全部逻辑；每次改动都在同一文件里，reviewer 难以定位边界，shape-check 只能冻结既有长函数，无法阻止文件继续膨胀。shape-check 也还没接 CI（只在本地/post-merge 之外手动跑）。

## 决策

1. **按职责拆模块**（每个 <600 行，shape 新文件上限）：
   - `tower_common.py`（JSON/IO/id/path/emit）
   - `tower_ledger.py`（append/verify/replay/lock）
   - `tower_task.py`（task-new/check/approve/close/board）
   - `tower_delivery.py`（dispatch/deliver/evidence/completion）
   - `tower_merge.py`（envelope/queue/merge/post-merge）
   - `tower_command.py`（campaign/brief/where/status）
   - `tower_arch.py`（arch-check/graph）
   - `tower_profile.py`（profile-check）
   - `tower_cli.py`（parser/handlers/composition）
   - `towerctl.py` 只做入口，目标 <500 行（硬上限 <3000）。
2. **依赖方向单向**：`towerctl → tower_cli → {各域模块} → tower_common/tower_ledger`；域模块之间只允许 `delivery/merge` 依赖 `ledger/task`，禁止循环。
3. **行为不变**：所有 CLI 子命令、退出码、JSON 输出、证据/状态语义不变；630 tests 全绿。
4. **shape 接 CI**：`.github/workflows/tower-gate.yml` 在 `status` 前增加 `python tools/towerctl.py shape-check`；status 仍最后。
5. **门表**：`GATE-MODULES` 校验 `towerctl.py <3000`、每个新模块 <600、无循环 import；`test_arch` 的 gates 17→18。
6. **不加事件类型、不改状态机、不改 spec@2**。

## 替代方案

- **只删注释/压行**：否。过不了 shape 的新文件/长函数规则，也不解决边界。
- **把代码塞进 `tools/` 子包但保留单文件**：否。`towerctl.py` 仍超 3000。
- **先接 shape CI、后拆**：否。CI 会立刻红在单文件上；拆完再接。

## 后果

正面：单文件回到可 review 的规模；模块边界成为 arch-check/import 测试的检查对象；CI 每次跑 shape，新增债务进不来。

负面：一次大搬家，diff 大、review 成本高；模块间 import 需要一次理顺；shape 基线可能因文件路径变化需要重建（卡内处理）。

## 关联卡

- `PILOT-055` — 落地本决策的卡。

## 关联文件

- `tower-dsh/tools/towerctl.py` — 入口。
- `tower-dsh/ARCHITECTURE.md` — 模块图。
- `tower-dsh/.github/workflows/tower-gate.yml` — shape 步。
