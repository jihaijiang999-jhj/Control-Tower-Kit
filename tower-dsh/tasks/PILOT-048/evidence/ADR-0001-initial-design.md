---
schema: tower/adr@1
id: ADR-0001
title: "初始设计提案 v0.3（历史）"
status: archived
date: 2026-10-19
deciders:
  - mac
related_cards: []
related_files:
  - tower-dsh/tools/towerctl.py
  - tower-dsh/ARCHITECTURE.md
---
# Tower/DSH — 控制塔重构设计 v0.3

> 状态：设计提案 v0.3，待 owner 拍板后进入实现。
> v0.2 变更：**双塔分离**、**文件化控制面**、**接线门**、**project-handoff v2.1**、**9 塔审计**。
> v0.3 变更：补上“站在所有 coding agent 之上的 control plane”定位、Boomi/Warp/MAQA 分工，
> 并把**首版范围收窄为 Core + Skill + Reviewer 门 + worktree 隔离**。
> 目标：不是复刻某一座现有塔，而是把它们的治理内核抽成一套
> DSH 原生、可实例化、可检查、可审计、可交接的控制塔。
>
> **代号：应县木塔 / Yingxian** —— 命名与构件隐喻见 [`NAMING.md`](NAMING.md)。

---

## 0. 一句话

把现有 9 座塔的共性抽成 **Tower Core + Tower Preset + Tower Skill + Tower Console + Tower Instance** 五件套；
每个实例内固定 **主控制塔（Primary）+ 监督控制塔（Supervision）** 双塔：
主塔把目标变成任务和交付，监督塔独立验收、串行合并、合并后验证。
**没有 `.ct` 运行时也能跑**——文件化控制面是默认形态。

---

## 0.1 定位：站在所有 coding agent 之上的 control plane

Tower/DSH 不训练更强的模型，也不做另一个 orchestrator。它站在 Claude Code、Codex、Cursor、Warp、Jules 等所有 coding agent 之上，负责五件事：

- **spec**：把意图变成可验收的规格、任务卡、验收条款；
- **routing**：选专业 owner、协作模式、模型/推理档；
- **gates**：四闸 + 阶段门 + PR/合并门；
- **evidence**：证据、哈希、版本、回执、账本；
- **handoff**：project-handoff v2.1 的交接与接续。

执行交给 `subagents` / cloud agents。Tower/DSH 不追求自己变强，而追求**让整支 agent 队伍的输出可信**。

## 0.2 与业界的分工

| 层 | 代表 | 强项 | 不覆盖 | Tower/DSH 的关系 |
|---|---|---|---|---|
| 企业 agent 治理 | Boomi Agent Control Tower / Agent Control Plane | agent 资产、身份、策略、可观测、agent sprawl | 编码工作流、PR/合并、spec/证据 | 借治理语义，不替代 |
| 编码编排 | Warp Factories、MAQA、Claude Code Agent Teams | 多 agent、worktree、任务队列、QA gate | owner 四闸、证据账本、交接状态机 | 站在它们之上，补治理层 |
| 规格驱动 | GitHub Spec Kit | Specify → Plan → Tasks → Implement → Converge | 运行时门禁、合并、证据审计 | 作为输入契约 |
| 单 agent 执行 | Claude Code、Codex、Cursor、Jules | 代码生成、工具、上下文 | 跨 agent 治理、owner 闸 | 把执行交给它们 |
| **Tower/DSH** | 本项目 | spec/routing/gates/evidence/handoff + 双塔 | 不训练模型、不做执行 | **control plane** |

一句话：**Boomi 管“企业里有哪些 agent”，Warp/MAQA 管“编码 agent 怎么并行干活”，Tower/DSH 管“这些 agent 的输出能不能被 owner 相信”。**

---

## 1. 从现有塔里提炼出的设计理念

v0.1 的 12 条仍然成立，v0.2 补 4 条：

1. **控制塔是治理角色，不是执行者。** 它负责路由、核验、收口、晋级；专项工作交给专项会话。
2. **Owner 主权。** 四个闸永远归 owner：merge / 真实外部调用 / 部署与生产数据 / L0 文档写 main。
3. **真值层级。** owner 决定 > 项目宪法 > 已批准规格 > 原始证据 > 聊天与推断。
4. **单一写者 + 执行路由。** 同一时刻只有一个控制塔写治理状态；不该它做的事不因为工具在手就自己做。
5. **证据优先于声明。** 文件存在、脚本通过、实际执行、独立接收、真实业务验收是五个不同层级。
6. **失败闭合。** 先命名失败类型，再选一个处置：下一动作 / 显式门槛 / 补证 / 熔断；不无限重试。
7. **连续性。** 启动读序、CURRENT、交接包、恢复说明是塔的一部分，不靠聊天记忆。
8. **最小状态复制。** 一份账本 + 投影；引用原始证据，不复制业务总账。
9. **收口契约。** 每个任务记录范围、证据、验证、变更、副作用、失败、门变化、下一步。
10. **显式授权。** advisory / read_only / workspace_write / runtime_mutation / production_enforcement 五级，不能从角色描述自动扩张。
11. **可审计。** 哈希、版本、回执、时间、执行者，缺一不可。
12. **自动化最后。** 手动流程跑稳、完成规定周期后，才允许上心跳/调度。

