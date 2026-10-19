# tower-dsh — Project Map

| 对象 | 路径 |
|---|---|
| Workspace root | `C:/Users/mac/Documents/deepseek-harness/default-workspace` |
| Tower root | `C:/Users/mac/Documents/deepseek-harness/default-workspace/tower-dsh` |
| Pilot repo | `tower-dsh/pilot/repo` (git) |
| Pilot worktree | `tower-dsh/pilot/worktrees/PILOT-001` |
| Task dir | `tower-dsh/tasks/PILOT-001` |
| Evidence | `tower-dsh/tasks/PILOT-001/evidence` |
| State | `tower-dsh/primary/CURRENT_STATE.json` |
| Task board | `tower-dsh/primary/TASK_BOARD.json` |
| Ledger | `tower-dsh/ledger/primary.jsonl` |
| CLI | `tower-dsh/tools/towerctl.py` |
| Skill (primary) | `C:/Users/mac/.agents/skills/control-tower/SKILL.md` |
| Skill (supervisor) | `C:/Users/mac/.agents/skills/control-tower-supervisor/SKILL.md` |
| 红线 | `tower-dsh/RED-LINES.md` |
| 变更分级 | `tower-dsh/CHANGE-LEVELS.md` |
| 体检报告 | `tower-dsh/AUDIT-2026-10-19.md` |
| 代号 | `control-tower/NAMING.md`（应县木塔 / Yingxian） |

## 权限

- 工程轨：`workspace_write`，worktree 内；
- 生产轨：`no_access`；
- merge / 外部调用 / 部署 / L0 文档：owner 四闸，未授权。

## 真值

`primary/CURRENT_STATE.json` + `primary/TASK_BOARD.json` + `ledger/primary.jsonl`；
聊天记录不是项目真值。
