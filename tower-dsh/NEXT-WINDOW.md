# NEXT WINDOW — tower-dsh（2026-10-30：036 → 051）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）、
> `040`（空账本守卫）、`041`（deliver 范围门）、`042`（授权完成清单 + base_sha）、
> `044`（shape-check 形状门）、`045`（命令层 v1）、`046`（状态历史）、`047`（双视图位置图）、
> `048`（架构脊柱）、`049`（objective 硬门）、`050`（命令层接线）、`051`（依赖门）是收官后的十六张卡；
> `043` 暂缓 ready（未派）。
> 判例与残余见 `control-tower/MAP.md` §6.16–§6.30；蓝图见 `control-tower/COMMAND-LAYER.md`。

## 当前状态（2026-10-30 PILOT-051 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-051`：50 张 closed + `PILOT-043` ready 暂缓（未派）；50 个信封 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 585 tests / OK（skipped=1）`（569 + 051 新增 16；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 51 任务 / 50 信封 / 449 条证据 / drift 0；skipped 4（`025/039/041/044-VOID`） |
| 账本 | primary 468 / supervision 262 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| 形状门 | `shape-check` → exit 0（38 文件 / 1,603 函数；基线 1,114 条） |
| 架构门 | `arch-check` → exit 0（gates 16 / invariants 16 / events 29 / adrs 4 / sections 6；graph 38 nodes / 21 edges） |
| 目标门 | `tower/spec@2` + `objective` 四要素；`task-new` 零写入；`spec-lint` 只对 @2 强制；旧 @1 冻结 |
| 命令层 | `campaign-check` → exit 0（W1 0 + W4 2；`--strict` 仍红，strict 未开启）；`brief` → 23 行七节 |
| 依赖门 | `depends_on` 在 task-new（结构）、ready（闭合）、dispatch（闭合）三处硬校验；全塔 DFS 环检测 |
| 位置图 | `where --json` → **7/9**、current `PILOT-052`、next `PILOT-052`；位置条 `[✅045][✅046][✅047][✅048][✅049][✅050][✅051][▶052][ 053]` |
| CI | PR #7…#35 全绿；main 最近 run `41052580240` success（7m21s，head `af940d7`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=af940d7` |
| 036–042 | PR #21–#27；7/7；塔 `305/293`→`419/387` |
| 044 | PR #28 `129dd4e`；7/7（塔 `441/419`）；shape ratchet + REVIEW 五问 |
| 045 | PR #29 `99b61a1`；7/7（塔 `467/441`）；命令层 v1 + VOID 修复 |
| 046 | PR #30 `63d7b47`；7/7（塔 `487/467`）；状态历史 + E7/R3–R5/W3 |
| 047 | PR #31 `b4c7859`；7/7（塔 `518/487`）；双视图位置图；首轮 merge GraphQL EOF → 重试成功 |
| 048 | PR #32 `aaa4dfe`；7/7（塔 `536/518`）；架构脊柱 + ADR-0001 + arch-check；首轮/二轮 FAIL 后修文档事实/CI 归属/编码 |
| 049 | PR #33 `7d8ca4a`；7/7（塔 `552/536`）；spec@2 + objective 零写入门 + ADR-0002；test_arch 计数字面量用 completion |
| 050 | PR #34 `694f592`；9/9（塔 `569/552`）；dispatch campaign + W1 current/legacy + W2 open-only + post-merge/CI 两门；首轮 FAIL W1=050 → current 覆盖修复 |
| 051 | PR #35 `b37450b`；9/9（塔 `585/569`）；depends_on 结构/闭合/无环 + ADR-0004；test_objective 夹具用 completion |
| 043 | **ready 暂缓**（spec `8a28c80`）：记录层纵深（deliver 反查 completion 事件、state-verify 审计 base_sha、孤悬 drift） |

## 新窗口读序

