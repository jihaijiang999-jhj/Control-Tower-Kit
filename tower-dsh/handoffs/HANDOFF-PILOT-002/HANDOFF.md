# tower-dsh 交接上下文包 — HANDOFF-PILOT-002

> 项目：Tower/DSH · 机制：project-handoff v2.1 · 装配路径：塔台直写
> 交接时刻：2026-10-19T22:43:52+08:00 · 交出塔：ctl-phase3-receiver-001

## §0 交接时刻实值

| 锚点 | 值 |
|---|---|
| tower_id | `tower-dsh` |
| primary phase | `READY_FOR_PRACTICE` |
| primary id | `ctl-phase3-receiver-001` |
| supervisor id | `sup-phase2-pilot` |
| supervision phase | `PHASE_2_PILOT_VERIFIED` |
| task id | `PILOT-010` |
| envelope id | `ENV-PILOT-010` |
| main SHA | `9fb5ba243f5cf03f7ccafb0eb381793770835db2` |
| worktree head | `6e00d6975540dfc3df8d29ec7083d6960ff637df` |
| repo status | `clean` |
| worktree status | `clean` |
| task status | `closed` |
| task next | `merged via ENV-PILOT-010; POST_MERGE_VERIFIED; hardening 2 complete` |
| merge queue | `POST_MERGE_VERIFIED` |
| merge commit | `87bd88c40950a4ef141907f837a5a8b8ea2724d2` |
| primary ledger seq | `98` |

### 证据锚点

| 证据 | SHA-256 |
|---|---|
| `tasks/PILOT-010/evidence/towerctl.py` | `2823da2c1dd018a3f5e2950e5b306efdc73d9111adbac824508ac1ba06be1a8a` |
| `tasks/PILOT-010/evidence/test_hardening2.py` | `726a87a871275cae0ebbc45ec68405f192b94b85d0c962c8ef34a1f36f53930a` |
| `tasks/PILOT-010/evidence/test_coverage.py` | `3cd2f9436906684b959fce58c08cce0d04a3c530d2324dff861615b59f25bb1d` |
| `tasks/PILOT-010/evidence/clause_bindings.py` | `4fa325e937d8a312f044b528520048606d1e106e1b98943bfa348a39c066b3bc` |
| `tasks/PILOT-010/evidence/test-output.txt` | `047917b0b216bc6c7283290a369323aeab8508531822fa2645e380dbe1543e0f` |
| `tasks/PILOT-010/evidence/commit.txt` | `c614977c94faa31a9a1c624af35bff9b6fb824c0b30e1ba46274916d14dc2910` |
| `tasks/PILOT-010/evidence/diff.txt` | `60c84485b0f854c03744cca017fd17446b9151d3f0be2db5e39d4d36be747e07` |

## §0a 材料漂移警示

NONE（无阻断性漂移；证据锚点：package 7 项，所选 task record 7 项）。

## §1 30 秒版现状

主塔 phase `READY_FOR_PRACTICE`；任务 `PILOT-010` 状态 `closed`（next：merged via ENV-PILOT-010; POST_MERGE_VERIFIED; hardening 2 complete）；合并队列 `ENV-PILOT-010` 状态 `POST_MERGE_VERIFIED`（merge commit：`87bd88c40950a4ef141907f837a5a8b8ea2724d2`）。

## §2 接续读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`
4. `shared/AUTHORITY_MODEL.json`
5. `primary/CURRENT_STATE.json`
6. `supervision/CURRENT_STATE.json`
7. `primary/TASK_BOARD.json`
8. `supervision/MERGE_QUEUE.json`
9. `tasks/PILOT-010/CLOSEOUT.md`
10. `ledger/primary.jsonl` 与 `ledger/supervision.jsonl`

## §3 运行时操作手册

- Tower root：`C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh`
- Pilot repo：`C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh\pilot\repo`
- Pilot worktree：`C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh\pilot\worktrees\PILOT-010`
- Python：3.12.10；测试：`python -B -m unittest discover -s tools/tests -v`
- CLI：`python tools/towerctl.py <command>`
- 不读凭据、不调用生产、不部署；所有状态经 `towerctl`。

## §4 在途任务队列

- 无在途任务。
- 下一动作：new window: control-tower Q&A + map/portrait; then real project pilot

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
- 证据锚点以 package 与 task record 各自的列表为准，两侧条目数可能不同（如 `commit.txt` 可能只登记在 record 中）。
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
| 任务卡 | `tasks/PILOT-010/TASK.md` |
| 收口 | `tasks/PILOT-010/CLOSEOUT.md` |
| Ledger | `ledger/primary.jsonl`、`ledger/supervision.jsonl` |

**四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。**
