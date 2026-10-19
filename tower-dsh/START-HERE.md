# START HERE — tower-dsh

按顺序读：

1. `TOWER.md` — 本塔是什么、双塔边界。
2. `shared/PROJECT_PROFILE.json` — 项目、workspace_root、权限上限。
3. `shared/AUTHORITY_MODEL.json` — 双塔角色、owner 保留、分离不变量。
4. `primary/CURRENT_STATE.json` — 主塔 phase、primary id、下一动作。
5. `supervision/CURRENT_STATE.json` — 监督塔 phase、supervisor id、下一动作。
6. `primary/TASK_BOARD.json` — 任务总表。
7. `supervision/MERGE_QUEUE.json` — 唯一合并队列。
8. `tasks/<id>/TASK.md` — 当前任务卡。
9. `RED-LINES.md` — 红线清单（触碰即停）。
10. `CHANGE-LEVELS.md` — 变更分级 L0–L3。

启动自检：

```powershell
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py supervision-status
```

若 `wiring` 不通过，塔状态为 `ORPHANED`，不得宣称已建成。

Phase 2 规则：**Primary 不 merge；Supervision 独占合并队列**。任何 merge 必须有两提交信封 + 独立验收 + post-merge verification。

## 接续口令消歧（硬规则）

裸说“接续 / 继续 / resume / 接手 / 你来”时，**必须先反问三件事**，不得直接开工：

1. 接哪个塔？（primary / supervision）
2. 接哪个对象？（handoff 包 ID / task ID / 当前会话）
3. 只读自检，还是执行？（执行需 owner 口令）

owner 已明确给出对象与动作时，才可跳过反问。
“只读自检”默认：不写文件、不改状态、不 merge、不外部调用。
