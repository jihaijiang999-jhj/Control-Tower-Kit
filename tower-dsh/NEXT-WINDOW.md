# NEXT WINDOW — tower-dsh（2026-10-23 收官版）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在 `primary/CURRENT_STATE.json`、
> `primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`。
> 最近一次完整窗口摘要：`control-tower/SESSION-CLOSEOUT-2026-10-23.md`。
> 地图与判例：`control-tower/MAP.md`（§6.9–§6.15）。

## 当前状态（2026-10-23 收官时）

| 项 | 值 |
|---|---|
| 代号 | **应县木塔 / Yingxian**（`YX-001`） |
| 任务 | `PILOT-001` … `PILOT-035` 全部 `closed`；35 个信封全部 `POST_MERGE_VERIFIED` |
| 测试 | `Ran 293 tests / OK（skipped=1）` |
| 状态自洽 | `state-verify` → 35 任务 / 35 信封 / 264 条证据 / drift 0；skipped 仅 `PILOT-025-VOID` |
| 账本 | primary 316 / supervision 183 事件，0 error（legacy 未哈希 53/26，按 INV-05 只计不判） |
| CI | PR #7…#20 全绿；main 最近 run `39929889654` success |
| 阶段 | `HANDOFF_ACTIVE`；`authority_dirty_count=0`；工作树干净 |

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `primary/TASK_BOARD.json`
6. `supervision/MERGE_QUEUE.json`
7. `control-tower/MAP.md`（§6.9–§6.15：状态重放/计数门/迁移/队列完整性/合并门）
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

1. **`PILOT-036` 信任边界收口**（推荐，最小）：
   - 缺失/不可读 ledger 不再算 `ledger chain intact`（缺失=错，不可读=干净 exit 2）；
   - 命令级 identity 改精确比较（不再 `str()`）；
   - `ENVELOPE_NEW` 绑定 head/task（不只 id）。
2. **∅5 对象层画像**：需要 owner 指定一个真实对象/项目，冻结不变量 + `profile-check`。
3. **∅7 授权态单写者**：`state/AUTHORITY.json` + `authority-check`，把 `--role supervisor` 从字符串变成可判定身份。
4. **∅6 趋势/熔断、∅8 判例集、∅9 包号防呆**：均未做，可单卡切入。

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>` 且 supervisor ≠ primary。
- **状态提交只在 envelope 之后**；不早于 `envelope-new`，否则 base 祖先断言会红。
- **spec 冻结**：`task-new` 后改 spec 必须重建卡（v1 归档留痕），不能原地改。
- **预批准 spec 先入库**：批跑时先把整批 spec 提交，否则 post-merge 的 clean 检查会判脏（已犯两次）。
- **卡面与验收冲突**：先修卡，或做最小可证明补齐并在记录里写明前提错误。
- 四闸（merge / 外部调用 / 部署·生产数据 / L0 文档写 main）永远归 owner。
- 每张卡必须有独立 reviewer（`reviewer != executor`，read-only，亲跑证据）；作者自查不算。

## 批授权跑法（推荐）

1. 写 `RUN-<date>-X.md` 章程（卡序、预算、硬停、检查点） + 整批 spec，一次提交；
2. owner 批准后建 goal（`max_goal_rounds` 覆盖卡数），逐卡执行；
3. 每卡 post-merge 给四段摘要（不要求回复）；命中硬停立即停；
4. 完成后更新 `MAP.md` 判例与 `SESSION-CLOSEOUT`，push、看 CI。

## 已知残余（详见 MAP ∅10–∅12 与 §6.14/§6.15）

- `ready→TASK_NEW` 仍合法；未来生命周期事件漏表会默认放行；关闭卡无正式 reopen 流程。
- legacy（无 baseline）信封可降级绕过新式合并检查；链可重算伪造（tamper-evident）。
- 缺失 ledger 算 `ok`、不可读 ledger 会 traceback；`ENVELOPE_NEW` 只绑 id。
- 035 修复不造 `ENVELOPE_NEW`；非 WAITING 半写 stdout 报 WAITING；反向半写未处理。
- `.test-tmp` 不自动清理；runner 依赖 Windows `core.longpaths`；直接 discovery 不走沙箱。
- 分支保护对 admin 无效（owner 可直推）；真实项目 pilot 未接。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令+阈值）**。
缺任何一段等于没有交接。