v0.2 新增：

13. **职责分离。** 作者 ≠ 独立验收者 ≠ 合并批准者；同一个人格不能同时持有“提交”和“合并”权限。
14. **自动权限上限。** 工程 PR 轨可以给常备授权；生产轨默认无权限，必须逐次 owner 决定。
15. **诚实能力缺口。** 同 GitHub 身份、无服务端分支保护、无密码学身份等缺口要写明补偿控制，不假装已解决。
16. **接线门。** 塔必须被 `AGENTS.md` / `README.md` / `START-HERE.md` 引用；否则视为“孤儿基建”，不算塔。

---

## 2. 现有实现的取舍

| 来源 | 保留 | 不搬 |
|---|---|---|
| **BI CODE UP 03/04 双塔** | 双塔职责分离、`PROJECT_PROFILE`、`AUTHORITY_MODEL`、PR 状态机、串行合并队列、两提交合并信封、合并后验证、机制改进注册表、上下文轮换注册表 | BI 业务事实、仓库清单、G2–G7 具体内容 |
| **CT-HOME / `.ct` 运行时** | identity、registration anchor、checkpoints、ledger、tasks/returns、profile、forbiddenActions、hostPlanes | 版本化 bootstrap runtime 的全部实现细节；不要求每座塔都装 `.ct` |
| **project-handoff v2.1** | 交出塔台写包、整包重生成、真相源指针化、§0/§0a 实值、七节正文、交出自查、接收首验、断路器 | 各项目专册的具体命令/路径/口令 |
| **GameShield 主塔** | 四闸、权限分级、`tower_gate.py` 的 ready/deliver/accept/close、模板化任务卡/交付/评审/收口 | 39KB 的 GameShield 业务宪法、GameShield 专属任务状态 |
| **智能客服控制塔** | 单一 owner、`CURRENT.json`、启动读序、独立入口、`startup_check` 只读核验 | `create_thread` / `wait_threads` / `list_projects` 这类 Kimi 桌面线程 API |
| **SeeMake Governance Tower** | 两轴路由（专业 owner + 协作模式）、owner-decision 独立闸、promotion rule、pending work register | 具体 workstream 注册表、Feishu/PM Agent 写入链 |
| **SeeMake-K3** | `tower-exam` / `tower-clerical` 的角色区分：只读自证 vs 文书候选；K3 单执行器治理层 | Codex 多会话线程机制 |
| **BI-CLEAN-REBUILD（反例）** | 业务定义、项目简报、施工/交接文档、检查点 | **只做文档、不做状态/身份/验证/交接/双塔**；7 份文件未接线，不构成可运行控制塔 |

**结论：** 保留“治理语义”，用 DSH 的 session / subagent / skill / plugin 重新实现；
`.ct` 是可选运行时，不是控制塔的前提。

---

## 3. 新架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  Tower Console（DSH 客户端插件）                               │
│  只读：双塔状态 / 四闸 / 合并队列 / 任务 / 阻塞 / 下一步        │
├──────────────────────────────────────────────────────────────┤
│  Tower Presets（DSH agent presets）                            │
│  tower-primary：拆解、派发、PR、提交合并信封，无 merge 权       │
│  tower-supervisor：独立验收、串行合并、合并后验证，无实现权      │
│  Tower Skill：启动读序、任务卡、核验、收口、交接 v2.1           │
├──────────────────────────────────────────────────────────────┤
│  Tower Core（协议层，项目无关）                                │
│  schema / 事件账本 / 双塔门禁 / towerctl / 模板 / 接线检查      │
├──────────────────────────────────────────────────────────────┤
│  Tower Instance（项目实例）                                    │
│  tower/shared + tower/primary + tower/supervision              │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 五件套

1. **Tower Core** — 项目无关的协议：状态 schema、事件类型、双塔门禁、`towerctl`、模板。
2. **Tower Preset** — 两个 DSH agent preset：`tower-primary`、`tower-supervisor`。
3. **Tower Skill** — 模型可加载的操作手册：启动、路由、派发、核验、收口、交接 v2.1。
4. **Tower Console** — 只读状态面板；不写状态，避免第二写者。
5. **Tower Instance** — 每个项目一份 `tower/` 目录，绑定项目宪法、owner、四闸、路径和证据根。

### 3.2 双塔模型

| 角色 | 谁 | 拥有 | 禁止 |
|---|---|---|---|
| **Owner** | 人 | 四闸、生产读写、外部调用、部署/切流、数据迁移、退役、终局合同变更 | 不代替主塔做日常路由 |
| **Primary Control Tower** | `tower-primary` 会话 | 目标拆解、任务卡、职责窗口、分支/worktree、commit/push、PR 创建与修正、提交合并信封 | 实际 merge、以自查代替独立验收、改监督塔的合并决定/队列 |
| **Supervision Control Tower** | `tower-supervisor` 会话 | 独立验收、串行合并队列、实际 merge、合并后验证、纠正单、机制审计 | 改候选 PR 实现、批准自己的实现、跳过必需证据 |
| **Executor** | 子 agent / 专项会话 | 在任务卡范围内实施、交付证据 | 改治理状态、merge、晋级 |
| **Reviewer** | 独立子 agent / 独立会话 | 亲查证据、独立复算、出评审结论 | 与执行者同一上下文，不以作者自查代替 |

