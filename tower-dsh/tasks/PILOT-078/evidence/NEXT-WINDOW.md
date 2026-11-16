# NEXT WINDOW — tower-dsh（2026-11-16，077 收盘 / 078 文档卡）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在
> `primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、
> `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。
> 口径冻结：2026-11-16（077 `POST_MERGE_VERIFIED` 之后）；数字全部可由"自检"里的命令复算。

## 当前状态（077 收盘；078 文档卡在途）

| 项 | 值 |
|---|---|
| 代号 | 应县木塔 / Yingxian（`YX-001`） |
| 代码卡 | **76 代码卡**（`PILOT-001`–`PILOT-077`；`072` void，`069` superseded） |
| 文档卡 | `PILOT-078`：C-04 的**第 17 个 campaign 节点**，**不计入 76 代码卡** |
| 信封 | **74 个信封**（`ENV-PILOT-002`–`ENV-PILOT-077`；`063` 无信封、`064` ABANDONED、`069` 不建信封、`072` 不建） |
| 测试 | `Ran 844 tests / OK (skipped=1)`（077 post-merge，2026-11-15；本地 2026-11-16 复跑） |
| 状态自洽 | `state-verify` → **76 任务 / 74 信封 / drift `[]`**；078 dispatch 后真实塔为 **77 任务 / 74 信封**（078 尚无信封） |
| 交付卡 | **16 张交付卡 / 16-16**：C-04 的 061–077（072 void 不计），全部 `POST_MERGE_VERIFIED` |
| campaign | C-2026-Q4-04 共 **17 个节点**（16 交付卡 + 078 文档卡）；078 收盘前 `where` = `16/17 · 下一站 078`，078 收盘后 = `17/17` |
| 账本 | primary 743 事件 / supervision 436 事件（077 收盘；078 dispatch 后 primary 747）；`verify-ledger` 0 error（legacy 未哈希 53/26，只计不判） |
| 证据 | `state-verify` 校验 734 条证据 |
| 权威性 | `authority-check` configured + required；pin `sup-phase2-pilot`；owner / primary 的 GitHub login 必须不同 |
| 形状 | `shape-check` 0（82 文件 / 2,424 函数） |
| 架构 | `arch-check` gates **18** / invariants 16 / events **32** / adrs 8 / nodes 82 / edges 185 |
| 对象层 | `profile-check` 11/0 |
| CI | 8 步（unit / spec-lint --strict / spec-coverage / verify-ledger / arch-check / campaign-check / shape-check / status），`fetch-depth: 0`；**未跑 online CI，不宣称在线已验证** |

> **16-16 不是"16 次 verified merge"**：它表示 16 张交付卡全部 `POST_MERGE_VERIFIED`。
> 其中 065–068 的 merge 事实由 074 的 `MERGE_HISTORICAL` 回填，071/074/075/076/077 走的是
> admin + `envelope-recover`；只有 070/073/076 是审计 admin（`admin=true` / `base_sync=state-only`）。
> 把 16-16 读成 16 次常规 tower `merge` 是错的。

## 061–077 结果

