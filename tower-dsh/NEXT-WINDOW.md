# NEXT WINDOW — tower-dsh（2026-10-25：036 + 037 + 038 + 039）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）
> 是收官后单独四张卡，判例与残余见 `control-tower/MAP.md` §6.16–§6.19。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.19）。

## 当前状态（2026-10-25 PILOT-039 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-039` 全部 `closed`；39 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 363 tests / OK（skipped=1）`（341 + 039 新增 22；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 39 任务 / 39 信封 / 305 条证据 / drift 0；skipped 2（`PILOT-025-VOID`、`PILOT-039-VOID`） |
| 账本 | primary 359 / supervision 203 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| CI | PR #7…#24 全绿；main 最近 run `40166220688` success（4m52s，head `f175d1d`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=f175d1d` |
| 036 实值 | PR #21 → merge `d8ef20f`；实现 `dab951f`；post-merge 7/7（塔 `305/293`） |
| 037 实值 | PR #22 → merge `895141c`；实现 `22cbe50` → `89e0afc`；post-merge 7/7（塔 `328/305`） |
| 038 实值 | PR #23 → merge `7cb9e0b`；实现 `b9f688d`；post-merge 7/7（塔 `341/328`） |
| 039 实值 | **v1 复核 FAIL → VOID**（`tasks/PILOT-039-VOID` + `pilot/PILOT-039.spec.v1.json`）→ v2：PR #24 → merge `c4efe6d`；实现 `cba7c2e`；信封 `9a78d79`；post-merge 7/7（塔 `363/341`） |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`（本塔必须配置权威态 / 谁是 merge 权威）
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `control-tower/MAP.md`（§6.9–§6.19：状态重放/计数门/迁移/队列完整性/合并门/信任边界/授权态/必需标记/前置链）
9. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`
10. `RUN-2026-10-22-B.md`、`RUN-2026-10-23-C.md`、`RUN-2026-10-23-D.md`（批授权样本）

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py state-verify
python tools/towerctl.py authority-check      # 必须 exit 0 / configured / requirement=required
python -B tools/run_tests.py
```

`wiring` 不通过 = `ORPHANED`。`state-verify` drift = 先停。`authority-check` 失败 = 不能 merge（fail closed）。
`merge` 现在还会对 primary+supervision 做**前置链校验**：缺失/不可读/坏行一律 exit 2，队列与 ledger 都不会被改。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-040` 空账本语义**（推荐，直接吃 039 的残余）：
   - 把 ledger **截断为 0 字节**（不是删除）目前仍是合法空链；required/configured 塔 + legacy 信封仍可 merge。040 要区分「从未有事件的空塔」与「有任务/队列/信封工件的塔被清空账本」：后者在 merge 前置链里按失败处理；
   - 顺手：`authority-require` 的 `already=true` 分支回显请求的 `--decision` 而实际不改变（文案误导）；
   - 可选：给 `verify_ledger_file` 增加“与宿主持久工件对账”的最小规则（有 `tasks/` 或 `supervision/envelopes/` 却 0 事件 → warning/error），需先想清楚旧塔兼容。
2. **∅8 判例集机器化**：19 条判例（§6.1–§6.19）→ ledger `PRECEDENT` 事件 + `towerctl precedent --list`。
3. **036/037 绑定收尾（A3）**：`envelope_head_sha` 缺失/非字符串显式失败（不许 `None==None`）；`supervision_available` 跳过前提写成不变量测试；TOCTOU 决策写成测试。
4. **∅5 对象层画像**：需要 owner 指定真实对象，冻结不变量 + `profile-check`（当前备选见下）。
5. **∅6 趋势/熔断、∅9 包号防呆**：均未做，可单卡切入。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"：只读回流 → 影子策略 → 小预算 → 自动放量） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；owner 给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`，PR #266 系） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`，且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**：禁止手改 `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json` 或 ledger；改 supervisor 身份后必须重跑 `authority-set` 并提交。
- **required 不是可选项**；**缺失/不可读/坏链不是可选项**：039 起 merge 前置链对 primary+supervision 无条件校验，缺失=错。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`，否则 base 祖先断言会红。
- **spec 冻结**：`task-new` 后改 spec 必须重建卡（v1 归档留痕），不能原地改；039 是第一个「复核 FAIL → VOID → v2」的完整样本。
- **预批准 spec 先入库**：批跑时先把整批 spec 提交，否则 post-merge 的 clean 检查会判脏（已犯两次）。
- **卡面与验收冲突**：先修卡，或按 §6.11 做唯一、最小、可核的补齐并在 commit body/报告里写明前提错误。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 **fatal**；信封 identity 精确到类型；`ENVELOPE_NEW` 同一条事件绑 `envelope + task + head`。改这三条＝改信任边界，必须走新卡。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）；作者自查不算。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.19）

- **0 字节截断**：把 ledger 截成空文件（不是删除）仍是合法空链；required/configured 塔 + legacy 信封仍可 merge（040 候选）。036 的「空文件=合法空链」与 039 的「缺失=错」在这里留了一条缝。
- **`authority-require` 的 `already=true` 回显**：输出会回显请求的 `--decision`，实际以事件为准；文案误导（040 候选）。
- **TOFU 残余**：policy+event 双写并重算整链可自洽；policy 的 git 追踪是唯一外部锚（超出 039）。
- **无密钥链可重算伪造**（036 起共同残余）；`--by` 是字符串不是认证。
- legacy（无 baseline）信封仍可降级绕过链/绑定检查（但 039 起 merge 前置链对缺失/坏链已 fatal）。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge，属"靠兜底"）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen 流程。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效（owner 可直推）；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