**职责分离不变量：**

- `pr_author_must_not_be_merge_approver`
- `merge_must_follow_dependency_order`
- `merge_requires_machine_valid_merge_envelope`
- `merge_requires_independent_checkback`
- `merged_is_not_complete_until_post_merge_verified`
- `repository_authority_does_not_imply_production_authority`

**自动权限上限（来自 BI CODE UP）：**

| 轨道 | 风险 | 常备授权 |
|---|---|---|
| 工程 PR 轨 | 可逆的新仓工程 | 主塔可走完整日常 PR 生命周期，**但不含 merge** |
| 生产轨 | 真实系统影响 | **none**；逐次 owner 决定 + 独立证据门 |

> `global_pause_authority` 只归 owner，入口是监督塔；主塔不能全局暂停，也不能把局部等待升级为全局阻塞。

### 3.3 文件化控制面优先

`.ct` 运行时不是必需。默认采用 **file-backed control plane**：

```text
shared/PROJECT_PROFILE.yaml      # 项目、根目录、权限上限、轨
shared/AUTHORITY_MODEL.yaml      # 双塔角色、owner 保留、分离不变量
shared/TARGET.md                 # 不可被局部里程碑替代的终局
primary/CURRENT_STATE.yaml       # 当前门、下一动作、局部等待
primary/TASK_BOARD.yaml          # 任务卡与状态
primary/registries/              # gate / evidence / decision / routing / queue
primary/work-packages/           # 工作包
supervision/CURRENT_STATE.yaml   # 监督塔状态
supervision/MERGE_QUEUE.yaml     # 唯一串行合并队列
supervision/registries/merge-ledger.yaml
supervision/outbox/corrections/  # 纠正单
tools/towerctl.py                # 机器检查
```

原则：

- 文件是权威，聊天/窗口状态不是；
- 每个塔只写自己的目录；
- `shared/` 由 owner 控制，主塔提案、监督塔复核；
- `.ct` 可选：需要 identity/checkpoint/ledger 的运行时时再挂，不因缺 `.ct` 退化成纯文档塔。

### 3.4 接线门（v0.2 新增）

一座塔如果没有被入口引用，就是**孤儿基建**。强制：

- `AGENTS.md` 必须包含 `TOWER.md` 指针；
- `README.md` 或 `START-HERE.md` 必须说明启动读序；
- `towerctl wiring check` 验证：
  - `TOWER.md` 存在；
  - `AGENTS.md` 含 `tower/TOWER.md`；
  - `START-HERE.md` 含 `CURRENT_STATE` 路径；
  - `shared/PROJECT_PROFILE.yaml` 指向正确的 `workspace_root`；
  - 新增的塔文件不是“只被自己引用”。

未通过接线门 → 状态 `ORPHANED`，不计入“已建成塔”。

### 3.5 交接 v2.1（project-handoff）

采用 `project-handoff` 技能的 v2.1 机制，不自造一套：

- **三原则**：交出塔台写包 / 整包重生成 / 真相源指针化。
- **包结构**：§0 实值 + §0a 漂移警示 + 七节正文 + 交出自查 + 校验。
- **交出**：实值复核 → 整包重生成 → 装配路径 → 流水收官条 → 高危零半截自查。
- **接续**：读最新包 → 项目宪法 → 真相源/流水尾部 → 在途锚点；**只读自检** → 报一句结果 + 在途清单 → 停，等 owner 口令。
- **纪律**：只读自检、凭据零回显、不认预填结论、四闸归 owner、断路器、诚实账。
- **DSH 适配**：把 Kimi 的窗口交接映射为 `towerctl handoff` + `claim` 两阶段；`project-handoff` 的 6 本专册作为只读参考，不整包复制业务。

> 现有 `project-handoff/references/` 实际有 6 本：`gameradar`、`gameshield`、`game-cs`、`seemake-k3`、`ci-self-hosted-runner`、`infra`；不是 4 本。

---

## 4. 状态模型

### 4.1 目录

```text
tower/
├─ TOWER.md                     # 实例身份 + 接线入口
├─ AGENTS.md                    # 项目宪法（必须指向 TOWER.md）
├─ START-HERE.md                # 启动读序
├─ shared/
│  ├─ PROJECT_PROFILE.yaml      # 项目/根/权限上限/轨
│  ├─ AUTHORITY_MODEL.yaml      # 双塔角色/owner 保留/分离不变量
│  ├─ TARGET.md                 # 终局目标
│  └─ PROJECT-MAP.md            # 仓库/环境/真值入口
├─ primary/
│  ├─ CURRENT_STATE.yaml
│  ├─ TASK_BOARD.yaml
│  ├─ WORK_PACKAGES/
│  ├─ decisions/
│  ├─ registries/
│  │  ├─ gate-registry.yaml
│  │  ├─ evidence-registry.yaml
│  │  ├─ evidence-acceptance-registry.yaml
│  │  ├─ decision-registry.yaml
│  │  ├─ model-routing-registry.yaml
│  │  └─ work-package-orchestration.yaml
│  ├─ handoffs/                 # 交给监督塔的合并信封
│  └─ evidence/
├─ supervision/
│  ├─ CURRENT_STATE.yaml
│  ├─ MERGE_QUEUE.yaml
│  ├─ TASK_BOARD.yaml
│  ├─ reviews/
│  ├─ outbox/corrections/
│  └─ registries/
│     ├─ merge-ledger.yaml
│     ├─ mechanism-improvement-register.yaml
│     └─ context-rotation-register.yaml
├─ ledger/
│  ├─ primary.jsonl
│  └─ supervision.jsonl
├─ receipts/
├─ handoffs/
└─ tools/
   ├─ towerctl.py
   └─ templates/
```

