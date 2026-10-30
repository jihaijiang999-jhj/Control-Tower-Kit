---
schema: tower/workflow@1
id: WF-TASK
title: 任务流 — 任务卡从创建到收口
owner: mac
version: 3
enforcement_legend: tool-check | review-check | owner-gate
---

# WF-TASK — 任务流

## 1. 范围

适用于 `tower-dsh` 中单张任务卡（`tasks/<id>/`）的完整生命周期：
创建 → spec 批准 → 派发 → 交付 → 独立复核 → 接受 → 收口。
不覆盖合并（见 `WF-MERGE`）与交接（见 `WF-HANDOFF`）。

所有状态变更必须经 `towerctl`；聊天记录不是状态。

## 2. 状态机

| 状态 | 含义 | 终态 |
|---|---|---|
| `ready` | 任务卡已建，等待 spec 批准与派发 | 否 |
| `dispatched` | 已派发给 executor，worktree 已锁定 | 否 |
| `delivered` | executor 已交付，证据已入 `tasks/<id>/evidence/` | 否 |
| `reviewed` | 独立 reviewer 给出 PASS | 否 |
| `rework` | reviewer 给出 FAIL，等待返工 | 否 |
| `accepted` | owner 接受，decision 已记录 | 否 |
| `closed` | closeout 已写，任务结束 | 是 |

## 3. 转移

| ID | from | to | 前置条件 | 命令 | 证据 | 失败动作 |
|---|---|---|---|---|---|---|
| TR-01 | `—` | `ready` | spec 满足 `tower/spec@1`；worktree 存在 | `task-new` | `spec_sha256` 写入 record | 拒绝建卡 |
| TR-02 | `ready` | `ready` | 批准人 ≠ executor | `spec-approve` | ledger `SPEC_APPROVED` | 拒绝批准 |
| TR-03 | `ready` | `ready` | spec 哈希未变 | `check` | `spec_gate=PASS` + ledger `CHECK` | 返回错误，不置 PASS |
| TR-04 | `ready`\|`rework` | `dispatched` | `spec_gate=PASS`、spec 哈希一致、`TASK.md` 存在、worktree 存在 | `dispatch` | ledger `DISPATCH` | 拒绝派发 |
| TR-05 | `dispatched`\|`delivered`\|`rework` | `delivered` | 证据文件存在且可哈希 | `deliver` | `DELIVERY.md` + 证据 SHA-256 | 拒绝交付 |
| TR-06 | `delivered`\|`reviewed`\|`rework` | `reviewed` | reviewer 非空且 ≠ executor | `checkback --verdict PASS` | `REVIEW.md` + ledger `CHECKBACK` | 拒绝复核 |
| TR-07 | `delivered`\|`reviewed`\|`rework` | `rework` | 同上 | `checkback --verdict FAIL` | `REVIEW.md` | 进入返工 |
| TR-08 | `reviewed`\|`accepted` | `accepted` | review PASS；证据 0 项或哈希不符则拒绝 | `accept` | `decision` + ledger `ACCEPT` | 拒绝接受 |
| TR-09 | `accepted` | `closed` | 证据有效；`TASK.md` 存在 | `close` | `CLOSEOUT.md` + ledger `CLOSEOUT` | 拒绝收口 |

## 4. 不变量

| ID | 不变量 | enforcement |
|---|---|---|
| INV-01 | reviewer 必须非空且不等于 executor | tool-check |
| INV-02 | 任务卡创建后 spec 冻结；`spec_sha256` 变化即视为 spec_gate 失效 | tool-check |
| INV-03 | accept / close 时证据非空且逐条 SHA-256 匹配 | tool-check |
| INV-04 | executor 只写 `allowed_paths` 内的文件 | review-check |
| INV-05 | spec 批准人不得是 executor；作者不得自审 | owner-gate |
| INV-06 | 状态只能沿本表转移，不得跳步（如 ready → accepted） | tool-check |
| INV-07 | 每个状态变更都必须留下 ledger 事件 | tool-check |

## 5. 证据

- spec：`pilot/<ID>.spec.json` 的 SHA-256（record 内 `spec_sha256`）；
- 交付：`tasks/<id>/evidence/` 下逐文件 SHA-256 + 字节数；
- 复核：`REVIEW.md`（reviewer、verdict、时间、证据清单）；
- 收口：`CLOSEOUT.md`（范围、证据、决策、merge 状态）；
- 事件：`ledger/primary.jsonl` 的 `SPEC_APPROVED` / `DISPATCH` / `DELIVER` / `CHECKBACK` / `ACCEPT` / `CLOSEOUT`。

## 6. 失败模式

