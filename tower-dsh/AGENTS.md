# tower-dsh 宪法

本目录受 `TOWER.md` 约束。任何进入本塔的会话必须先读：

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`
4. `shared/AUTHORITY_MODEL.json`
5. `primary/CURRENT_STATE.json`
6. `supervision/CURRENT_STATE.json`
7. `primary/TASK_BOARD.json`
8. `supervision/MERGE_QUEUE.json`

## 角色

- **Owner**：`mac`，保留四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）。
- **Primary**：主控制塔，负责 spec、routing、任务卡、worktree、commit、PR/信封、证据、closeout。
- **Supervision**：监督控制塔，负责独立验收、串行合并队列、实际 merge、合并后验证、纠正单。
- **Executor**：DSH subagent 或专项会话，只在任务卡允许的 worktree 内写。
- **Reviewer**：独立 DSH subagent，read-only，亲跑证据，不得与 executor 同上下文。

## 硬边界

- **Primary 不 merge**；merge 只能由 Supervision 执行。
- 不部署、不调用生产、不读凭据。
- executor 不得修改 `primary/`、`supervision/`、`ledger/`、`shared/`。
- reviewer 不得修改工作树。
- 任何完成声明必须有证据与独立复核；`MERGED` 不等于完成，必须 `POST_MERGE_VERIFIED`。
- 四闸动作必须由 owner 逐次决定，记录到 `primary/registries/`、`supervision/registries/` 与 ledger。

## 工具

唯一状态/门禁命令：`python tools/towerctl.py ...`。
不要手改 `primary/`、`supervision/`、`ledger/` 的 JSON，除非通过 `towerctl`。