### 4.2 `PROJECT_PROFILE.yaml`

```yaml
schema_version: '0.1'
project_id: 'TOWER-DSH'
project_name: 'DeepSeek Harness Control Tower'
control_tower_version: '0.2'
operating_mode: 'goal_mode_control_tower'
control_tower_execution_policy: 'dispatch_only_no_direct_domain_execution'
workspace_root: 'C:/Users/mac/Documents/deepseek-harness/default-workspace'
automatic_authority_ceiling:
  engineering_pr_track: 'full_daily_PR_lifecycle_except_merge'
  production_track: 'no_access'
current_gate: 'G0'
global_pause_authority: 'human_owner_via_supervising_control_tower_only'
```

### 4.3 `AUTHORITY_MODEL.yaml`

```yaml
schema_version: '0.1'
authorization_id: 'TOWER-DSH-AUTH-001'
authorized_by: 'human_owner'
operating_model: 'dual_tower_separation_of_duties'
roles:
  primary_control_tower:
    owns: [goal_decomposition, task_cards, branch_and_worktree, commit_and_push,
           pr_create_and_update, merge_envelope_submission]
    forbidden: [merge_pull_request, substitute_self_review,
                rewrite_supervisor_decision]
  supervising_control_tower:
    owns: [independent_acceptance, serial_merge_queue, actual_merge,
           post_merge_validation, correction_return, mechanism_audit]
    forbidden: [edit_candidate_implementation, approve_own_implementation,
                bypass_required_evidence]
  human_owner:
    reserves: [production_read_write, real_external_call, deployment_and_traffic,
               data_migration, legacy_retirement, terminal_contract_change]
separation_invariants:
  - 'pr_author_must_not_be_merge_approver'
  - 'merge_must_follow_dependency_order'
  - 'merge_requires_machine_valid_merge_envelope'
  - 'merge_requires_independent_checkback'
  - 'merged_is_not_complete_until_post_merge_verified'
  - 'repository_authority_does_not_imply_production_authority'
```

### 4.4 `CURRENT_STATE.yaml`（主塔/监督塔各一份）

```yaml
schema_version: '0.1'
goal_status: 'ACTIVE_WITH_LOCAL_WAITS'
current_gate: 'G2'
runtime_truth: 'unverified'
next_actions:
  - '……'
local_waits:
  - wait_id: '……'
    failure_class: 'data_gap'
    disposition: 'next_action'
    global_effect: 'none'
forbidden_progress_claims:
  - 'merged_pull_request_equals_terminal_completion'
  - 'source_evidence_equals_runtime_truth'
```

### 4.5 `MERGE_QUEUE.yaml`（只有监督塔写）

```yaml
schema_version: '0.1'
entries:
  - envelope_id: 'ME-001'
    pr: 42
    base: 'main'
    head: 'feature/x'
    dependency: null
    status: 'WAITING'   # WAITING | CHECKING | MERGE_APPROVED | MERGING | MERGED | CORRECTION_REQUIRED
    implementation_head_sha: 'A'
    envelope_head_sha: 'B'
    merged_sha: null
```

### 4.6 `ledger/*.jsonl`

每个塔一份追加式账本：

```json
{"seq":1,"at":"…","type":"DECISION","actor":"owner","payload":{"id":"D-001"}}
{"seq":2,"at":"…","type":"DISPATCH","actor":"primary","payload":{"task":"T-001"}}
{"seq":3,"at":"…","type":"RETURN","actor":"executor","payload":{"task":"T-001"}}
{"seq":4,"at":"…","type":"CHECKBACK","actor":"supervisor","payload":{"task":"T-001"}}
{"seq":5,"at":"…","type":"MERGE","actor":"supervisor","payload":{"envelope":"ME-001"}}
{"seq":6,"at":"…","type":"POST_MERGE_VERIFY","actor":"supervisor","payload":{"result":"PASS"}}
```

投影（`CURRENT_STATE`、`TASK_BOARD`、`MERGE_QUEUE`）必须能由账本 + 任务文件重放得到。

---

## 5. 生命周期与门禁

### 5.1 任务生命周期

```text
INTAKE → ROUTE → READY → DISPATCHED → RETURNED → CHECKBACK
      → ACCEPT / REWORK → CLOSEOUT → HANDOFF
```