1. `TOWER.md`（spec 环节含 objective 前置不变量）
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `command/STRATEGY.md` + `command/campaigns/*.md`
9. `towerctl where --json`（当前位置，7/9）
10. `ARCHITECTURE.md`（六节）+ `adr/ADR-0002/0003/0004`（objective / 接线 / 依赖门）
11. `arch/GATES.json`、`arch/INVARIANTS.json`、`EVENT_CATALOG.json`（架构门的数据面）
12. `control-tower/COMMAND-LAYER.md`（四本账 / 045–053 阶段）
13. `control-tower/MAP.md`（§6.9–§6.30）
14. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`
15. `RUN-2026-10-22-B.md`、`RUN-2026-10-23-C.md`、`RUN-2026-10-23-D.md`（批授权样本）

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py state-verify
python tools/towerctl.py authority-check      # 必须 exit 0 / configured / requirement=required
python tools/towerctl.py arch-check           # gates 16 / invariants 16 / events 29 / adrs 4
python tools/towerctl.py where --json         # 7/9；next PILOT-052
python tools/towerctl.py campaign-check       # exit 0；W1=0；--strict 仍因 W4 红
python tools/towerctl.py brief                # ≤60 行；七节
python tools/towerctl.py shape-check          # exit 0
python tools/towerctl.py spec-lint --strict   # 6/6；pilot @2 另由 spec-lint 扫
python -B tools/run_tests.py                  # 585 / OK (skipped=1)
```

`wiring` 不通过 = `ORPHANED`。`state-verify` drift = 先停。`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链（缺失/不可读/坏行致命）→ 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet（塔根基线、worktree 不得改/删基线）。
需要授权补齐时用 `completion-add`；需要放宽基线时走单独的 baseline-refresh 卡。
**新建 spec 必须带 `objective` 四要素**；新卡用 `@2`，旧 `@1` 冻结。
**有 active campaign 时 `dispatch --campaign <id>` 必填**；缺省/无效 exit 2。
**`depends_on` 在 ready/dispatch 必须闭合**；全塔有环会 exit 2。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-052` 对象层**（当前位置）：`PROFILE` + `profile-check`（∅5）。
2. **`PILOT-053` shape 接 CI + `towerctl` 模块化**（单文件 8k+ 行 → <3000）。
3. **`PILOT-043` 记录层纵深**（ready 暂缓，独立轨道）。
4. **契约级依赖（`contracts` + `spec-graph`）**：卡级依赖已通，下一层是 schema/event/command 的版本与影响图；建议排在对象层之前或并行评估。
5. **050/051 残余小卡**：`__FILL__` 前缀规则、长度按 grapheme、TASK.md/record 渲染 objective、board-only 依赖闭合、spec acceptance 的“恰 N 路径”措辞。
6. **GameCS 外部评审**：§四 6 问已作答；是否走正式 handoff/开卡由 owner 决定（当前未建包）。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；owner 给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`，且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**；**completion 只由 `completion-add --by <owner>` 写**；**baseline 变更只走 baseline-refresh 卡**；禁止手改这些文件或 ledger。
- **required / 缺失链 / 空账本+工件 / 越界 deliver / 伪造 completion / 新增形状债务 / 无 objective 新卡 / 未挂 campaign 派发 / 未闭合依赖 都不是可选项**（037–051）。
- **objective 是硬门**：新 spec 必须有四要素；`task-new` 在写 record/TASK/ledger 前拒绝，`spec-lint` 对 @2 强制；旧 @1 不回溯。
- **campaign 是派发门**：有 active campaign 时 `dispatch --campaign` 必填；W1 覆盖 `task_forces ∪ legacy_cards ∪ current ∪ dispatch.campaign`。
- **depends_on 是调度门**：task-new 结构、ready/dispatch 闭合、全塔无环；失败零写入。
- **TOWER.md 的 objective 行是 L0**：以后改它仍需 owner 逐次批准。
- **地图是地图，状态是状态**：`command/` 只写方向与战役；进度由 `status/` 快照与 `brief` 投影；不要把手写进度塞回 `STRATEGY.md`。
- **brief/where 是生成物**：手改即伪造；改内容去改来源（STRATEGY/campaign/record）。
- **index 语义 errata**：`where.index` = done 节点数（= 进度分子），不是 1-based 偏移；`next` 才是“下一站”。
- **`current` 要随进度改**：051 关闭后已把 campaign `current` 改为 `PILOT-052`；以后每关一卡同步推进。
- **`--strict` 仍红**（W4 2，052/053 未建档）；接 strict 前先回填。
- **新代码自己受 80 行/12 分支约束**：写不下就拆，别先写长再想着 baseline。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`。
- **spec 冻结**：改 spec 必须重建卡（v1 归档）；039/041/044 是 FAIL→VOID→v2 的样本。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.30）

