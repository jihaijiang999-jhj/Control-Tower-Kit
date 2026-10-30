# Tower/DSH — tower-dsh

> Status: **Phase 3 active** — `HANDOFF-PILOT-001` 已接管；dual tower (primary + supervision)。
> 代号：**应县木塔 / Yingxian**（实例 `tower-dsh`，别名 `YX-001`）。
> Owner: `mac`。
> Primary controller: see `primary/CURRENT_STATE.json` (`primary.id`).
> Supervisor: see `supervision/CURRENT_STATE.json` (`supervisor.id`).

## 本塔是什么

`tower-dsh` 是 Tower/DSH 的第一个实例。它是 file-backed control plane，不执行任务，只负责：

- spec：把内部任务变成可验收的任务卡；
- routing：把任务派给 executor（DSH subagent）；
- gates：spec / ready / deliver / review / accept / close；
- evidence：SHA-256、任务证据、ledger；
- merge：**只有监督塔可以合并**，主塔只能提交合并信封；
- handoff：Phase 3 再挂 v2.1。

## spec 环节（第一道闸）

spec 是任务卡的来源，也是闭环的第一道闸。规则：

- spec 必须声明 `"schema": "tower/spec@1"`（旧卡冻结）或 `"tower/spec@2"`（新卡），格式见 `templates/task.spec.json`；
- 所有新建 spec（@1/@2）必须含 `objective` 四要素（`problem/outcome/approach/non_goals_and_done`）；缺项、占位或内容过短时 `task-new` 零写入拒绝，`spec-lint` 对 @2 强制；见 `adr/ADR-0002-spec-objective.md`；
- `acceptance` 每条必须可执行（能跑、能测、能核哈希），禁止不可测表述；
- `forbidden` 必须含 `merge` 与 `production access`；
- 流程：`task-new` → owner 或独立 reviewer 运行 `spec-approve --task <id> --by <name>` 在 ledger 留下 `SPEC_APPROVED` → `check --task <id> --phase spec` 通过后才允许 `check --phase ready`；
- spec 批准人不能是 executor；
- spec 一经 `task-new` 消费即冻结（任务卡记录 SHA-256）；要改 spec 就重建任务卡，旧卡作废留痕，禁止原地改。

## 双塔

| 塔 | 目录 | 拥有 | 禁止 |
|---|---|---|---|
| Primary | `primary/` | 任务卡、worktree、commit、PR/信封、证据、closeout | merge、生产、外部调用 |
| Supervision | `supervision/` | 独立验收、串行合并队列、实际 merge、合并后验证、纠正单 | 改候选实现、自批、跳过证据 |

**任何 merge 之前，Phase 2 双塔必须就位。**

## 首版边界

- 工程轨：主塔 `workspace_write` + 监督塔 merge；生产轨 `no_access`；
- 不碰生产、外部调用、部署；
- executor 只在 `pilot/worktrees/PILOT-001` 内写；
- reviewer 必须是独立 subagent；
- merge 必须走 `MERGE_QUEUE.json` + 两提交信封 + post-merge verification。

## 入口

1. `AGENTS.md` — 本塔宪法；
2. `shared/PROJECT_PROFILE.json` — 项目/根/权限上限；
3. `shared/AUTHORITY_MODEL.json` — 双塔角色/owner 保留/分离不变量；
4. `primary/CURRENT_STATE.json` — 主塔状态；
5. `supervision/CURRENT_STATE.json` — 监督塔状态；
6. `primary/TASK_BOARD.json` — 任务总表；
7. `supervision/MERGE_QUEUE.json` — 唯一合并队列；
8. `tasks/<id>/TASK.md` — 任务卡；
9. `tools/towerctl.py` — 唯一状态/门禁 CLI；
10. `RED-LINES.md` — 红线清单（触碰即停）；
11. `CHANGE-LEVELS.md` — 变更分级 L0–L3；
12. `AUDIT-2026-10-19.md` — 首次全面体检与缺口清单；
13. `specs/WF-TASK|MERGE|HANDOFF|LEDGER.md` — 四条工作流规范（`tower/workflow@1`）。

## 当前状态

- 代号：**应县木塔 / Yingxian**（`YX-001`）
- 任务：`PILOT-001` … `PILOT-006` 全部 `closed`；6 个 envelope 全部 `POST_MERGE_VERIFIED`
- Phase 3：`HANDOFF-PILOT-001` ACTIVE，controller `ctl-phase3-receiver-001`
- 门禁：spec 强制 / 证据强制 / merge 分支断言 / post-merge 可重试 / handoff 参数化 / ledger 哈希链
- 工作流规范：`specs/WF-TASK.md`、`WF-MERGE.md`、`WF-HANDOFF.md`、`WF-LEDGER.md`
- 已知 backlog：`AUDIT-2026-10-19.md` §8

## 四闸

merge / 外部调用 / 部署·生产数据 / L0 文档写 main 永远归 owner。
Phase 2 的 merge 是**工程轨**，由监督塔执行；生产轨仍然 `no_access`。