| 阶段 | 必须有什么 | 检查 |
|---|---|---|
| INTAKE | 目标、对象、owner、真值入口 | `check --phase intake` |
| ROUTE | 专业 owner、协作模式、权限等级、owner-decision | `check --phase route` |
| READY | 任务卡、范围、允许/禁止、依赖、验收、回执格式 | `check --phase ready` |
| DISPATCHED | 派发记录、执行者、模型/推理档、任务卡哈希 | `check --phase dispatch` |
| RETURNED | 交付封面、逐条证据、实际检查值、失败分类 | `check --phase deliver` |
| CHECKBACK | 独立评审、证据绑定、无作者自查代替 | `check --phase review` |
| ACCEPT | owner/授权人决定、证据版本有效、无越界 | `check --phase accept` |
| CLOSEOUT | 范围、证据、副作用、门变化、下一动作 | `check --phase close` |
| HANDOFF | v2.1 包、§0/§0a、自查、包哈希、接收方 claim | `check --phase handoff` |

### 5.2 PR / 交付状态机

代码仓使用 PR 状态机（来自 BI CODE UP）：

```text
DRAFT
  → READY_FOR_SUPERVISOR
  → INDEPENDENT_CHECKBACK
  → CORRECTION_REQUIRED | MERGE_APPROVED
  → MERGED
  → POST_MERGE_VERIFIED
```

非 Git 交付使用等价状态机：

```text
DRAFT → DELIVERED → INDEPENDENT_CHECKBACK
      → REWORK | ACCEPTED → POST_ACCEPT_VERIFIED
```

规则：

- `CORRECTION_REQUIRED` 必须命名具体失败模式、限界处置、可执行验收命令；
- 修正留在同一 PR，除非原范围失效；重开 PR 必须链接旧 PR 和关闭理由；
- `MERGED` / `ACCEPTED` 不是完成态，只有目标分支/目标环境验证通过才是 `POST_MERGE_VERIFIED` / `POST_ACCEPT_VERIFIED`。

### 5.3 串行合并队列

- 监督塔独占写 `MERGE_QUEUE.yaml`；
- 同一时刻只允许一个 `MERGING`；
- 顺序：依赖 → 兼容性/风险 → 到达时间（最后才用）；
- 基础提交漂移时必须重新验收，不允许沿用旧批准；
- 禁止“带病合并”；任一门失败 → 纠正单或熔断。

### 5.4 两提交合并信封

候选 PR 最后两步固定：

1. 主塔形成实现提交 `A`；
2. 主塔形成只改合并信封的提交 `B`。

信封记录 `implementation_head_sha=A`，不记录包含自身的 `B`。
监督塔用 GitHub CLI 独立读取当前 head `B`，证明 `B` 的父提交是 `A`、`B` 只修改信封路径；合并回执记录 `A`、`B`、最终 merge commit。

任何纠正都会使旧批准失效；主塔必须产生新的 `A` 和新的 `B`，监督塔重新读取 head 并复核。

### 5.5 四闸与自动权限上限

四闸（永远独立于阶段门）：

- `merge`
- `external_call`
- `deploy_prod`
- `l0_main`（AGENTS/治理主干写入）

阶段门通过 **不等于** 四闸通过。四闸必须逐次 owner 决定，记录到 `DECISIONS.md`/`decision-registry` 和 ledger。

自动权限上限：

- 工程 PR 轨：主塔可走完整日常 PR 生命周期，**不含 merge**；
- 生产轨：`no_access`；生产读取、外部真实调用、部署、切流、数据迁移、退役都必须单独授权 + 证据门；
- 两条轨不能通过文件命名、脚本包装或 PR 合并相互隐式授权。

### 5.6 权限等级

| 等级 | 允许 | 典型 |
|---|---|---|
| `advisory` | 分析、建议、解释 | 研究、诊断 |
| `read_only` | 只读发现、核验、复算 | 独立评审、监督塔检查 |
| `workspace_write` | 任务卡允许的工作区写入 | 实施 |
| `runtime_mutation` | 启动服务、改远端配置、生产准备 | 需明确授权 |
| `production_enforcement` | 真实处罚、封禁、生产数据动作 | 逐次 owner 精确批准 |

### 5.7 Promotion rule

专项会话的产出默认只是 **evidence**，不是项目真值。晋级前检查：

- 范围是否完成、改动是否匹配授权；
- 验证是否实跑，失败是否分类；
- 是否含秘密/原始隐私/凭据；
- L2/L3 假设是否已记成 gate 或 owner decision；
- 证据身份、版本、哈希是否匹配；
- 晋级子集、目标路径、证据处置是否明确；
- 是否经过独立 checkback；
- `MERGED` 是否已 `POST_MERGE_VERIFIED`。

---

## 6. DSH 映射