| ID | 失败 | 唯一合法动作 |
|---|---|---|
| FM-01 | `dispatch` 报 spec gate 未通过 | 重建任务卡或补 `spec-approve`；不得手改 record |
| FM-02 | spec 哈希不符 | 重建任务卡；不得原地改 spec |
| FM-03 | reviewer 与 executor 相同 | 换独立 reviewer |
| FM-04 | 证据哈希不符 | 重新 `deliver`；不得改证据副本 |
| FM-05 | executor 中途失联 | 以 aborted 记录为证据 → `deliver` → `checkback FAIL` → 重新 `dispatch` |
| FM-06 | 误改状态文件 | 停止，报告 owner；不得用第二次写入掩盖 |

## 7. 变更记录

| 版本 | 日期 | 变更 | 批准 |
|---|---|---|---|
| 1 | 2026-10-19 | 初版，按 PILOT-002/003/006 后的实际行为编写 | owner |
| 2 | 2026-10-29 | 增加第 8 节“施工目标前置不变量”（spec@2 objective 门） | owner |
| 3 | 2026-10-30 | 增加第 9 节“卡依赖前置不变量”（`depends_on` 结构/闭合/无环三层） | owner |

## 8. 施工目标前置不变量

`tower/spec@2` 要求每张新卡在顶层携带 `objective` 对象；`tower/spec@1` 旧卡冻结，不回溯、不改哈希。

| 字段 | 语义 |
|---|---|
| `problem` | 遇到了什么问题：缺陷或风险、受影响入口、可证明的影响 |
| `outcome` | 交付后应出现的可验收业务结果 |
| `approach` | 为什么这样解决：方案、取舍、为什么不是单点补丁 |
| `non_goals_and_done` | 不解决什么、边界在哪，以及怎么算完成 |

- `task-new` 对**所有**新 spec 校验 objective：必须是对象、四字段齐全、每个值 `strip()` 后至少 8 字符、不是裸 `__FILL__` 占位、不是整体 `<...>` 占位；校验发生在创建 `tasks/<id>/`、写 record/TASK、append `TASK_NEW` 之前，失败 `exit 2` 单 JSON 且**零写入**。`__FILL__` 只在作为整个字段值时拒绝（正文提及该标记是允许的，049 bootstrap 即如此），否则“卡自身 must pass”与“不得含”互相矛盾。
- `spec-lint` 只对顶层 `pilot/*.spec.json` 中声明 `tower/spec@2` 的卡强制同一规则；`tower/spec@1` 跳过（冻结旧卡）；`pilot/worktrees/**` 的嵌套副本不在扫描范围。
- 机器检查只证结构与最低内容量，不证目标真实性与 AC 对齐；reviewer 仍须独立审 objective 是否描述真实问题、approach 是否避免单点补丁、`non_goals_and_done` 是否与 acceptance 一致。

## 9. 卡依赖前置不变量

`depends_on`（`tower/spec@2` 字段，旧卡可为空或缺省）从 051 起是三层前置，不只是被复制进 record 的字段：

| 层 | 校验点 | 规则 | 错误码（exit 2） |
|---|---|---|---|
| 结构 | `task-new` | 必须是字符串列表（可为空 `[]`）；元素 `strip()` 后非空；不得自依赖；重复 id 报错；每个 id 必须能在 `primary/TASK_BOARD.json` 或 `tasks/<id>/` 找到 | `depends_on.invalid` / `depends_on.self` / `depends_on.duplicate` / `depends_on.missing` |
| 闭合 | `check --phase ready` 与 `dispatch` | `record.depends_on` 的每个目标状态必须是 `closed`；`dispatch` 不信任 ready 时的状态，重新校验 | `depends_on.<id>: <status>`（目标不存在时为 `depends_on.<id>: missing`） |
| 无环 | `check --phase ready` 与 `dispatch` | 沿全部 live task record 的 `depends_on` 做 DFS（含自依赖）；发现环即拒绝 | `depends_on.cycle: A -> B -> A` |

- 结构校验在写 `tasks/<id>/`、record/TASK 与 `TASK_NEW` 之前完成；失败 exit 2 单 JSON、零写入。
- `dispatch` 的闭合与无环校验在写 record/board 与 `DISPATCH` 之前完成；失败零状态变更。
- **允许先建卡后等依赖**：`task-new` 只要求目标卡存在，不要求目标 `closed`；否则“排期”与“可派发”会被混为一谈。
- `check --phase spec` 不查闭合：spec 获批时依赖可能仍在 ready / dispatched / merged 流程中。
- 旧卡 `depends_on` 为空或缺省视为无依赖，ready / dispatch 行为不变。
- `task-new` 不做全图 DFS：新卡尚未写入，环只能由后续卡形成，故环检测放在调度与执行入口。
