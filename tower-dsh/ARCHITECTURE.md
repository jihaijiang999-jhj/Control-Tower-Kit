---
schema: tower/architecture@1
id: ARCH-001
version: 1
updated: 2026-10-29
review_by: 2026-12-31
owner: mac
---

# ARCH-001 — tower-dsh 架构（一页活文档）

> 这是 HOW 账：**当前结构是什么、为什么这么设计、以后怎么改**。
> 机读部分：`arch/GATES.json`（门表）、`arch/INVARIANTS.json`（红线 probe）、
> `EVENT_CATALOG.json`（事件目录）、`adr/`（关键决策）。
> `towerctl arch-check` 把本文档说的与代码有的逐条对账；文档过期即 exit 2。

## 1. 系统上下文

**塔管什么**：把意图变成可验收的事实——spec、任务卡、路由、门禁、证据、
账本、合并信封、交接。所有事实都落成文件，可 diff、可复算、可审计。

**塔不管什么**：

- 不执行任务：执行在 `pilot/worktrees/<ID>` 的隔离 worktree 里，由 executor 完成；
- 不运行产品代码、不部署、不接生产、不读凭据、不联网（`merge --mode pr` 是唯一出网路径）；
- 不代替 owner 决定四闸：merge / 外部调用 / 部署·生产数据 / L0 文档写 main。

**边界**：单实例、单写者、串行合并。塔是控制面，不是 orchestrator，也不训练模型。

## 2. 组件与职责

| 组件 | 位置 | 职责 | 不碰 |
|---|---|---|---|
| Primary | `primary/` | spec、routing、任务卡、worktree、commit、信封、证据、closeout | merge、生产、外部调用 |
| Supervision | `supervision/` | 独立验收、串行合并队列、实际 merge、post-merge 验证、纠正单 | 候选实现、自批 |
| Ledger | `ledger/primary.jsonl` / `ledger/supervision.jsonl` | 只追加的权威事实链（seq + prev_hash + hash） | 手改 |
| Tasks | `tasks/<ID>/{TASK.md,record.json,evidence/,DELIVERY.md,REVIEW.md}` | 任务卡与证据 | 绕过 `towerctl` 写 |
| Pilot | `pilot/<ID>.spec.json` + `pilot/worktrees/<ID>/` | 冻结 spec、隔离执行区 | merge |
| Tools | `tools/towerctl.py`、`tools/run_tests.py`、`tools/spec_lint.py`、`tools/spec_coverage.py` | 唯一状态/门禁 CLI 与静态检查 | 联网、写塔外路径 |
| CI | `.github/workflows/tower-gate.yml` | 只读复跑 5 步：unit tests / spec-lint --strict / spec-coverage / verify-ledger / status；shape/state-verify/authority/campaign/arch 在 049 接入 CI | 改状态、merge |
| Docs | `ARCHITECTURE.md`、`arch/`、`adr/`、`EVENT_CATALOG.json` | WHY/HOW 的可证伪描述 | 冒充权威（代码与 ledger 才是） |

## 3. 数据流

```text
spec (pilot/<ID>.spec.json)
  → task-new       记录 TASK_NEW，冻结 spec_path + spec_sha256，状态 ready
  → spec-approve   记录 SPEC_APPROVED（批准人 ≠ executor）
  → check --phase spec / ready   记录 CHECK；spec_gate=PASS 才能 dispatch
  → dispatch       记录 DISPATCH，锚定 dispatch.base_sha，状态 dispatched
  → deliver        scope / base_sha / shape 三闸 → 复制证据 → 记录 DELIVER
  → checkback      独立 reviewer，PASS → reviewed，FAIL → rework
  → accept         reviewed → accepted（证据哈希复核）
  → close          accepted → closed（CLOSEOUT 证据落盘）
  → envelope-new   记录 ENVELOPE_NEW，DRAFT
  → queue-add      记录 QUEUE_ADD，WAITING（两条 tests 基线）
  → merge          记录 MERGE_START / MERGE（或 MERGE_BLOCKED / MERGE_FAILED）
  → post-merge     独立复跑 → 记录 POST_MERGE_VERIFIED（或 POST_MERGE_FAILED）
  → CI             当前 5 步：unit tests / spec-lint --strict / spec-coverage /
                   verify-ledger / status（GATE-CI）；shape/state-verify/authority/
                   campaign/arch 于 049 接入 CI
```

每一步的输入/输出都是文件：ledger 事件是权威，record/board/queue/envelope 是
工作副本，`state-verify` 用 ledger 重放并比对工作副本；不一致即 drift。

## 4. 关键契约

**事件**：`EVENT_CATALOG.json` 是唯一目录（29 条：primary 19 / supervision 10）。
每条声明 `ledger`、`producer`（真实子命令）、`payload_required`、
`state_verify`、`drift_kinds`、`note`。目录与代码**双向**对账（AST 扫描三个
ledger writer 的字面 type）：代码有而目录无、目录有而代码无都 exit 2；
`state-verify` 只重放目录中 `state_verify=true` 的
生命周期事件（未知名默认被忽略——这是已知边界，不是许可）。

