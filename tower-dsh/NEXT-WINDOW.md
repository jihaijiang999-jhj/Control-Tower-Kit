# NEXT WINDOW — tower-dsh（2026-11-01：036 → 059）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）、
> `040`（空账本守卫）、`041`（deliver 范围门）、`042`（授权完成清单 + base_sha）、
> `044`（shape-check 形状门）、`045`（命令层 v1）、`046`（状态历史）、`047`（双视图位置图）、
> `048`（架构脊柱）、`049`（objective 硬门）、`050`（命令层接线）、`051`（依赖门）、
> `052`（对象层）、`053`（信封恢复）、`054`（记录层）、`055`（shape CI + re-dispatch）、`057`（ID 注册表）、`058`（结构化 REVIEW）、`059`（验收 A/M）是收官后的二十三张卡；`043` 已 superseded（closed、无 envelope）；`056` 模块化 reserved。
> 判例与残余见 `control-tower/MAP.md` §6.16–§6.35；蓝图见 `control-tower/COMMAND-LAYER.md`；
> 批次章程见 `control-tower/RUN-2026-10-30-E.md` 与 `RUN-2026-11-01-F.md`。

## 当前状态（2026-11-01 PILOT-059 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-059`：58 张 closed（含 043 superseded）；58 个信封 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 675 tests / OK（skipped=1）`（660 + 059 新增 15；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 58 任务 / 58 信封 / 543 条证据 / drift 0；skipped 8 |
| 账本 | primary 571 / supervision 316 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| 形状门 | `shape-check` → exit 0（38+ 文件 / 1,600+ 函数；基线 1,114 条） |
| 架构门 | `arch-check` → exit 0（gates 17 / invariants 16 / events 29 / adrs 8 / sections 6；graph 45 nodes / 25 edges） |
| 目标门 | `tower/spec@2` + `objective` 四要素；`task-new` 零写入；`spec-lint` 只对 @2 强制；旧 @1 冻结 |
| 命令层 | `campaign-check` → exit 0（C-2026-Q4-02 3/3；`--strict` 现状以实跑为准）；`brief` → 23 行七节 |
| 依赖门 | `depends_on` 在 task-new（结构）、ready（闭合）、dispatch（闭合）三处硬校验；全塔 DFS 环检测 |
| 对象层 | `state/PROFILE-TEMPLATE.md` + `state/PROFILE-TOWER-DSH.md`（11 行 / 10 逻辑事实）；`profile-check` 11/0 |
| 信封恢复 | `ENVELOPE_NEW` 保留已有状态；`envelope-new` 拒绝重开 MERGED；`merge` 只拦“重信后 DRAFT” |
| 位置图 | `where --json` → **3/3**、current `PILOT-059`、next `null`；位置条 `[✅057][✅058][✅059]`（C-2026-Q4-02 完成） |
| CI | PR #7…#42 全绿；main 最近 run `41318462958` success（head `1c8cd31`，含 Shape check 第 8 步）；059 用本地 supervisor merge `1c249fa`（PR #43 head race 关闭） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=1c8cd31` |
| 036–042 | PR #21–#27；7/7；塔 `305/293`→`419/387` |
| 044 | PR #28 `129dd4e`；7/7（塔 `441/419`）；shape ratchet + REVIEW 五问 |
| 045 | PR #29 `99b61a1`；7/7（塔 `467/441`）；命令层 v1 + VOID 修复 |
| 046 | PR #30 `63d7b47`；7/7（塔 `487/467`）；状态历史 + E7/R3–R5/W3 |
| 047 | PR #31 `b4c7859`；7/7（塔 `518/487`）；双视图位置图；首轮 merge GraphQL EOF → 重试成功 |
| 048 | PR #32 `aaa4dfe`；7/7（塔 `536/518`）；架构脊柱 + ADR-0001 + arch-check；首轮/二轮 FAIL 后修文档事实/CI 归属/编码 |
| 049 | PR #33 `7d8ca4a`；7/7（塔 `552/536`）；spec@2 + objective 零写入门 + ADR-0002；test_arch 计数字面量用 completion |
| 050 | PR #34 `694f592`；9/9（塔 `569/552`）；dispatch campaign + W1 current/legacy + W2 open-only + post-merge/CI 两门；首轮 FAIL W1=050 → current 覆盖修复 |
| 051 | PR #35 `b37450b`；9/9（塔 `585/569`）；depends_on 结构/闭合/无环 + ADR-0004；test_objective 夹具用 completion |
| 052 | PR #36 `27c1872`；post-merge **9/9 重跑**（塔 `609/609`）；对象层 + profile-check；AUTH required 修复；CI probe 可移植性修复；baseline 585→609 |
| 053 | PR #37 `e8d69f3`；9/9（塔 `609/601`）；re-envelope 恢复 + ADR-0005；052 post-merge 随之重跑通过 |
| 054 | PR #39 `bc823b1`；9/9（塔 `630/609`）；记录层：completion 反查 + DISPATCH base_sha 权威 + 孤悬 drift；043 v2 改号；R1 关闭 |
| 055 | PR #40 `2fe7a11`；9/9（塔 `638/630`）；shape 接 CI 第 8 步 + re-dispatch 窄语义；055 v1/v2 归档 |
| 057 | PR #41 `a28426c`；9/9（塔 `646/638`）；ID 注册表/不复用；056 reserved |
| 058 | PR #42 `a0e8f52`；9/9（塔 `660/646`）；REVIEW head/base + expected-head merge |
| 059 | 本地 supervisor merge `1c249fa`；9/9（塔 `675/660`）；ACCEPTANCE A/M；PR #43 因 head race 关闭 |
| 043 | **superseded**：v1/v2 均归档；保留一条 closed、无 envelope 的记录满足旧 `TASK_NEW`；`ENV-PILOT-043` 仍 CORRECTION 但 branch 已删、不可 merge，待 abandon/tombstone 卡 |

