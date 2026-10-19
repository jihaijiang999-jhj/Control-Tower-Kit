# tower-dsh — Phase 1 Target

> 历史文档：这是 Phase 1 的目标，已被 Phase 2/3 超越；保留为轨迹，不据此判断当前状态。
> 当前状态见 `primary/CURRENT_STATE.json` 与 `supervision/CURRENT_STATE.json`。

## 首版目标

用一个**真实内部任务**证明控制塔闭环：

```text
READY → DISPATCHED → RETURNED → REVIEW → ACCEPT → CLOSE
```

要求：

- executor 是独立 subagent，只在 git worktree 内写；
- reviewer 是另一个独立 subagent，read-only，亲跑测试；
- 证据进 `tasks/PILOT-001/evidence/`，带 SHA-256；
- 通过 `towerctl` 记录状态与 ledger；
- **不 merge、不碰生产、不调用外部服务**。

## 首版不做

- 监督塔 / 合并队列 / 两提交信封（Phase 2）；
- Console（Phase 4）；
- 自动化 / 心跳（Phase 5）；
- 任何四闸动作。

## 完成判据

- `towerctl wiring` 通过；
- `towerctl check` 的 ready/deliver/review/accept/close 全过；
- 测试全过，reviewer 独立 PASS；
- closeout 明确写“merge not performed”；
- ledger 可重放状态。