| 卡 | 结果 | 说明 |
|---|---|---|
| 061 | local bootstrap | PR head envelope-only 早期检查；未走成 PR merge |
| 062 | local bootstrap | 043 tombstone + 052/056/060 清债；未走成 PR merge |
| 063 | closed 无 envelope | 被 065 取代；历史保留、不补 envelope |
| 064 | ABANDONED | base-side 首版失败；`ENV-PILOT-064` tombstone；被 065 取代 |
| 065 | PR #48 `c199928` direct admin + 回填 | base-side envelope；074 用 `MERGE_HISTORICAL` 补 merge 事实 |
| 066 | PR #50 `713d709` direct admin + 回填 | post-merge 认 tower 前缀；删 repo-root shim |
| 067 | PR #52 `eba7ed3` direct admin + 回填 | base-sync policy；仍直接 admin |
| 068 | PR #53 `969acdb` direct admin + 回填 | state-only 白名单；仍直接 admin |
| 069 | **superseded by 070** | `TASK_SUPERSEDE` + ID→void；不建 envelope、不写 MERGE |
| 070 | PR #54 `269e629` **audited admin** + verified | implementation-head 基准；审计首次成功 |
| 071 | PR #55 `c0e1d57` direct admin → **recover** | 审计 admin 拒绝 spec/campaign 后直接 `gh --admin`；073 `envelope-recover` 补 MERGE |
| 072 | **void / parked** | task-reopen 未实现；`pilot/PILOT-072.spec.json.parked`；`TASK_IDS` status=`void`，**不复用** |
| 073 | PR #56 `1042265` **audited admin** + verified | spec/campaign state-only；recover fetch-first + 半写幂等 |
| 074 | PR #57 `373d42c` direct admin → recover + verified | CI shallow-history 失败；补 `MERGE_HISTORICAL` 回填 065–068、新增 `verified_without_merge` drift |
| 075 | PR #59 `eb25ff5` admin → **recover re-fold** + verified | CORRECTION 先 `MERGE_START(recovered)` 再 `MERGE(recovered)`；CI checkout `fetch-depth: 0` |
| 076 | PR #60 `0d9cab0` **audited admin** + tail recover + verified | `admin=true` / `base_sync=state-only`；owner APPROVED review 门（approver ≠ primary / PR author）；076 自身 legacy bootstrap |
| 077 | PR #61 `2bfab80` admin → recovered + verified | 严格 owner gate bootstrap；post-merge snapshot/restore；**16-16 / 844** 收盘 |

## 关键 deviation（必须记，不掩盖）

1. **065–068 回填**：四张卡都直接 `gh --admin` 合并，没有 tower `MERGE` 事件、`envelope.merge_commit` 为空。
   074 用 `MERGE_HISTORICAL` 补事实：`c199928` / `713d709` / `eba7ed3` / `969acdb`，
   `recovered=true`、`historical=true`、**不写 `admin=true`**；只补 merge 事实，不改状态、不伪造审计 admin。
2. **069 superseded**：`TASK_SUPERSEDE` + ID→void；不是 close、不是 void 别名，不建 envelope。
3. **071 direct admin fallback**：base-ahead 含 spec/campaign 被旧白名单判 code，审计 admin 拒绝；
   直接 `gh --admin` 后用 `envelope-recover` 补 MERGE，审计字段是 `recovered=true`，不是 `admin=true`。
4. **074 也是 direct admin + recover**（不是审计 admin）：CI 在 shallow 历史上报
   `verified_without_merge`，直接 admin 合并后 `envelope-recover`，再 post-merge 9/9。
5. **075 recover re-fold**：从 CORRECTION 恢复时先写 `MERGE_START(recovered=true)`，再写
   `MERGE(recovered=true)`；普通 CORRECTION→MERGE 仍 illegal。CI 改 `fetch-depth: 0`。
6. **076 审计 admin 之后再尾部 recover**：`merge --allow-state-ahead` 写 `admin=true` / `base_sync=state-only`；
   合并后 envelope 尾部停在中间态，`envelope-recover` 追加 recovered `MERGE_START`/`MERGE` 才到 MERGED；
   post-merge 独立跑 9/9 才 verified。owner GitHub 批准门从 077 起强制（076 是 legacy bootstrap）。
7. **077 admin + recovered**：PR #61 `2bfab80`；严格 owner gate 的 bootstrap，同样靠 recover 收口；
   post-merge 先 snapshot 再跑测试、失败先 restore 再写 CORRECTION。
8. **063/064/072**：063 closed 无 envelope；064 ABANDONED；072 parked → 现登记为 `void`。
9. **口径**：76 代码卡 + 078 文档卡 = 77 个 campaign 节点中的 16 交付卡；`16-16` 不是 16 次 verified merge。

## 078（当前卡）

- 类型：**文档卡**，C-04 第 17 个节点；**不计入 76 代码卡，也不计入 16-16**。
- scope：NEXT-WINDOW / MAP / README / REPRODUCE / ARCHITECTURE 统一到 76/74/844/16-16；
  `state/TASK_IDS.json` 登记 072 `void`；新增 `docs/WALKTHROUGH.md`；新增文档数字测试。