| 塔概念 | DSH 机制 | 说明 |
|---|---|---|
| Primary 会话 | 运行 `tower-primary` preset 的 DSH session | 用户在创建会话时选 preset |
| Supervision 会话 | 运行 `tower-supervisor` preset 的独立 session | 不与主塔同一会话/同一上下文 |
| 控制塔手册 | `~/.agents/skills/control-tower/SKILL.md` | 与现有 arkcli 技能同一发现机制 |
| Executor | `subagent`（spawn）或用户专项会话 | 任务卡 + 明确禁止项 |
| Reviewer | `subagent`（fresh context）或独立会话 | 必须亲跑证据，不能只看执行者摘要 |
| Owner 决定 | `ask_user_question` + `DECISIONS.md`/`decision-registry` + ledger | 结构化选项，不靠聊天“同意” |
| Checkback | `send_message` / `list_agents` / `job_output` + 证据文件 | 不看“已完成”字样，看原始输出 |
| 长任务 | `create_goal` + `schedule_create` + `job_*` | 只做提醒/状态，不自动晋级 |
| 交付物 | `present` | 文件卡片 |
| 状态面板 | DSH 客户端插件页面 | 只读 `CURRENT_STATE`/`TASK_BOARD`/`MERGE_QUEUE` |
| 检查器 | `python towerctl.py …` | 本地 Python，JSON 输出，0/2 退出码 |
| 权限 | DSH permission preset + skill 内四闸 | 主塔 `workspace_write`，监督塔 `read_only`（merge 由受控命令执行） |
| 合并 | 监督塔专用命令/服务 | 主塔 preset 不暴露 merge 工具 |

### 会话身份（DSH 的限制与补法）

DSH 没有 Kimi 的 `create_thread` / `wait_threads`。因此：

- 主塔启动时生成 `primary.id = ctl-<uuid>`，写入 `primary/CURRENT_STATE.yaml`；
- 监督塔启动时生成 `supervisor.id = sup-<uuid>`，写入 `supervision/CURRENT_STATE.yaml`；
- owner 在两个会话里分别确认一次“本会话是 primary/supervisor”；
- 交接采用两阶段：
  1. 旧塔写 `handoffs/<id>/`，`status = PREPARED`；
  2. 新会话运行 `towerctl claim --package <id>`，写 `CLAIM.json`，`status = READY_FOR_RECEIVER`；
  3. 旧塔核 claim 的 `id`、包哈希、包摘要，写 `ACCEPTED` 后停写；
  4. 新塔读 `CURRENT_STATE`，写启动回执。
- 这是**程序性锁**，不是密码学身份；真正的保证来自 owner 在场确认 + 回执 + 证据 + 独立监督。

### 与 Kimi 的差异

- 不复制 `create_thread` / `wait_threads` / `list_projects`；
- 不把“窗口存在/空闲”当权威；
- 不依赖桌面应用 UI 状态；
- 不复制项目专属业务规则，只保留可迁移的治理协议。

---

## 7. 检查器 `towerctl.py`

一个入口，子命令，机器可读：

```bash
python towerctl.py init      --root tower --tower-id tower-dsh
python towerctl.py wiring    --root tower
python towerctl.py startup   --root tower --role primary|supervision
python towerctl.py check     --root tower --task T-001 --phase ready
python towerctl.py hash      <path>
python towerctl.py dispatch  --root tower --task T-001 --executor <id> --model <model>
python towerctl.py deliver   --root tower --task T-001 --evidence E-001
python towerctl.py checkback --root tower --task T-001 --reviewer <id> --verdict PASS
python towerctl.py accept    --root tower --task T-001 --decision D-002
python towerctl.py close     --root tower --task T-001
python towerctl.py envelope  --root tower --pr 42 --implementation A --envelope B
python towerctl.py merge     --root tower --envelope ME-001
python towerctl.py post-merge --root tower --envelope ME-001 --result PASS
python towerctl.py handoff   --root tower --role primary --package <id>
python towerctl.py claim     --root tower --package <id> --controller ctl-<uuid>
python towerctl.py status    --root tower
```

规则：

- 只读优先；写操作只改自己拥有的状态文件，并追加 ledger；
- `wiring` 失败 → `ORPHANED`；
- `check` 输出 `{ok, errors[], warnings[], phase, task}`；
- 退出码 `0` 通过，`2` 不通过；
- 不执行任务正文、不跑网络、不读未引用文件；
- 失败时保留原始错误，不把“工具不可用”说成“检查通过”。

---

## 8. 现有塔审计与迁移

### 8.1 现有 9 座塔

| # | 塔 | 根 | 形态 | 状态/缺口 |
|---|---|---|---|---|
| 1 | BI 主控制塔 | `D:\BI CODE UP\03-control-tower` | 文件化双塔 | G2，工程 PR 轨，无 merge 权 |
| 2 | BI 监督控制塔 | `D:\BI CODE UP\04-supervision-control-tower` | 文件化双塔 | 独立验收/串行合并，最成熟 |
| 3 | CT-REAL-BI-TAKEOVER-01 | `D:\CT-REAL-BI-TAKEOVER-01` | CT-HOME runtime | `.ct` 全，文档/交接薄 |
| 4 | CT-GAME-CREATIVE-OPS-01 | `D:\CT-GAME-CREATIVE-OPS-01` | CT-HOME runtime | `.ct` 全，业务资产多 |
| 5 | BI-CLEAN-REBUILD | `D:\BI-CLEAN-REBUILD` | 文档塔 | 7 文件就位，未运营 |
| 6 | GameShield 主塔 | `D:\game  os` | 混合 | 四闸+Codex 包+CS 子塔 |
| 7 | 智能客服控制塔 | `D:\game  os\work\智能客服控制塔` | 文件塔+skill | 交接 v2.1，强 |
| 8 | SeeMake Governance Tower | `D:\SeeMake` | 治理流程 | 旧塔/已改名废弃 |
| 9 | SeeMake-K3 塔台 | `D:\SeeMake-K3\_k3-ops` | K3 治理层 | 单执行器，无 5 文件标准 |

