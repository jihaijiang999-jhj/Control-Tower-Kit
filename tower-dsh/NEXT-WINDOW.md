# NEXT WINDOW — tower-dsh（2026-10-26：036 → 041）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`、
> `shared/AUTHORITY_POLICY.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036`（信任边界）、`037`（授权态单写者）、`038`（授权必需标记）、`039`（授权态收尾）、
> `040`（空账本守卫）、`041`（deliver 范围门）是收官后单独六张卡，判例与残余见
> `control-tower/MAP.md` §6.16–§6.21。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.21）。

## 当前状态（2026-10-26 PILOT-041 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-041` 全部 `closed`；41 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 387 tests / OK（skipped=1）`（371 + 041 新增 16；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 41 任务 / 41 信封 / 327 条证据 / drift 0；skipped 3（`PILOT-025/039/041-VOID`） |
| 账本 | primary 380 / supervision 213 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured + requirement=required**（13 checks；`revision=2`、pin `sup-phase2-pilot`） |
| CI | PR #7…#26 全绿；main 最近 run `40312374515` success（5m6s，head `fba013b`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=fba013b` |
| 036 | PR #21 `d8ef20f`；实现 `dab951f`；7/7（塔 `305/293`） |
| 037 | PR #22 `895141c`；实现 `22cbe50`→`89e0afc`；7/7（塔 `328/305`） |
| 038 | PR #23 `7cb9e0b`；实现 `b9f688d`；7/7（塔 `341/328`） |
| 039 | v1 FAIL → VOID → v2 PR #24 `c4efe6d`；实现 `cba7c2e`；7/7（塔 `363/341`） |
| 040 | PR #25 `2bd870f`；实现 `ecb5700`；7/7（塔 `371/363`）；§6.11 夹具播种 |
| 041 | v1 措辞错误 VOID → v2；首轮 FAIL（rename）→ 返工 `fa84fbe`；PR #26 `cc7c55a`；7/7（塔 `387/371`）；bootstrap 交付 |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `control-tower/MAP.md`（§6.9–§6.21：状态重放/计数门/迁移/队列完整性/合并门/信任边界/授权态/必需标记/前置链/空账本/范围门）
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
`merge` 的三道前置：authority pin → 两条链（缺失/不可读/坏行致命）→ 空账本守卫。
`deliver` 的新前置（041）：diff ⊆ allowed_paths（`--no-renames`）、linked-worktree 身份、已跟踪不得脏。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-042` 授权完成清单 + 基线锚定**（推荐，直接吃 041 的两个残余）：
   - `deliver` 接受显式 completion 列表（路径 + author + reason + 授权编号），写入 record/ledger；范围门把 completion 并入 allowed——解决 §6.11 复发（039/040/041 三连）与"门拦自己"；
   - dispatch 记录 `base_sha`，deliver 以该 sha 为 diff 基线（防 `update-ref` 改写本地 main 使 diff 为空）；
   - 防：授权补齐靠人手改 spec、以及本地 ref 改写绕过范围门。
2. **`PILOT-043` 形状预算（shape-check ratchet）**：函数 >80 行/12 分支、新文件 >600 行、重复块 ≥15 行、未使用 import/死代码、diff 覆盖率 <70%——只判新增债务；`REVIEW.md` 加 Structure 五问。现状：`towerctl.py` 5,105 行、11 个 >80 行函数。
3. **P1 记忆/角色（C1+C4+C5）**：`towerctl brief` + `roles/<role>/SKILL.md` + `only_primary_writes_tower_state` 不变量。
4. **∅8 判例集机器化**：21 条判例 → ledger `PRECEDENT` + `precedent --list`。
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
- **权威态只由 `authority-require` / `authority-set` 写**；禁止手改 `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json` 或 ledger。
- **required / 缺失链 / 空账本+工件 / 越界 deliver 都不是可选项**（037–041）。
- **`deliver` 会按新门拒绝越界 diff**：再遇 §6.11 需要的补齐，**不要再走 bootstrap**——先做 042 的 completion-list，或重建卡把路径写进 allowed_paths。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`。
- **spec 冻结**：改 spec 必须重建卡（v1 归档）；039/041 是 FAIL→VOID→v2 的样本。
- **§6.11 最小补齐**：唯一、最小、可核；前提错误写进 commit body 与报告。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 fatal；信封 identity 精确到类型；`ENVELOPE_NEW` 同一条事件绑 `envelope+task+head`。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.21）

- **本地 main ref 可 `update-ref` 改写**：deliver 的 diff 基线仍是本地 main，改写后 diff 为空、可过门（042 候选：dispatch 锚定 base_sha）。
- **§6.11 复发**：039/040/041 三连都撞上"卡面 allowed_paths 与授权补齐不一致"；041 之后新门会直接拒绝这类交付（042 completion-list）。
- **bootstrap**：041 自身交付用 pre-gate 工具为一次性例外；不回填、不追认。
- **identity 兼容**：独立 clone、塔仓本身是 linked worktree 会被拒；identity 是路径前缀不是密码学边界。
- **rename 两侧都必须在 allowed**（`--no-renames` 的保守语义）。
- **11 字节重开空账本守卫**：`{"seq": 1}` 仍可绕过（042/043 候选：只数 type+payload）。
- **legacy 塔 primary 清 0 字节**仍按 036 放行；**TOFU**（policy+event 双写并重算整链）仍靠 git 追踪做外部锚。
- **无密钥链**可重算伪造；`--by` 是字符串不是认证。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
