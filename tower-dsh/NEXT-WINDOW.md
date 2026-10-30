# NEXT WINDOW — tower-dsh（2026-10-30：036 → 049）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）、
> `040`（空账本守卫）、`041`（deliver 范围门）、`042`（授权完成清单 + base_sha）、
> `044`（shape-check 形状门）、`045`（命令层 v1）、`046`（状态历史）、`047`（双视图位置图）、
> `048`（架构脊柱）、`049`（objective 硬门）是收官后的十四张卡；`043` 暂缓 ready（未派）。
> 判例与残余见 `control-tower/MAP.md` §6.16–§6.28；蓝图见 `control-tower/COMMAND-LAYER.md`。

## 当前状态（2026-10-30 PILOT-049 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-049`：48 张 closed + `PILOT-043` ready 暂缓（未派）；48 个信封 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 552 tests / OK（skipped=1）`（536 + 049 新增 16；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 49 任务 / 48 信封 / 420 条证据 / drift 0；skipped 4（`025/039/041/044-VOID`） |
| 账本 | primary 448 / supervision 250 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| 形状门 | `shape-check` → exit 0（36 文件 / 1,515 函数；基线 1,114 条） |
| 架构门 | `arch-check` → exit 0（gates 16 / invariants 16 / events 29 / adrs 2 / sections 6；graph 36 nodes / 21 edges） |
| 目标门 | `tower/spec@2` + `objective` 四要素；`task-new` 零写入；`spec-lint` 只对 @2 强制；旧 @1 冻结 |
| 命令层 | `campaign-check` → exit 0（W1 44 + W4 3；`--strict` 仍红，回填属 050）；`brief` → 23 行七节 |
| 位置图 | `where --json` → **5/8**、current `PILOT-050`、next `PILOT-050`；位置条 `[✅045][✅046][✅047][✅048][✅049][▶050][ 051][ 052]` |
| CI | PR #7…#33 全绿；main 最近 run `40918631043` success（7m1s，head `298bdf5`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=298bdf5` |
| 036–042 | PR #21–#27；7/7；塔 `305/293`→`419/387` |
| 044 | PR #28 `129dd4e`；7/7（塔 `441/419`）；shape ratchet + REVIEW 五问 |
| 045 | PR #29 `99b61a1`；7/7（塔 `467/441`）；命令层 v1 + VOID 修复 |
| 046 | PR #30 `63d7b47`；7/7（塔 `487/467`）；状态历史 + E7/R3–R5/W3 |
| 047 | PR #31 `b4c7859`；7/7（塔 `518/487`）；双视图位置图；首轮 merge GraphQL EOF → 重试成功 |
| 048 | PR #32 `aaa4dfe`；7/7（塔 `536/518`）；架构脊柱 + ADR-0001 + arch-check；首轮/二轮 FAIL 后修文档事实/CI 归属/编码 |
| 049 | PR #33 `7d8ca4a`；7/7（塔 `552/536`）；spec@2 + objective 零写入门 + ADR-0002；test_arch 计数字面量用 completion |
| 043 | **ready 暂缓**（spec `8a28c80`）：记录层纵深（deliver 反查 completion 事件、state-verify 审计 base_sha、孤悬 drift） |

## 新窗口读序