不计入：`D:\CT-EP`（空）、`D:\BI CODE UP\03-control tower`（空格旧副本）、`D:\quant-K3`（无塔规则）。

### 8.2 BI-CLEAN-REBUILD 的 9 个遗漏

1. **来源漏了 BI CODE UP 双塔**：报告没有引用 `03/04`，这是最成熟的 BI 控制塔。
2. **形态选错**：因 `.ct` 未安装退成纯文档塔；但 BI CODE UP 证明无 `.ct` 也能跑文件化双塔。
3. **状态层缺失**：无 `CURRENT_STATE`/`TASK_BOARD`/`EVIDENCE`/`DECISIONS`/`RECOVERY`/`START-HERE`；只有 46KB 检查点。
4. **身份/权限层缺失**：无 `PROJECT_PROFILE`/`AUTHORITY_MODEL`/controller identity/`profile.json`。
5. **验证层缺失**：无 `tower_gate.py`/`validate-control-tower.py`/`startup_check.py`；只有语法检查。
6. **交接层只有草稿**：无 v2.1 模板、§0 锚点、交接包、接收自查；专册未落位。
7. **没有双塔监督**：无双塔、合并队列、合并账本、post-merge verification；作者=验收者风险。
8. **接线缺失**：`AGENTS.md`/`README.md`/`MAINLINE_CHECKPOINT.md` 都没引用新增 7 文件；grep 只在新文件自身命中。
9. **seed 只有合同，没有资产**：`seed/` 只有 README + schema，没有实际证据清单/样本/冻结 manifest。

> 另：报告说 project-handoff “四本专册”，实际 `references/` 有 6 本（gameradar / gameshield / game-cs / seemake-k3 / ci-self-hosted-runner / infra）。

### 8.3 其他塔的缺口

- **CT runtime 双塔**：`.ct` 的 identity/registration/checkpoint 齐全；缺 `MAINLINE_CHECKPOINT.md`、`docs/handoff` 专册、project-handoff v2.1；状态是 `.ct` 内部格式，人读入口弱。
- **BI CODE UP 双塔**：治理最成熟；但没有全局 `AGENTS.md`/`README` 入口，也没有 CT-HOME 注册；状态是文件化，不是 `.ct`。
- **GameShield**：四闸、Codex 规范包、客服子塔很强；但没有统一 5 文件业务定义/项目简报，状态分散在 `operator_workspace`、`ai-game-ops`、`work/智能客服控制塔`。
- **SeeMake**：只有 governance workflow；无状态/证据/交接层；已改名“废弃seem”。
- **SeeMake-K3**：`_k3-ops` + workflows 完整；无 5 文件标准；交接走 `_k3-ops` 模板，不走 `project-handoff`。
- **CT-EP**：空壳，0 文件。

### 8.4 迁移策略

1. **不整体复制**：现有塔继续在各自目录运行，作为只读参考。
2. **抽协议，不抽业务**：只迁四闸、权限、双塔、任务卡、证据、交接、收口。
3. **文件化优先**：先建 `tower/shared + primary + supervision` 文件骨架；`.ct` 只在需要 identity/checkpoint 时挂。
4. **新实例优先**：先建一个 greenfield 实例跑通，再把 BI CODE UP/GameShield 作为第二个实例接入。
5. **历史只引用**：旧塔的 `CURRENT/WORK` 不复制成新塔的总账，只记“来源 + 迁移决定”。
6. **双向不覆盖**：新塔不修改旧塔状态；旧塔的 owner 仍是旧塔的 owner。

---

## 9. 分阶段落地

| 阶段 | 交付 | 验收 |
|---|---|---|
| **0. 设计** | 本文档 v0.3 | owner 确认双塔、文件化、交接 v2.1、首版收窄、首实例 |
| **1. 首版（收窄）** | Core + Skill + Reviewer 门 + worktree 隔离：schema/ledger/templates、`tower-primary` preset、独立 reviewer、worktree 隔离、接线门、`towerctl` 基础 | 一个任务 `READY → DISPATCHED → RETURNED → REVIEW → ACCEPT`，reviewer 独立、worktree 隔离、接线门通过；**不含 merge/生产/双塔/Console** |
| **2. 双塔** | `tower-supervisor` preset、`MERGE_QUEUE`、PR 状态机、两提交信封、post-merge | 主塔不能 merge；监督塔能独立验收并合并；分离不变量检查通过 |
| **3. 交接 v2.1** | `project-handoff` 适配、§0/§0a、七节包、claim | 两个 DSH 会话完成一次完整交接 |
| **4. Console** | DSH 客户端插件只读面板 | 面板状态与文件一致，无写权限 |
| **5. 自动化** | `schedule`/`goal` 提醒 | 手动跑稳后才开，且只提醒不晋级 |

### 9.1 首版范围（v0.3 收窄）

**做：**

