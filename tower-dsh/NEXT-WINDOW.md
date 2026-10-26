# NEXT WINDOW — tower-dsh（2026-10-26：036 → 040）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）、
> `040`（空账本守卫）是收官后单独五张卡，判例与残余见 `control-tower/MAP.md` §6.16–§6.20。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.20）。

## 当前状态（2026-10-26 PILOT-040 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-040` 全部 `closed`；40 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 371 tests / OK（skipped=1）`（363 + 040 新增 8；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 40 任务 / 40 信封 / 317 条证据 / drift 0；skipped 2（`PILOT-025-VOID`、`PILOT-039-VOID`） |
| 账本 | primary 367 / supervision 208 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| CI | PR #7…#25 全绿；main 最近 run `40268903598` success（5m14s，head `ab084d3`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=ab084d3` |
| 036 | PR #21 `d8ef20f`；实现 `dab951f`；7/7（塔 `305/293`） |
| 037 | PR #22 `895141c`；实现 `22cbe50`→`89e0afc`；7/7（塔 `328/305`） |
| 038 | PR #23 `7cb9e0b`；实现 `b9f688d`；7/7（塔 `341/328`） |
| 039 | **v1 FAIL → VOID** → v2 PR #24 `c4efe6d`；实现 `cba7c2e`；7/7（塔 `363/341`） |
| 040 | PR #25 `2bd870f`；实现 `ecb5700`；信封 `ec9c22c`；7/7（塔 `371/363`）；§6.11 夹具播种 |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `control-tower/MAP.md`（§6.9–§6.20：状态重放/计数门/迁移/队列完整性/合并门/信任边界/授权态/必需标记/前置链/空账本）
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

`wiring` 不通过 = `ORPHANED`。`state-verify` drift = 先停。`authority-check` 失败 = 不能 merge。
`merge` 现在有三道前置：authority pin → primary/supervision 链（缺失/不可读/坏行致命）→ 空账本守卫（configured/required 塔的 supervision 0 事件 + 有工件 → 拒绝）。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-041` 执行契约：`allowed_paths` 交付校验**（推荐，最便宜的"执行窗口管理"）：
   - `deliver` 时校验 worktree 的 `git diff --name-only base..HEAD ⊆ allowed_paths`（越界拒绝）；
   - 顺带：dispatch 记录 `kind/model/parent/started_at`（只记录，不做注册表）；
   - 防：executor 越界写仍能交付（MAP P1-1 至今未做）。
2. **`PILOT-042` 事件计数口径收紧**（040 的直接残余）：
   - `ledger_empty_guard` 只数"含非空 `type` + dict `payload`"的行（或 per-envelope `QUEUE_ADD`/`ENVELOPE_NEW` 背书）；
   - 修 merge-ledger-only 工件的文案/审计不一致；
   - 防：`{"seq": 1}`（11B）重开 0 字节守卫。
3. **P1 记忆/角色（C1+C4+C5）**：`towerctl brief`（一页记忆）+ `roles/<role>/SKILL.md`（渐进披露）+ `only_primary_writes_tower_state` 不变量。
4. **∅8 判例集机器化**：20 条判例 → ledger `PRECEDENT` + `towerctl precedent --list`。
5. **036/037 绑定收尾（A3）**：`envelope_head_sha` 缺失显式失败；`supervision_available` 前提测试；TOCTOU 测试。
6. **∅5 对象层画像**：需要 owner 指定真实对象（备选见下）；∅6/∅9 可单卡切入。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；owner 给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`，且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**；禁止手改 `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json` 或 ledger；改 supervisor 后必须重跑 `authority-set` 并提交。
- **required 不是可选项；缺失/不可读/坏链不是可选项；空账本+工件也不是可选项**（039/040）。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`。
- **spec 冻结**：改 spec 必须重建卡（v1 归档）；039 是「FAIL → VOID → v2」的完整样本，040 是「卡面矛盾 → §6.11 最小播种」的样本。
- **§6.11 最小补齐**：唯一、最小、可核；前提错误写进 commit body 与报告，复核据此判。
- **预批准 spec 先入库**；卡面与验收冲突先修卡或写明前提错误。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 fatal；信封 identity 精确到类型；`ENVELOPE_NEW` 同一条事件绑 `envelope+task+head`。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求命中回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.20）

- **11 字节重开守卫**：`ledger_empty_guard` 按“可解析 JSON 对象”计事件，`{"seq": 1}` 可绕过（041 候选）。
- **merge-ledger-only 工件**：守卫失败但 state-verify ok，文案与审计不一致（042 候选）。
- **§6.11 卡面 stale**：040 的 allowed_paths（3）与实改（5 文件）不一致，已在 commit body 记录，closeout 可见。
- **legacy 塔 primary 清 0 字节**仍按 036 放行（空文件=合法空链；卡面明确保持）。
- **TOFU**：policy+event 双写并重算整链可自洽；policy 的 git 追踪是唯一外部锚。
- **无密钥链**可重算伪造；`--by` 是字符串不是认证。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
