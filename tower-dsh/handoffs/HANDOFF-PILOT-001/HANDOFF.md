# tower-dsh 交接上下文包 — HANDOFF-PILOT-001

> 项目：Tower/DSH · 机制：project-handoff v2.1 · 装配路径：塔台直写
> 交接时刻：2026-10-19T12:50:58+08:00 · 交出塔：ctl-8cd51ef9-2972-415a-b1db-d8d37afdde82

## §0 交接时刻实值

| 锚点 | 值 |
|---|---|
| tower_id | `tower-dsh` |
| primary phase | `PHASE_2_VERIFIED` |
| primary id | `ctl-8cd51ef9-2972-415a-b1db-d8d37afdde82` |
| supervisor id | `sup-phase2-pilot` |
| supervision phase | `PHASE_2_PILOT_VERIFIED` |
| main SHA | `9fb5ba243f5cf03f7ccafb0eb381793770835db2` |
| worktree head | `ed28ac618f524db7d5db426db3839cd185a6da11` |
| repo status | `clean` |
| worktree status | `clean` |
| task status | `closed` |
| task next | `merged via ENV-PILOT-001; POST_MERGE_VERIFIED` |
| merge queue | `POST_MERGE_VERIFIED` |
| merge commit | `9fb5ba243f5cf03f7ccafb0eb381793770835db2` |
| primary ledger seq | `12` |

### 证据锚点

| 证据 | SHA-256 |
|---|---|
| `tasks/PILOT-001/evidence/ledger_chain.py` | `38ced80e191785ff9c1d3901cf1562c729709522c313436bf63c02029d8a131c` |
| `tasks/PILOT-001/evidence/test_ledger_chain.py` | `57ae95aa6ec05e40468a77a0d589dfb4ffbb0ff5028d8c590293800d6943b70e` |
| `tasks/PILOT-001/evidence/README.md` | `968b351f87e5ee7b6724b2585aa12147bd88b2073789c62de5e79fbb364ef3dd` |
| `tasks/PILOT-001/evidence/test-output.txt` | `80f9e4c35664a1a4dab1cd2114ab875cb3c9ae1ece02ab5e2a7749702f5b9da7` |
| `tasks/PILOT-001/evidence/commit.txt` | `a8618ec6bfae296e7583d2fec22262fa9e201a2d3840abbb0b61af85bfa96882` |
| `tasks/PILOT-001/evidence/review-output.txt` | `fc1beed9f68f3308e47476ca8fe81d21822935b75aaa85ab5f115ce47ea44953` |

## §0a 材料漂移警示

NONE（无阻断性漂移；已知非阻断项：merge envelope 的证据列表 5 项，task record 6 项，含 `commit.txt`）。

## §1 30 秒版现状

Phase 2 双塔已验证：`PILOT-001` 已合并并 `POST_MERGE_VERIFIED`；merge commit `9fb5ba243f5cf03f7ccafb0eb381793770835db2`；post-merge 14 tests OK；主塔与监督塔状态均为已验证。下一步是 Phase 3 handoff 或真实项目 pilot。

## §2 接续读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`
4. `shared/AUTHORITY_MODEL.json`
5. `primary/CURRENT_STATE.json`
6. `supervision/CURRENT_STATE.json`
7. `primary/TASK_BOARD.json`
8. `supervision/MERGE_QUEUE.json`
9. `tasks/PILOT-001/CLOSEOUT.md`
10. `ledger/primary.jsonl` 与 `ledger/supervision.jsonl`

## §3 运行时操作手册

- Tower root：`C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh`
- Pilot repo：`pilot/repo`（main）
- Pilot worktree：`pilot/worktrees/PILOT-001`
- Python：3.12；测试：`python -B -m unittest discover -s tests -v`
- CLI：`python tools/towerctl.py <command>`
- 不读凭据、不调用生产、不部署；所有状态经 `towerctl`。

## §4 在途任务队列

- 无在途任务。
- 下一动作：owner 选择 Phase 3 handoff 完成后接真实项目 pilot，或补远端 PR/分支保护。
- 待 owner 输入：下一个真实任务/项目。

## §4a 调研/方案/未实现需求资产登记

- `control-tower/DESIGN.md` — Tower/DSH v0.3 设计（双塔/文件化/接线门/handoff v2.1）。
- `tower-dsh/PHASE2-REPORT.md` — Phase 2 双塔 pilot 报告。
- `%APPDATA%\kimi-desktop\daimon-share\daimon\skills\project-handoff\SKILL.md` — v2.1 源机制（只读参考）。
- `D:\SeeMake-K3\_k3-ops\templates\项目交接机制-v2.1-通用模板.md` — v2.1 通用模板（只读参考）。
- `~/.agents/skills/control-tower/`、`~/.agents/skills/control-tower-supervisor/` — 本塔技能。

## §5 owner 偏好与裁决档案

- Owner：`mac`。
- 四闸永远归 owner：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。
- Primary 不 merge；Supervision 独占合并队列。
- 生产轨 `no_access`；本 pilot 未碰生产。
- 偏好：证据优先、单一写者、先手动后自动化。

## §6 判例与环境陷阱

- 本地 git 合并，不是远端 PR；无服务端分支保护。
- `--role supervisor` 是程序性分离，不是密码学身份。
- merge envelope 证据列表 5 项，task record 6 项（`commit.txt` 未列）。
- Windows CRLF 警告属正常；控制台中文可能显示乱码，文件本身 UTF-8。
- 不要手改 `primary/`、`supervision/`、`ledger/`；用 `towerctl`。

## §7 红线四闸与文档地图

| 对象 | 路径 |
|---|---|
| 塔身份 | `TOWER.md` |
| 宪法 | `AGENTS.md` |
| 启动读序 | `START-HERE.md` |
| 主塔状态 | `primary/CURRENT_STATE.json` |
| 监督塔状态 | `supervision/CURRENT_STATE.json` |
| 合并队列 | `supervision/MERGE_QUEUE.json` |
| 合并账本 | `supervision/registries/merge-ledger.json` |
| 任务卡 | `tasks/PILOT-001/TASK.md` |
| 收口 | `tasks/PILOT-001/CLOSEOUT.md` |
| Ledger | `ledger/primary.jsonl`、`ledger/supervision.jsonl` |

**四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。**
