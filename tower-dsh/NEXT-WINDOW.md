# NEXT WINDOW — tower-dsh（2026-10-24：036 + 037 追加）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、`state/AUTHORITY.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036`（信任边界）与 `PILOT-037`（授权态单写者）是收官后单独两张卡，判例与残余见
> `control-tower/MAP.md` §6.16–§6.17。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.17）。

## 当前状态（2026-10-24 PILOT-037 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-037` 全部 `closed`；37 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 328 tests / OK（skipped=1）`（305 + 037 新增 23；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 37 任务 / 37 信封 / 284 条证据 / drift 0；skipped 仅 `PILOT-025-VOID` |
| 账本 | primary 335 / supervision 193 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| 权威态 | `authority-check` → **configured**（`merge_authority=sup-phase2-pilot`，`revision=1`，12/12 checks） |
| CI | PR #7…#22 全绿；main 最近 run `40087835638` success（4m12s，head `1bb42d9`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净；`HEAD=origin/main=1bb42d9` |
| 036 实值 | PR #21 → merge `d8ef20f`；实现 `dab951f`；信封 `43b9401`；post-merge 7/7（塔 `305/293`） |
| 037 实值 | PR #22 → merge `895141c`；实现 `22cbe50`（v1）→ `89e0afc`（返工）；信封 `0866f48`；post-merge 7/7（塔 `328/305`，anchor `305`） |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `state/AUTHORITY.json`（谁是 merge 权威）
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `control-tower/MAP.md`（§6.9–§6.17：状态重放/计数门/迁移/队列完整性/合并门/信任边界/授权态）
9. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`
10. `RUN-2026-10-22-B.md`、`RUN-2026-10-23-C.md`、`RUN-2026-10-23-D.md`（批授权样本）

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py state-verify
python tools/towerctl.py authority-check      # 必须 exit 0 / status=configured
python -B tools/run_tests.py
```

`wiring` 不通过 = `ORPHANED`，停止并修接线。`state-verify` 出现 drift = 先停，不继续加卡。
`authority-check` 失败 = 本塔**不能 merge**（fail closed），先修权威态，不要绕过。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-038` authority_required 标记**（推荐，直接吃 037 的假 legacy 残余）：
   - 在 `state/AUTHORITY.json` 之外持久化一个"本塔必须 configured"的标记（或把标记写进 `primary/CURRENT_STATE.json`），使"删文件 + 截掉 ledger 尾部 `AUTHORITY_SET`"不能再退回 legacy；
   - `merge` 在该标记存在时对 legacy 状态 fail closed；`state-verify` 把"标记在但 legacy"记为 drift；
   - 给 `authority-set` 的 ledger append 失败补 fail-closed（现在 ledger 为目录会 traceback，state 文件已写但 merge 仍会拦）。
2. **∅8 判例集机器化**：17 条判例（§6.1–§6.17）→ ledger `PRECEDENT` 事件 + `towerctl precedent --list`，让下个窗口查得到而不是读散文。
3. **037 绑定收尾（A3）**：`envelope_head_sha` 缺失/非字符串显式失败（不许 `None==None`）；`supervision_available` 跳过前提写成不变量测试；TOCTOU 决策写成测试。
4. **∅5 对象层画像**：需要 owner 指定一个真实对象/项目，冻结不变量 + `profile-check`（当前备选见下）。
5. **∅6 趋势/熔断、∅9 包号防呆**：均未做，可单卡切入。

## 备选（parked，2026-10-24 owner 决定「作为备选」）

| 代号 | 内容 | 复访条件 |
|---|---|---|
| **B1** | 投放效果对象（SeeMake 业务链的"新半边"：只读回流 → 影子策略 → 小预算 → 自动放量） | 塔具备对象层能力（PROFILE/KB/`profile-check`）后；老板给平台/预算/合规信息 |
| **B2** | 迁移 Kimi 侧 SeeMake-K3 控制塔（`D:\SeeMake-K3`，PR #266 系） | 满足任意两条：自审出过实际事故 / 源塔可完全停写 / 接受 2–4 周只接管 / 执行窗统一到 K3 仓 |
| **B3** | 把 SeeMake 直接当对象 | 一般不建议，B1 跑通后再谈 |

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，且该 id 必须等于 `state/AUTHORITY.json` 的 `merge_authority`（037 起），并 ≠ primary。
- **权威态只由 `authority-set` 写**：禁止手改 `state/AUTHORITY.json` 或 ledger；改 supervisor 身份后必须重跑 `authority-set` 并提交。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`，否则 base 祖先断言会红。
- **spec 冻结**：`task-new` 后改 spec 必须重建卡（v1 归档留痕），不能原地改。
- **预批准 spec 先入库**：批跑时先把整批 spec 提交，否则 post-merge 的 clean 检查会判脏（已犯两次）。
- **卡面与验收冲突**：先修卡，或做最小可证明补齐并在记录里写明前提错误。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 **fatal**；信封 identity 精确到类型（禁止 `str()` 归一化）；`ENVELOPE_NEW` 必须同一条事件绑 `envelope + task + head`。改这三条＝改信任边界，必须走新卡。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）；作者自查不算。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.17）

- **假 legacy（037 新增，最值得记）**：删掉 primary 尾部唯一 `AUTHORITY_SET`（前缀仍是合法链）+ 用悬空 junction 顶替 `state/AUTHORITY.json` → `verify-ledger` 0、`state-verify` 0、`authority-check` legacy，可退回任意 supervisor。需本地写 ledger/state，属 036 的 `tamper-evident` 模型；修法是 038 的 `authority_required` 标记。
- **`authority-set` append 失败仍 traceback**（ledger 为目录时；state 文件已写 → unbacked，merge 仍 fail closed，但不合"单 JSON"风格）。
- **并发 `authority-set` 无跨锁**：file/revision 读+写不串行，16 次双写出现 5 次重复 revision（3 次仍 check 0）；现实风险低（owner 一次性 backfill）。
- **无密钥链可重算伪造**（036/037 共同残余）：能写 ledger 的人可追加/重算"合法"`AUTHORITY_SET`；`--by` 是字符串不是认证；`merge_authority` 未强制等于当前 supervision.id。
- legacy（无 baseline）信封仍可降级绕过链/绑定检查（有意兼容）；`queue-add` 已堵新加路径。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查（git 检查仍拦 merge，属"靠兜底"）。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen 流程。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效（owner 可直推）；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
