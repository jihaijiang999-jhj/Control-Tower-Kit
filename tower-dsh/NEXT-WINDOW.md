# NEXT WINDOW — tower-dsh（2026-10-23 收官 + 036 追加）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`（覆盖 022–035）；
> `PILOT-036` 是收官后单独一张卡，判例与残余见 `control-tower/MAP.md` §6.16。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.16）。

## 当前状态（2026-10-23 PILOT-036 闭环后）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-036` 全部 `closed`；36 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 305 tests / OK（skipped=1）`（基线 293 + 036 新增 12；skip 为平台 symlink） |
| 状态自洽 | `state-verify` → 36 任务 / 36 信封 / 274 条证据 / drift 0；skipped 仅 `PILOT-025-VOID` |
| 账本 | primary 324 / supervision 188 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| CI | PR #7…#21 全绿；main 最近 run `39940214841` success（3m28s，head `2fdd196`） |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净 |
| 036 实值 | PR #21 → merge `d8ef20f`；实现 `dab951f`；信封 `43b9401`；post-merge 7/7（塔 `305/293`，anchor `293`） |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `primary/TASK_BOARD.json`
6. `supervision/MERGE_QUEUE.json`
7. `control-tower/MAP.md`（§6.9–§6.16：状态重放/计数门/迁移/队列完整性/合并门/信任边界）
8. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`
9. `RUN-2026-10-22-B.md`、`RUN-2026-10-23-C.md`、`RUN-2026-10-23-D.md`（批授权样本）

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py state-verify
python -B tools/run_tests.py
```

`wiring` 不通过 = `ORPHANED`，停止并修接线。`state-verify` 出现 drift = 先停，不继续加卡。

## 下一张卡（候选，需 owner 拍板）

1. **`PILOT-037` 绑定收尾**（推荐，最小，直接吃 036 的残余）：
   - `envelope_head_sha` 缺失/非字符串时**显式失败**，不许 `None == None` 让绑定检查变绿（今天靠 git 检查兜底，不该靠兜底）；
   - 把 036 的 `supervision_available` 跳过前提写成不变量测试：**链检查一旦从 fatal 降级，那两个 lifecycle 检查必须重新出现或直接判红**；
   - 把 `ledger_events_in_seq_order` 的 TOCTOU 决策（不吞 OSError）写成测试，锁死"宁可红，不可静默当空"。
2. **∅7 授权态单写者**：`state/AUTHORITY.json` + `authority-check`，把 `--role supervisor` 从字符串变成可判定身份。
3. **∅5 对象层画像**：需要 owner 指定一个真实对象/项目，冻结不变量 + `profile-check`。
4. **∅6 趋势/熔断、∅8 判例集、∅9 包号防呆**：均未做，可单卡切入。

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>` 且 supervisor ≠ primary。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`，否则 base 祖先断言会红。
- **spec 冻结**：`task-new` 后改 spec 必须重建卡（v1 归档留痕），不能原地改。
- **预批准 spec 先入库**：批跑时先把整批 spec 提交，否则 post-merge 的 clean 检查会判脏（已犯两次）。
- **卡面与验收冲突**：先修卡，或做最小可证明补齐并在记录里写明前提错误。
- **信任边界（036 起）**：缺失/不可读 ledger 在合并门是 **fatal**（exit 2，不是 ok）；信封 identity 精确到类型（禁止 `str()` 归一化）；`ENVELOPE_NEW` 必须同一条事件绑 `envelope + task + head`。改这三条＝改信任边界，必须走新卡。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）；作者自查不算。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14–§6.16）

- **无密钥链可被“追加一行正确 prev_hash/hash 的 `ENVELOPE_NEW`”伪造**（036 把成本从“手写信封”抬到“手写信封+写一行账”，不是加密强度）；宪法只靠“executor 不写 ledger”这条信任。
- `envelope_head_sha` 两边同时缺失时 `None == None` 可过绑定检查；git 检查（branch head / `b^`）仍拦 merge，属“靠兜底”，037 应改成显式失败。
- legacy（无 baseline）信封仍可降级绕过链/绑定检查（有意兼容）；`queue-add` 已堵新加路径。
- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen 流程。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效（owner 可直推，036 的 state push 又触发过一次 bypass 提示）；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