- 边界：不改运行时代码、不 merge、不联网；`allowed_paths` 之外零改动。
- 收盘判据：PR 审计 admin（`admin=true` + `base_sync=state-only`，或如实记录 deviation）、
  post-merge 9/9、`where` = `17/17`。在此之前不得写 verified。

## 下一步建议

1. **078 收口**：deliver → 独立 checkback → envelope → queue → PR merge → post-merge；
   收盘后 `where` 从 `16/17` 变 `17/17`，但代码卡仍是 76（078 是文档卡）。
2. **外证**：真实外部项目 1 个 feature，完整跑 spec→dispatch→review→envelope→PR merge→post-merge→owner 验收；
   先写 RUN 章程 + owner 批准。
3. **072 处置**：保持 void/parked；若未来需要 task-reopen，另开新编号，不复用 072。
4. **文档**：本文件 + MAP §6.39 + `docs/WALKTHROUGH.md` 是 077 收盘口径；改数字必须同步改测试。

## 新窗口读序

1. `TOWER.md`
2. `START-HERE.md`
3. `shared/PROJECT_PROFILE.json`、`shared/AUTHORITY_MODEL.json`
4. `primary/CURRENT_STATE.json`
5. `shared/AUTHORITY_POLICY.json` + `state/AUTHORITY.json`
6. `primary/TASK_BOARD.json`
7. `supervision/MERGE_QUEUE.json`
8. `command/STRATEGY.md` + `command/campaigns/*.md`
9. `python tools/towerctl.py where --json`（C-04 = 17 节点）
10. `docs/WALKTHROUGH.md`（从 task-new 到 post-merge 的可执行路径）
11. `ARCHITECTURE.md` + `adr/ADR-0002/0003/0004/0005/0009`
12. `state/PROFILE-TEMPLATE.md` + `state/PROFILE-TOWER-DSH.md`
13. `arch/GATES.json`、`arch/INVARIANTS.json`、`EVENT_CATALOG.json`
14. `control-tower/COMMAND-LAYER.md`（仓库根，tower 前缀之外）
15. `control-tower/MAP.md` §6.1–§6.39（仓库根）
16. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py state-verify          # 76 / 74；drift=[]
python tools/towerctl.py verify-ledger         # 0 error；primary 743 / supervision 436
python tools/towerctl.py authority-check       # exit 0 / configured / required
python tools/towerctl.py arch-check            # gates 18 / events 32 / adrs 8
python tools/towerctl.py profile-check         # 11/0
python tools/towerctl.py where --json          # C-04 17 节点；078 在途时 index 16
python tools/towerctl.py campaign-check        # exit 0
python tools/towerctl.py shape-check           # exit 0
python -B tools/run_tests.py                   # Ran 844 / OK (skipped=1)
```

`wiring` 不通过 = ORPHANED；`state-verify` drift = 先停；`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链 → 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet。
新建 spec 必须带 `objective` 四要素；新卡 `@2`，旧 `@1` 冻结。

## 已知残余

- **065–068 只有回填事实**：`MERGE_HISTORICAL` 不等于审计 admin；审计 admin 仍只有 070/073/076。
- **071/074/075/077 的 direct admin + recover**：审计字段是 `recovered=true`；不是常规审计路径。
- **076 legacy bootstrap**：owner GitHub 批准门从 077 起强制，076 不能被引用为"已强制"。
- **072 parked → void**：复用 072 会被 `task-new` 拒绝；task-reopen 仍未实现。
- **063 closed 无 envelope、064 ABANDONED、069 superseded**：历史保留，不补 envelope。
- **078 未收口**：文档卡；未 merge 前 `where` 是 `16/17`，不是 `17/17`。
- **外证未开始**：真实外部项目 0。
- **online CI 未跑**：本轮只有本地 844 绿；工作流 `fetch-depth: 0` 与 8 步由 `test_ci_gate` 锁定。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令/阈值）**。
缺任何一段等于没有交接。
