# NEXT WINDOW — tower-dsh（2026-10-25：036 + 037 + 038）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036`（信任边界）、`PILOT-037`（授权态单写者）、`PILOT-038`（授权必需标记）是收官后
> 单独三张卡，判例与残余见 `control-tower/MAP.md` §6.16–§6.18。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.18）。

## 当前状态（2026-10-25 PILOT-038 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-038` 全部 `closed`；38 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 341 tests / OK（skipped=1）`（328 + 038 新增 13；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 38 任务 / 38 信封 / 293 条证据 / drift 0；skipped 仅 `PILOT-025-VOID` |
| 账本 | primary 345 / supervision 198 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`merge_authority=sup-phase2-pilot`，`revision=2`） |
| CI | PR #7…#23 全绿；main 最近 run `40096634339` success（4m21s，head `40f4dc2`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=40f4dc2` |
| 036 实值 | PR #21 → merge `d8ef20f`；实现 `dab951f`；信封 `43b9401`；post-merge 7/7（塔 `305/293`） |
| 037 实值 | PR #22 → merge `895141c`；实现 `22cbe50` → `89e0afc`（返工）；post-merge 7/7（塔 `328/305`） |
| 038 实值 | PR #23 → merge `7cb9e0b`；实现 `b9f688d`；信封 `34c1ec3`；post-merge 7/7（塔 `341/328`，anchor `328`） |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`（本塔必须配置权威态 / 谁是 merge 权威）
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `control-tower/MAP.md`（§6.9–§6.18：状态重放/计数门/迁移/队列完整性/合并门/信任边界/授权态/必需标记）
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

`wiring` 不通过 = `ORPHANED`，停止并修接线。`state-verify` 出现 drift = 先停，不继续加卡。
`authority-check` 失败 = 本塔**不能 merge**（fail closed）；先修权威态，不要绕过。required 塔删文件/截尾不再是 legacy，而是 `required_unconfigured`。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-039` 授权态收尾**（推荐，直接吃 038 的残余）：
   - `AUTHORITY_POLICY` 与 `AUTHORITY_REQUIRED` payload **逐字段同构**（现在只验 presence/极性，改 `decision/set_at/set_by` 不报）；
   - `authority-require` / `authority-set` 的 file/event 写入加**跨锁**（现在并发可能重复 revision）；
   - `merge` 在 configured/required 时把 **`verify-ledger` 纳入前置**（现在空账本前缀不被 merge 抓）；
   - 可选：把 `authority-required` 的 required 标记也写进 `primary/CURRENT_STATE.json`（三处冗余，让"删干净"更难）。
2. **∅8 判例集机器化**：18 条判例（§6.1–§6.18）→ ledger `PRECEDENT` 事件 + `towerctl precedent --list`。
3. **037/036 绑定收尾（A3）**：`envelope_head_sha` 缺失/非字符串显式失败（不许 `None==None`）；`supervision_available` 跳过前提写成不变量测试；TOCTOU 决策写成测试。
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
- **required 不是可选项**：真实塔已 armed；不要用"删文件 + 截账本"制造 legacy（新码会报 `required_unconfigured`）。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`，否则 base 祖先断言会红。
- **spec 冻结**：`task-new` 后改 spec 必须重建卡（v1 归档留痕），不能原地改。
- **预批准 spec 先入库**：批跑时先把整批 spec 提交，否则 post-merge 的 clean 检查会判脏（已犯两次）。
- **卡面与验收冲突**：先修卡，或做最小可证明补齐并在记录里写明前提错误。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 **fatal**；信封 identity 精确到类型；`ENVELOPE_NEW` 同一条事件绑 `envelope + task + head`。改这三条＝改信任边界，必须走新卡。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）；作者自查不算。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.18）

- **假 legacy 的门槛已抬到 4 个工件**：删 `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`，并截掉 primary 里**最早**一条 `AUTHORITY_SET`/`AUTHORITY_REQUIRED` 及其后所有行（合法前缀仍过 `verify-ledger`）→ 才能回到 legacy。不是不可删，只是"一次删除"不够用了。
- **policy/event 只验 presence 与极性**：改 `decision/set_at/set_by` 不会报 drift（039 候选）。
- **`authority-set`/`authority-require` 无跨锁**：并发可能重复 revision（039 候选）。
- **`merge` 不跑 `verify-ledger`**：空账本/合法前缀不被 merge 自身抓住（039 候选）。
- **无密钥链可重算伪造**（036/037/038 共同残余）；`--by` 是字符串不是认证。
- legacy（无 baseline）信封仍可降级绕过链/绑定检查（有意兼容）；`queue-add` 已堵新加路径。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge，属"靠兜底"）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen 流程。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效（owner 可直推）；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
