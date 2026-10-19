# tower-dsh

Tower/DSH 的第一个实例，Phase 3（`HANDOFF_ACTIVE`），双塔。

> 代号：**应县木塔 / Yingxian**（第一座塔，别名 `YX-001`）。命名与构件隐喻见 [control-tower/NAMING.md](../control-tower/NAMING.md)。

## 这是什么

一个 **file-backed control plane**，不执行任务，只负责：

- 任务卡（spec）
- 派发（routing）
- 阶段门（ready / deliver / review / accept / close）
- 证据（SHA-256 + ledger）
- 合并（只有监督塔可以 merge）
- closeout

执行交给 DSH subagent；review 交给另一个独立 subagent；merge 交给监督塔。

## 双塔

| 塔 | 目录 | 职责 |
|---|---|---|
| Primary | `primary/` | 任务卡、worktree、commit、PR/信封、证据、closeout；**不 merge** |
| Supervision | `supervision/` | 独立验收、串行合并队列、实际 merge、post-merge 验证、纠正单 |

## 快速开始

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py supervision-status
```

## Phase 2 pilot

- Task: `PILOT-001` — Ledger SHA-256 哈希链模块与篡改检测
- Phase 1: closed（未 merge）
- Phase 2: `ENV-PILOT-001` 已由监督塔合并，`POST_MERGE_VERIFIED`
- Phase 3: `HANDOFF-PILOT-001` 已激活，controller `ctl-phase3-receiver-001`
- Repo: `pilot/repo`
- Worktree: `pilot/worktrees/PILOT-001`

## 目录

| 路径 | 作用 |
|---|---|
| `TOWER.md` | 塔身份与边界 |
| `AGENTS.md` | 宪法 |
| `START-HERE.md` | 启动读序 |
| `shared/` | 项目/权限/目标/地图 |
| `primary/` | 主塔状态、任务板、注册表 |
| `supervision/` | 监督塔状态、合并队列、合并账本 |
| `tasks/` | 任务卡、记录、证据 |
| `ledger/` | 追加式账本（primary/supervision 各一份） |
| `handoffs/` | Phase 3 交接 |
| `tools/towerctl.py` | 唯一状态/门禁 CLI |

## 状态

Phase 2：见 `primary/CURRENT_STATE.json`、`supervision/CURRENT_STATE.json`、`supervision/MERGE_QUEUE.json`。
聊天不是状态；`ledger/*.jsonl` 才是历史。