- **046 R-1**：写失败未硬化（ACL 禁写/`status` 是文件时 index/rollup/snapshot 裸 Traceback exit 1，archive 静默 0）→ 052/053 补 `OSError → exit 2`。
- **046 R-2**：截断/损坏快照被 index 静默跳过；无“快照损坏”告警。
- **046 R-3**：重复 `task_forces` 会重复计数；**R-4**：archive 不清理外部已删快照的陈旧季档；**R-5**：样例快照 `wip 0/1` 对塔低报（已随 047 位置图部分修复）。
- **047 双分母**：同一条 status 里 `campaign (x/y)`（task_forces）与 `position x/9`（roadmap）并存，建议 052 统一或改名。
- **047 `where` vs `campaign-check` 错误码**：坏 campaign 时 `where` 报 E9 而非 E1；`skipped` 枚举不可达；WIP 全塔口径。
- **048 事件扫描只覆盖字面量/模块常量**：变量/f-string 传 type 会逃逸，`unresolved_event_calls` 只计数不失败（053 候选：非零 warning/exit 2）。
- **048 C-12/C-15 无自动化 proof**：probe 是 review/owner 执行点，arch-check 只证引用存在。
- **048 `GATE-SPEC-OBJECTIVE` 计数**：加门会把 `test_arch` 的 `gates=16` 打破；以后加门要同步改测试计数（或 completion）。
- **049 `__FILL__` 整值语义**：`TODO __FILL__`、`__FILL__x`、`补充 <待填写>` 能过；建议加“前缀 marker + 混合占位”规则。
- **049 长度按 code point**：ZWJ 家庭 emoji（7 code points）会被误判过短。
- **049 模板测试用子串、门口用整值**：口径不一致（仅模板测试）。
- **049 TASK.md/record 不渲染 objective**：spec 有、卡面没有；建议 052/053 补 `## Objective` 与 record 字段。
- **050 spec 冻结文本**仍写 skipped/W4=3；实际 A（不追加）+ W4=2；`legacy_cards` 不校验重复/存在；`-2 cards` 解析为正 2；CI campaign-check 非 strict；`current` 无 open liveness 校验。
- **051 依赖门假通过**：record 缺失时 closure 回退 board（board-only closed 可放行，state-verify 不报）；只查直接依赖（A→B closed→C open 可通过）；手改 record 成 string 时报错可读性差；`check --phase dispatch` 不复查依赖；全塔任一环冻结所有卡。
- **W1×0 / W4×2**：052/053 未建档；`--strict` 仍红（预期）。
- **记录层残余（043 未做）**：deliver 不反查 completion 备份事件；state-verify 不审计 base_sha；孤悬 completion 被忽略。
- **11 字节重开空账本守卫**：`{"seq": 1}` 仍可绕过（053 候选：只数 type+payload）。
- **legacy 塔 primary 清 0 字节**仍按 036 放行；**TOFU**（policy+event 双写并重算整链）仍靠 git 追踪做外部锚。
- **无密钥链**可重算伪造；`--by` 是字符串不是认证。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效；真实项目 pilot 未接。
- 工作区有无关目录 `review-gamcs-20261029/`（GameCS 评审），已本地 `.git/info/exclude`，不属于塔、未提交。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