**状态**：`primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、
`supervision/CURRENT_STATE.json`、`supervision/MERGE_QUEUE.json`、
`supervision/envelopes/*.json`、`state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json`。
状态文件只能由 `towerctl` 写；手改会被 `state-verify` / `authority-check` 报 drift。

**命令**：`python tools/towerctl.py <cmd>` 是唯一入口；argparse 的子命令名是
命令名的权威，`arch/GATES.json.gates[].command` 必须命中它。

**证据**：所有完成声明必须有 sha256 证据（`tasks/<ID>/evidence/`）、ledger 事件
与 `check_evidence` 复核；`MERGED` 不等于完成，只有 `POST_MERGE_VERIFIED` 是。

**门表**：`arch/GATES.json`（15 道门，含 spec/ready/dispatch/deliver 三闸/review/
accept/close/envelope/queue/merge-check/merge 前置/post-merge/CI）。每道门优先指向
**拒绝路径**测试（负例）；`weak: true` 表示该门当前只有正例测试，只证“能过”、
不证“会拒”。本卡 15 道门均为负例（或无 `weak` 字段）。
**红线 probe**：`arch/INVARIANTS.json`（C-01..C-16，每条一个真实测试或真实命令）。
**决策**：`adr/`（`tower/adr@1`，status ∈ proposed|accepted|superseded|archived）。

## 5. 扩展点

| 要加什么 | 步骤 | 影响面 |
|---|---|---|
| 门 | ① `towerctl` 里实现并在真实测试中覆盖；② `arch/GATES.json` 加一条 `{id,command,phase,test,blocks}`；③ 本节/§4 引用；④ `arch-check` 绿灯 | 门表、CI、reviewer 检查单 |
| 命令 | ① 写 `cmd_*`（新 layer 函数，不改既有函数行数/分支）；② parser 注册 + `COMMAND_LAYER_HANDLERS`；③ 测试（正例 + 反例 exit 2 单 JSON）；④ 文档提及 | CLI 表面、shape 棘轮、GATES.command 集合 |
| 事件 | ① `append_ledger` 用字面 type（或模块常量）；② **同卡**补 `EVENT_CATALOG.json`（producer 必须是真实命令）；③ 需要重放时补 `state-verify` 规则与 drift kind；④ 测试 | 目录双向一致、state-verify、审计 |
| 字段 | ① 只追加、不改名（L1 兼容性）；② 先 ADR（`adr/ADR-00NN-*.md`）；③ schema 校验与迁移计划；④ 测试 | adapter/legacy 回退、arch-check、下游读取方 |

原则：**文档不可证伪就不写**。任何“结构变了”都必须让 `arch-check` 或测试变红，
否则视为文档谎言。

## 6. 不变量

红线条款见 `RED-LINES.md`（C-01..C-16），机读映射见 `arch/INVARIANTS.json`：

- **owner-gate**（C-01/02/03/04/05/06/07/15/16）：执行点是 `merge`、
  `dispatch`、`post-merge` 的授权/分支/现场校验；塔只记录决定，不代替 owner。
- **tool-check**（C-09/11/14）：ledger 哈希链、`checkback` 拒绝自审、`dispatch`/`merge`/
  `post-merge` 拒绝跳闸。
- **review-check**（C-08/10/12/13）：`state-verify` 重放、`deliver` 范围门、完成声明必须
  引用 ledger 事件与证据哈希；C-12（凭据零回显）由 review 执行，`merge` 只是最近的
  出网执行点。

> **C-12 / C-15 没有自动化 proof**：`arch/INVARIANTS.json` 里它们的 `probe` 只是
> review/owner 的执行点，不是“已证明”的测试；`arch-check` 只验证该执行点存在。

**已知边界（Known limits）**：

1. **单文件**：`tools/towerctl.py` 7,981 行（约 8k；本卡 HEAD 实测）；模块化
   （PILOT-051）之前，所有命令共享一个进程与一个 parser。
2. **无密钥链**：owner 四闸依赖人工决定与记录，没有密码学签名；信任是 TOFU
   （首次设置即信任，之后靠 revision 与事件复核）。
3. **legacy 兼容**：无 `dispatch.base_sha` 的旧卡回退到 `merge-base main HEAD`；
   无 baselines 的旧信封跳过部分门。
4. **事件目录只覆盖字面量/模块常量**：`append_ledger`、`append_supervision_ledger` 与
   低层 `_append_ledger_event_locked` 的字面 type 都会扫描（`COMPLETION_ADDED` 由低层
   writer 写入，因此也在目录里）。**任何非字面量传 type（变量、f-string、字符串拼接）
   都会逃逸**，`arch-check` 的 `counts.unresolved_event_calls` 只**计数不失败**
   （051 候选：非零即 warning 或 exit 2）。新增非字面事件必须人工补目录，
   否则 `state-verify` 默认放行。
5. **arch-check 只证“引用存在”**：它证明门/ probe/事件有落点，不证明语义正确；
   语义证据在 `tools/tests/*.py`。
6. **单写者假设**：primary 与 supervision 串行；并行战役未实现（见 STRATEGY 非目标）。
7. **归档正文不可改**：`adr/ADR-0001-initial-design.md` 的正文是 v0.3 提案逐字节原文，
   其中的相对链接（如 `NAMING.md`）按原位置 `control-tower/` 解读，不随文件移动重写。