- Tower Core：schema、ledger、模板、`towerctl init/wiring/startup/check/hash`
- Tower Skill：启动读序、路由、任务卡、reviewer 门
- `tower-primary` preset
- 独立 Reviewer（`subagent` fresh context，read-only）
- worktree 隔离（每个 executor 一个 worktree，one file one owner）
- 接线门（AGENTS/README/START-HERE → TOWER.md）

**不做（留到后续阶段）：**

- merge / 合并队列 / 两提交信封（Phase 2）
- 监督塔与双塔分离（Phase 2）
- 生产/外部调用/部署（四闸，永远 owner）
- Console（Phase 4）
- 自动化/心跳（Phase 5）

**首版验收：**

- 一个真实任务走完 `READY → DISPATCHED → RETURNED → REVIEW → ACCEPT`（不 merge）
- Reviewer 与 Executor 不同上下文，亲跑证据
- worktree 隔离，主工作树无脏写
- `towerctl wiring` 通过，没有孤儿文件

---

## 10. 验收标准（v1）

- **首版**：一个任务走完 `READY → DISPATCHED → RETURNED → REVIEW → ACCEPT`（不 merge），reviewer 独立、worktree 隔离、接线门通过；
- 接线门通过：`AGENTS.md`/`README.md`/`START-HERE.md` 都指向 `TOWER.md`；
- 一个任务能从 `INTAKE` 走到 `CLOSEOUT`，每个阶段 `check` 通过；
- 主塔不能 merge；监督塔能独立验收并合并；`pr_author != merge_approver` 检查通过；
- 两提交合并信封可被监督塔独立复算；`MERGED` 必须 `POST_MERGE_VERIFIED`；
- 账本能重放出 `CURRENT_STATE`/`TASK_BOARD`/`MERGE_QUEUE` 的当前值；
- 一次 project-handoff v2.1 交接完成，旧塔停写、新塔有启动回执；
- Console 只读，不能改状态；
- 所有四闸动作都有 `decision-registry` + ledger 记录；
- 没有“只被自己引用”的孤儿塔文件。

---

## 11. 待 owner 拍板

1. **首实例选哪个？**
   - A. `tower-dsh`：绿field，先跑通机制（推荐）
   - B. BI CODE UP：直接接最成熟的双塔，但业务包袱重
   - C. GameShield 主塔：四闸/Codex 包成熟
   - D. 智能客服控制塔：交接 v2.1 最完整
2. **第一版要不要 Console？**
   - A. 先 Skill + CLI，Console 放第四阶段（推荐）
   - B. 一开始就做只读 Console
3. **命名**：`Tower/DSH`、`DSH Tower`、`控制塔 v2`，选一个。
4. **主塔默认权限**：`workspace_write` 还是 `read_only`（治理只读，执行另开）？
5. **小任务是否保留 `tower-lite` 快路径**（不建完整任务卡，只记 ledger + 回执）？
6. **首版是否按 v0.3 收窄？**
   - A. 是：Core + Skill + Reviewer 门 + worktree 隔离，不做 merge/双塔/Console（推荐）
   - B. 否：首版就上双塔
7. **双塔 Phase 2 是否确认？** 推荐 Phase 2，但在任何 merge 之前必须完成。
8. **PR 状态机**：直接采用 BI CODE UP 的 `DRAFT → … → POST_MERGE_VERIFIED`，还是先做简化版？推荐直接采用。

---

## 附录 A · 现有塔清单

| # | 塔 | 根 | 形态 |
|---|---|---|---|
| 1 | BI 主控制塔 | `D:\BI CODE UP\03-control-tower` | 文件化主塔 |
| 2 | BI 监督控制塔 | `D:\BI CODE UP\04-supervision-control-tower` | 文件化监督塔 |
| 3 | CT-REAL-BI-TAKEOVER-01 | `D:\CT-REAL-BI-TAKEOVER-01` | CT-HOME runtime |
| 4 | CT-GAME-CREATIVE-OPS-01 | `D:\CT-GAME-CREATIVE-OPS-01` | CT-HOME runtime |
| 5 | BI-CLEAN-REBUILD | `D:\BI-CLEAN-REBUILD` | 文档塔 |
| 6 | GameShield 主塔 | `D:\game  os` | 混合 |
| 7 | 智能客服控制塔 | `D:\game  os\work\智能客服控制塔` | 文件塔 + skill |
| 8 | SeeMake Governance Tower | `D:\SeeMake` | 治理流程（旧） |
| 9 | SeeMake-K3 塔台 | `D:\SeeMake-K3\_k3-ops` | K3 治理层 |

## 附录 B · 关键参考

- BI 双塔：`D:\BI CODE UP\03-control-tower\README.md`、`04-supervision-control-tower\README.md`、`AUTHORITY_MODEL.yaml`、`SUPERVISION_PROTOCOL.md`
- CT 运行时：`D:\CT-HOME\profiles`、`D:\CT-REAL-BI-TAKEOVER-01\.ct`
- 交接 v2.1：`%APPDATA%\kimi-desktop\daimon-share\daimon\skills\project-handoff\SKILL.md` 及 `references/`
- BI-CLEAN 迁移报告：`D:\BI-CLEAN-REBUILD\governance\infra-migration-20261004\MIGRATION_REPORT.md`

---

*本文是设计提案，不含实现代码。确认后从 Phase 1 开始落地。*
