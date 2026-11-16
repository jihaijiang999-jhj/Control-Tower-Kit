# tower-dsh

Tower/DSH 的第一个实例，Phase 3（`HANDOFF_ACTIVE`），双塔。

> 代号：**应县木塔 / Yingxian**（第一座塔，别名 `YX-001`）。命名与构件隐喻见 [control-tower/NAMING.md](../control-tower/NAMING.md)（仓库根）。

## 这是什么

一个 **file-backed control plane**，不执行任务，只负责：

- 任务卡（spec）
- 派发（routing）
- 阶段门（ready / deliver / review / accept / close）
- 证据（SHA-256 + ledger）
- 合并（只有监督塔可以 merge）
- closeout

执行交给 DSH subagent；review 交给另一个独立 subagent；merge 交给监督塔。

## 当前口径（2026-11-16，077 收盘）

| 项 | 值 |
|---|---|
| 代码卡 | **76 代码卡**（`PILOT-001`–`PILOT-077`；072 void、069 superseded） |
| 文档卡 | `PILOT-078`：C-04 第 **17** 个 campaign 节点，**不计入 76 代码卡** |
| 信封 | **74 信封** |
| 测试 | `Ran 844 tests / OK (skipped=1)` |
| 交付卡 | **16 张交付卡 / 16-16**（061–077，072 void 不计） |
| 位置 | 078 收盘前 `where` = `16/17`；收盘后 `17/17` |

> **16-16 不是"16 次 verified merge"**：065–068 由 074 的 `MERGE_HISTORICAL` 回填，
> 071/074/075/076/077 是 admin + `envelope-recover`。完整偏差见 `NEXT-WINDOW.md`。

- **入口**：[START-HERE.md](START-HERE.md)（读序）→ [NEXT-WINDOW.md](NEXT-WINDOW.md)（当前口径与残余）
- **端到端路径**：[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)（task-new → … → post-merge，含 owner/reviewer 判据）
- **架构**：[ARCHITECTURE.md](ARCHITECTURE.md) · **复现**：[REPRODUCE.md](REPRODUCE.md)

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
python tools/towerctl.py state-verify      # 76 / 74 / drift []
python tools/towerctl.py where             # C-04 17 节点
python -B tools/run_tests.py               # Ran 844
```

## 目录

| 路径 | 作用 |
|---|---|
| `TOWER.md` | 塔身份与边界 |
| `AGENTS.md` | 宪法 |
| `START-HERE.md` | 启动读序 |
| `NEXT-WINDOW.md` | 新窗口第一页：口径、deviation、残余 |
| `docs/WALKTHROUGH.md` | 从建卡到 post-merge 的可执行 walkthrough |
| `shared/` | 项目/权限/目标/地图 |
| `primary/` | 主塔状态、任务板、注册表 |
| `supervision/` | 监督塔状态、合并队列、合并账本 |
| `pilot/` | 冻结 spec（`<ID>.spec.json`）+ `worktrees/<ID>/` |
| `tasks/` | 任务卡、记录、证据 |
| `ledger/` | 追加式账本（primary/supervision 各一份） |
| `command/` | 战略、campaign、命令层 |
| `arch/` + `adr/` | 门表、红线 probe、事件目录、决策记录 |
| `tools/towerctl.py` | 唯一状态/门禁 CLI |
| `control-tower/` | 地图/命令层/命名（**仓库根，不在本目录内**） |

## 状态

Phase 2：见 `primary/CURRENT_STATE.json`、`supervision/CURRENT_STATE.json`、`supervision/MERGE_QUEUE.json`。
聊天不是状态；`ledger/*.jsonl` 才是历史。
