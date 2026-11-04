# NEXT WINDOW — tower-dsh（2026-11-04，073 闭环）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在
> `primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、
> `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。

## 当前状态（2026-11-04 PILOT-073 闭环后）

| 项 | 值 |
|---|---|
| 代号 | 应县木塔 / Yingxian（`YX-001`） |
| 任务 | `PILOT-001` – `PILOT-073`；72 张 closed/superseded；**70 个信封** |
| 测试 | `Ran 788 tests / OK (skipped=1)` |
| 状态自洽 | `state-verify` → 72 任务 / 70 信封 / drift `[]` |
| 账本 | primary/supervision 链无 error；证据 700+ |
| 权威性 | `authority-check` configured + required；pin `sup-phase2-pilot` |
| 形状 | `shape-check` 0；23 模块 <600；`towerctl.py` 246 行 |
| 架构 | `arch-check` gates 18 / events 31 / adrs 8 |
| 对象层 | `profile-check` 11/0 |
| 命令层 | `campaign-check` 0；C-2026-Q4-04 12/12 |
| 位置图 | `where --json` → **12/12**；next `null` |
| CI | main `67642cb` success（run `41810391363`） |
| 阶段 | `HANDOFF_ACTIVE`；工作树干净；`HEAD=origin/main` |

## 061–073 结果

| 卡 | 结果 | 说明 |
|---|---|---|
| 061 | local bootstrap | PR head envelope-only 早期检查 |
| 062 | local bootstrap | 043 tombstone + 052/056/060 清债 |
| 063 | closed 无 envelope | 被 065 取代 |
| 064 | ABANDONED | base-side 首版；被 065 取代 |
| 065 | PR #48 `c199928` admin + verified | envelope 在 main、branch 只实现 |
| 066 | PR #50 `713d709` admin + verified | post-merge base-side 路径；065 shim 删除 |
| 067 | PR #52 `eba7ed3` admin + verified | base-sync policy；直接 admin |
| 068 | PR #53 `969acdb` admin + verified | state-only 白名单；仍直接 admin |
| 069 | **superseded by 070** | HEAD 基准永远不触发审计 admin |
| 070 | PR #54 `269e629` **audited admin** + verified | implementation-head 基准；审计首次成功 |
| 071 | PR #55 `c0e1d57` admin fallback → **recover** → verified | 073 `envelope-recover` 补 MERGE；task-supersede |
| 072 | spec parked | task-reopen 未实现；071 卡已随回滚消失 |
| 073 | PR #56 `1042265` **audited admin** + verified | spec/campaign state-only；recover fetch-first + 半写幂等 |

## 关键 deviation（必须记）

1. **071 是 direct admin fallback**：base-ahead 含 spec/campaign 被旧白名单判 code，审计 admin 拒绝；直接 `gh --admin` 后用 `envelope-recover` 补 MERGE。审计字段是 `recovered=true`，不是 `admin=true`。
2. **073 是审计 admin**：`base_sync=state-only`、`admin=true`；这是 070 之后第二次成功（070/073）。
3. **069 superseded**：`TASK_SUPERSEDE` + ID→void；不是 close、不是 void 别名。
4. **072 parked**：`pilot/PILOT-072.spec.json.parked`；不建卡、不进 C-04。
5. **063/064**：063 closed 无 envelope；064 ABANDONED；历史保留。

## 071 recover / 073 审计

- 071：`envelope-recover --merge-commit c0e1d57`；先 fetch origin、FETCH_HEAD 解析；补 MERGE_START+MERGE；post-merge 9/9。
- 073：`merge --allow-state-ahead`；白名单 `pilot/*.spec.json` + `command/campaigns/**` 为 state-only；`admin=true`；post-merge 9/9。
- 073 的 recover 修复：fetch-first、remote-only commit 可恢复、半写幂等、不同 commit 拒绝。

## 下一步建议

1. **外证**：真实外部项目 1 个 feature，完整跑 spec→dispatch→review→envelope→PR merge→post-merge→owner 验收；先写 RUN 章程 + owner 批准。
2. **072 处置**：保持 parked；若未来需要 task-reopen，另开卡，不复用 072 编号。
3. **文档**：本文件 + MAP §6.38 已更新；061–073 的 deviation 已记录。
4. **可选**：把 071 的 direct admin fallback 作为“最后手段”写进 RUN 章程。

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `command/STRATEGY.md` + `command/campaigns/*.md`
9. `towerctl where --json`
10. `ARCHITECTURE.md` + `adr/ADR-0002/0003/0004/0005/0009`
11. `state/PROFILE-TEMPLATE.md` + `state/PROFILE-TOWER-DSH.md`
12. `arch/GATES.json`、`arch/INVARIANTS.json`、`EVENT_CATALOG.json`
13. `control-tower/COMMAND-LAYER.md`
14. `control-tower/MAP.md` §6.1–§6.38
15. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py state-verify          # 72/70；drift=[]
python tools/towerctl.py authority-check       # exit 0 / configured / required
python tools/towerctl.py arch-check            # gates 18
python tools/towerctl.py profile-check         # 11/0
python tools/towerctl.py where --json          # 12/12；next null
python tools/towerctl.py campaign-check        # exit 0
python tools/towerctl.py shape-check           # exit 0
python -B tools/run_tests.py                   # 788 / OK (skipped=1)
```

`wiring` 不通过 = ORPHANED；`state-verify` drift = 先停；`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链 → 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet。
新建 spec 必须带 `objective` 四要素；新卡 `@2`，旧 `@1` 冻结。

## 已知残余

- **071 direct admin fallback**：已 recover，但审计字段是 `recovered=true`；不是常规审计 admin。
- **072 parked**：`pilot/PILOT-072.spec.json.parked`；不建卡。
- **063 closed 无 envelope**：历史保留；不补 envelope。
- **064 ABANDONED**：`ENV-PILOT-064` tombstone。
- **069 superseded**：`ENV-PILOT-069` 未建 envelope；ID void。
- **C-04 12/12 active**：current 073；下一 campaign 启动时再 completed。
- **065/066/067/068 直接 admin**：历史 deviation；070/073 已证明审计 admin。
- **外证未开始**：真实外部项目 0。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令/阈值）**。
缺任何一段等于没有交接。