## 新窗口读序

1. `TOWER.md`（spec 环节含 objective 前置不变量）
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `command/STRATEGY.md` + `command/campaigns/*.md`
9. `towerctl where --json`（当前位置，3/3）
10. `ARCHITECTURE.md`（六节）+ `adr/ADR-0002/0003/0004/0005/0009`
11. `state/PROFILE-TEMPLATE.md` + `state/PROFILE-TOWER-DSH.md`（对象层）
12. `arch/GATES.json`、`arch/INVARIANTS.json`、`EVENT_CATALOG.json`
13. `control-tower/COMMAND-LAYER.md` + `RUN-2026-10-30-E.md`
14. `control-tower/MAP.md`（§6.9–§6.35）
15. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py state-verify
python tools/towerctl.py authority-check      # 必须 exit 0 / configured / requirement=required
python tools/towerctl.py arch-check           # gates 17 / invariants 16 / events 29 / adrs 8
python tools/towerctl.py profile-check        # 11/0
python tools/towerctl.py where --json         # 3/3；next null（C-2026-Q4-02 完成）
python tools/towerctl.py campaign-check       # exit 0；W1=0；--strict 仍因 W4 红
python tools/towerctl.py brief                # ≤60 行；七节
python tools/towerctl.py shape-check          # exit 0
python tools/towerctl.py spec-lint --strict   # 6/6；pilot @2 另由 spec-lint 扫
python -B tools/run_tests.py                  # 675 / OK (skipped=1)
```

`wiring` 不通过 = `ORPHANED`。`state-verify` drift = 先停。`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链（缺失/不可读/坏行致命）→ 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet。
需要授权补齐时用 `completion-add`；需要放宽基线时走单独的 baseline-refresh 卡。
**新建 spec 必须带 `objective` 四要素**；新卡用 `@2`，旧 `@1` 冻结。
**有 active campaign 时 `dispatch --campaign <id>` 必填**；缺省/无效 exit 2。
**`depends_on` 在 ready/dispatch 必须闭合**；全塔有环会 exit 2。
**失败后重封信封必须保留状态**；`MERGED`/`POST_MERGE_VERIFIED` 不能重开。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-056` 模块化**：已 reserved；23 模块/4 层 DAG，每模块 <600；`towerctl.py` <3000（目标 <500）；22 个长函数基线迁移；`GATE-MODULES` + `test_modules`。055 的 shape CI 是安全网。
2. **043 cleanup 卡**：`envelope-abandon`/tombstone 命令，清掉 stale `ENV-PILOT-043` 与 queue 条目；顺带修 054 evidence 文案与 spec 计数。
3. **052 evidence refresh**：052 的 evidence 快照早于 CI 修复（`07efc9c` vs `0a8bf31`），建议补一次受控刷新或记录为永久残余。
4. **C 补齐**：`queue-add` DRAFT→WAITING（会破 15+ 既有夹具，需同步改夹具/夹具 helper）或收敛“入队后重信”路径。
5. **GameCS 外部评审**：§四 6 问已作答；是否走正式 handoff/开卡由 owner 决定（当前未建包）。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；owner 给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`，且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**；**completion 只由 `completion-add --by <owner>` 写**；**baseline 变更只走 baseline-refresh 卡**；禁止手改这些文件或 ledger。
- **required / 缺失链 / 空账本+工件 / 越界 deliver / 伪造 completion / 新增形状债务 / 无 objective 新卡 / 未挂 campaign 派发 / 未闭合依赖 都不是可选项**（037–053）。
- **objective 是硬门**；**campaign 是派发门**；**depends_on 是调度门**；**PROFILE 是对象门**（每条事实一个只读 probe）。
- **信封恢复**：失败后重信保留状态；MERGED 不能重开；merge 只拦“重信后 DRAFT”；C（queue-add DRAFT→WAITING）尚未做。
- **TOWER.md 的 objective 行是 L0**：以后改它仍需 owner 逐次批准。
- **地图是地图，状态是状态**：`command/` 只写方向与战役；进度由 `status/` 快照与 `brief` 投影。
- **brief/where 是生成物**：手改即伪造；改内容去改来源。
- **index 语义 errata**：`where.index` = done 节点数；`next` 才是“下一站”。
- **`current` 要随进度改**：059 关闭后 C-2026-Q4-02 `current` 仍为 059，next null；056 需新 campaign/roadmap。
- **`--strict` 以实跑为准**（C-02 3/3；W3/W4 需重跑确认）。
- **新代码自己受 80 行/12 分支约束**：写不下就拆。
- **状态提交只在 envelope 之后**。
- **spec 冻结**：改 spec 必须重建卡（v1 归档）；039/041/044/053 是 FAIL→VOID→v2 的样本。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.35）

