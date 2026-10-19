# Control-Tower-Kit

> 代号：**应县木塔 / Yingxian**（见 `control-tower/NAMING.md`）
> 一个文件化、可审计、可交接的 AI 编码控制面（control plane），跑在 DeepSeek Harness 之上。

## 是什么

- **DSH** 是执行 harness：模型 + 工具 + subagent 运行时，让 agent 能干活。
- **本 kit** 是控制面：spec / routing / gates / evidence / merge / handoff，让活可验收、可追溯、可交接。
- 它不执行任务、不部署、不碰生产；执行交给 subagent，验收交给独立 reviewer，合并交给监督塔。

## 结构

```text
control-tower/            设计文档 v0.3 + 代号 NAMING.md
tower-dsh/                第一个实例（Phase 3 active）
├─ TOWER.md               身份与边界
├─ AGENTS.md              宪法
├─ START-HERE.md          启动读序（含接续口令消歧）
├─ RED-LINES.md           红线（触碰即停）
├─ CHANGE-LEVELS.md       变更分级 L0–L3
├─ primary/               主塔状态、任务板、注册表
├─ supervision/           监督塔、合并队列、合并账本、合并后验证
├─ tasks/                 任务卡、交付、评审、收口、证据
├─ ledger/                追加式账本（primary / supervision）
├─ handoffs/              project-handoff v2.1 交接包
├─ tools/towerctl.py      唯一状态/门禁 CLI
└─ AUDIT-2026-10-19.md    首次全面体检（6 个 P0 / 16 个 P1）
```

## 快速开始

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py supervision-status
```

`wiring` 不返回 `WIRED` 即为 `ORPHANED`，不得宣称塔已建成。

## 当前状态

- Phase 3：`HANDOFF-PILOT-001` ACTIVE，controller `ctl-phase3-receiver-001`
- 任务：`PILOT-001` … `PILOT-005` 全部 `closed` 且 `POST_MERGE_VERIFIED`
- 门禁：spec 强制、证据强制、reviewer 非空、merge 分支断言（PILOT-002）
- post-merge：清洁检查先于写 review，可从 `CORRECTION_REQUIRED` 重试（PILOT-003）
- handoff：按 task/envelope 参数化，无写死（PILOT-004）
- ledger：SHA-256 哈希链 + 单写者锁 + `verify-ledger`（PILOT-005）
- 剩余 backlog：见 `tower-dsh/AUDIT-2026-10-19.md` 未修 P1/P2（closeout 文案、程序性身份、路径过滤等）

## 边界

- 四闸永远归 owner：**merge / 外部调用 / 部署·生产数据 / L0 文档写 main**。
- Primary 不 merge；Supervision 独占合并队列。
- 不读凭据、不碰生产、不部署。

## 未纳入本仓

- `tower-dsh/pilot/repo`（pilot 的 git 仓库）与 `tower-dsh/pilot/worktrees/`（worktree）；
- 其源码副本保留在 `tower-dsh/tasks/PILOT-001/evidence/`；
- 见 `.gitignore`。