1. `TOWER.md`（spec 环节已含 objective 前置不变量）
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `command/STRATEGY.md` + `command/campaigns/*.md`
9. `towerctl where --json`（当前位置，5/8）
10. `ARCHITECTURE.md`（六节）+ `adr/ADR-0002-spec-objective.md`（objective 门决策）
11. `arch/GATES.json`、`arch/INVARIANTS.json`、`EVENT_CATALOG.json`（架构门的数据面）
12. `control-tower/COMMAND-LAYER.md`（四本账 / 045–052 阶段）
13. `control-tower/MAP.md`（§6.9–§6.28）
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
python tools/towerctl.py arch-check           # gates 16 / invariants 16 / events 29 / adrs 2
python tools/towerctl.py where --json         # 5/8；next PILOT-050
python tools/towerctl.py campaign-check       # exit 0；--strict 仍因 W1/W4 红（050 前预期）
python tools/towerctl.py brief                # ≤60 行；七节
python tools/towerctl.py shape-check          # exit 0
python tools/towerctl.py spec-lint --strict   # 6/6；pilot @2 另由 spec-lint 扫
python -B tools/run_tests.py                  # 552 / OK (skipped=1)
```

`wiring` 不通过 = `ORPHANED`。`state-verify` drift = 先停。`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链（缺失/不可读/坏行致命）→ 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet（塔根基线、worktree 不得改/删基线）。
需要授权补齐时用 `completion-add`；需要放宽基线时走单独的 baseline-refresh 卡。
**新建 spec 必须带 `objective` 四要素**（`problem/outcome/approach/non_goals_and_done`）；缺项/占位/过短时 `task-new` 零写入拒绝；旧 `@1` 冻结，新卡用 `@2`。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-050` 接线/回填**（当前位置）：dispatch 必填 `campaign`；`campaign-check`/`arch-check` 进 post-merge/CI；回填 44 张 W1 孤儿卡（W1 清零）后再决定 `--strict`。
2. **`PILOT-051` 对象层**：`PROFILE` + `profile-check`（∅5）。
3. **`PILOT-052` shape 接 CI + `towerctl` 模块化**（单文件 8k+ 行 → <3000）。
4. **恢复 `PILOT-043`**：记录层纵深（独立轨道）。
5. **GameCS 外部评审**：§四 6 问已在会话作答；是否走正式 handoff/开卡由 owner 决定（当前未建包）。
6. **objective 门的 049 残余**：`TODO __FILL__`/`__FILL__x`/`补充 <待填写>` 仍可过；可并入 051 或单独小卡。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；owner 给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`，且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**；**completion 只由 `completion-add --by <owner>` 写**；**baseline 变更只走 baseline-refresh 卡**；禁止手改这些文件或 ledger。
- **required / 缺失链 / 空账本+工件 / 越界 deliver / 伪造 completion / 新增形状债务 / 无 objective 新卡 都不是可选项**（037–049）。
- **objective 是硬门**：新 spec 必须有四要素；`task-new` 在写 record/TASK/ledger 前拒绝，`spec-lint` 对 @2 强制；旧 @1 不回溯。
- **TOWER.md 的 objective 行是 L0**：以后改它仍需 owner 逐次批准。
- **地图是地图，状态是状态**：`command/` 只写方向与战役；进度由 `status/` 快照与 `brief` 投影；不要把手写进度塞回 `STRATEGY.md`。
- **brief/where 是生成物**：手改即伪造；改内容去改来源（STRATEGY/campaign/record）。
- **index 语义 errata**：`where.index` = done 节点数（= 进度分子），不是 1-based 偏移；`next` 才是“下一站”。
- **`current` 要随进度改**：049 关闭后已把 campaign `current` 改为 `PILOT-050`；以后每关一卡同步推进。
- **`--strict` 在 050 回填前必红**（W1 44 + W4 3）；接 CI 前先决策：回填或先跑非 strict。
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

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.28）

- **046 R-1**：写失败未硬化（ACL 禁写/`status` 是文件时 index/rollup/snapshot 裸 Traceback exit 1，archive 静默 0）→ 050/051 补 `OSError → exit 2`。
- **046 R-2**：截断/损坏快照被 index 静默跳过；无“快照损坏”告警。
- **046 R-3**：重复 `task_forces` 会重复计数；**R-4**：archive 不清理外部已删快照的陈旧季档；**R-5**：样例快照 `wip 0/1` 对塔低报（已随 047 位置图部分修复）。
- **047 双分母**：同一条 status 里 `campaign (x/y)`（task_forces）与 `position x/8`（roadmap）并存，建议 050 统一或改名。
- **047 `where` vs `campaign-check` 错误码**：坏 campaign 时 `where` 报 E9 而非 E1；`skipped` 枚举不可达；WIP 全塔口径。
- **048 事件扫描只覆盖字面量/模块常量**：变量/f-string 传 type 会逃逸，`unresolved_event_calls` 只计数不失败（051 候选：非零 warning/exit 2）。
- **048 C-12/C-15 无自动化 proof**：probe 是 review/owner 执行点，arch-check 只证引用存在。
- **048 `GATE-SPEC-OBJECTIVE` 计数**：加门会把 `test_arch` 的 `gates=15` 打破，049 已用 completion 改 16；以后加门要同步改测试计数。
- **049 `__FILL__` 整值语义**：`TODO __FILL__`、`__FILL__x`、`补充 <待填写>` 能过；建议加“前缀 marker + 混合占位”规则。
- **049 长度按 code point**：ZWJ 家庭 emoji（7 code points）会被误判过短。
- **049 模板测试用子串、门口用整值**：口径不一致（仅模板测试）。
- **049 spec acceptance 仍写“恰六个 allowed_paths”**：实际 7（completion 授权），文档陈旧。
- **W1×44 / W4×3**：历史卡未挂 campaign、050–052 未建档；`--strict` 必红（050 回填前预期）。
- **记录层残余（043 未做）**：deliver 不反查 completion 备份事件；state-verify 不审计 base_sha；孤悬 completion 被忽略。
- **11 字节重开空账本守卫**：`{"seq": 1}` 仍可绕过（052 候选：只数 type+payload）。
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