- **046 R-1**：写失败未硬化（ACL 禁写/`status` 是文件时 index/rollup/snapshot 裸 Traceback exit 1，archive 静默 0）→ 054 补 `OSError → exit 2`。
- **046 R-2**：截断/损坏快照被 index 静默跳过；无“快照损坏”告警。
- **046 R-3**：重复 `task_forces` 会重复计数；**R-4**：archive 不清理外部已删快照的陈旧季档；**R-5**：样例快照 `wip 0/1` 对塔低报。
- **047 双分母**：`campaign (x/y)` 与 `position x/10` 并存，建议 054 统一或改名。
- **047 `where` vs `campaign-check` 错误码**：坏 campaign 时 `where` 报 E9 而非 E1；`skipped` 枚举不可达；WIP 全塔口径。
- **048 事件扫描只覆盖字面量/模块常量**：变量/f-string 传 type 会逃逸，`unresolved_event_calls` 只计数不失败（054 候选）。
- **048 C-12/C-15 无自动化 proof**：probe 是 review/owner 执行点，arch-check 只证引用存在。
- **048 `GATE-SPEC-OBJECTIVE` 计数**：加门会把 `test_arch` 的 `gates=17` 打破；以后加门要同步改测试计数。
- **049 `__FILL__` 整值语义**：`TODO __FILL__`、`__FILL__x`、`补充 <待填写>` 能过；建议加“前缀 marker + 混合占位”规则。
- **049 长度按 code point**：ZWJ 家庭 emoji 会被误判过短。
- **049 TASK.md/record 不渲染 objective**：spec 有、卡面没有；建议 054 补 `## Objective` 与 record 字段。
- **050 spec 冻结文本**仍写 skipped/W4=3；实际 A（不追加）+ W4 变化；`legacy_cards` 不校验重复/存在；`-2 cards` 解析为正 2；CI campaign-check 非 strict。
- **051 依赖门假通过**：record 缺失时 closure 回退 board；只查直接依赖；手改 record 成 string 报错可读性差；全塔任一环冻结所有卡。
- **052 AUTH 曾漏 required**：已拆 AUTH/AUTH-CONF；`profile-check` 的 `expect` 只支持单子串，多字段要拆行。
- **052 evidence 快照过期**：evidence 停在 `07efc9c`，最终代码 `0a8bf31`；靠 053 CI/post-merge 兜底，不是干净证据链。
- **053 C 未做**：`queue-add` 不改 DRAFT；`envelope-new → queue-add → envelope-new` 会被 D 守卫钉死，无 CLI 出口；ADR-0005 已记录，后续卡补 C 或收敛路径。
- **053 测试非 hermetic**：`test_real_tower_history_has_no_envelope_drift` 直读塔账本，瞬时 drift 会拖红套件。
- **053 D 守卫窄**：只拦“重信后 DRAFT”；非 DRAFT 垃圾状态与首封 DRAFT 不拦；真正保护在 replay。
- **W1×0 / W4×1**：054 未建档；`--strict` 仍红（预期）。
- **记录层（054 已做）**：deliver 反查 completion、DISPATCH base_sha 权威、state-verify 审计 base_sha/孤悬；残余 R3（skipped 空 completions + dangling event 不报）、R4（同 path 多事件只比第一条）。
- **re-dispatch（055）**：从 `dispatched` 重派会重算 `base_sha`；若只替换 executor，后续 main 前移会改变 deliver 基线；同 executor 重派仍合法。建议 056 或 follow-up 加固。
- **055 过程**：v1 模块化 9 模块数学不可行（8,863 > 8,390）→ 拆卡；v2 中间版归档 VOID2；8 步 CI 已实跑。
- **057/058/059 已完成**：58/58、675 tests、where 3/3；C-2026-Q4-02 3/3。056 reserved，需 claim 后开模块化。
- **059 merge deviation**：PR #43 checks 绿但 gh pr merge --match-head-commit 连续报 Head branch modified；用本地 supervisor merge 1c249fa，PR 关闭。
- **058 legacy**：仅 pre-058（≤57）且无 REVIEW；058+ 无 REVIEW/无 structured CHECKBACK 均 stale。
- **059 legacy**：仅 task number ≤58；缺/旧 created_at 不再豁免。
- **043 stale envelope**：`ENV-PILOT-043` CORRECTION_REQUIRED + queue 条目；branch 已删，merge-check 失败，但 commit 可复活；需 abandon/tombstone 卡。
- **054 evidence 文案**：commit.txt 仍写“043 no envelope”，事实是 stale CORRECTION + 分支删除；spec 计数 53/52 实际 54/53。
- **11 字节重开空账本守卫**：`{"seq": 1}` 仍可绕过。
- **legacy 塔 primary 清 0 字节**仍按 036 放行；**TOFU** 靠 git 追踪做外部锚。
- **无密钥链**可重算伪造；`--by` 是字符串不是认证。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查。
- `ready→TASK_NEW` 仍合法；关闭卡无正式 reopen；052 的 post-merge 重试依赖 envelope 重信（已记录）。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`。
- 分支保护对 admin 无效；真实项目 pilot 未接。
- 工作区有无关目录 `review-gamcs-20261029/`（GameCS 评审），已本地 `.git/info/exclude`。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
