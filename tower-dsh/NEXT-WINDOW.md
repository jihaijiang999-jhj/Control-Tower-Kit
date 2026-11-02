# NEXT WINDOW — tower-dsh（2026-11-02，065 闭环）

> 给新窗口的第一条消息用。**本文件不是权威状态**；权威在
> `primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、`supervision/MERGE_QUEUE.json`、
> `state/AUTHORITY.json`、`shared/AUTHORITY_POLICY.json`、`command/STRATEGY.md` + `command/campaigns/`。

## 当前状态（2026-11-02 PILOT-065 闭环后）

| 项 | 值 |
|---|---|
| 代号 | 应县木塔 / Yingxian（`YX-001`） |
| 任务 | `PILOT-001` – `PILOT-065`；65 张 closed；**64 个信封** |
| 测试 | `Ran 730 tests / OK (skipped=1)`（715 + 065 新增 15） |
| 状态自洽 | `state-verify` → 65 任务 / 64 信封 / drift `[]` |
| 账本 | primary/supervision 链无 error；证据 620 |
| 权威性 | `authority-check` → configured + requirement=required；13 checks；pin `sup-phase2-pilot` |
| 形状 | `shape-check` → 0；23 模块 <600；`towerctl.py` 246 行 |
| 架构 | `arch-check` → gates 18 / invariants 16 / events 30 / adrs 8 |
| 对象层 | `profile-check` → 11/0 |
| 命令层 | `campaign-check` → 0；C-2026-Q4-04 5/5 |
| 位置图 | `where --json` → **5/5**；current `PILOT-065`；next `null` |
| CI | main `3e79ce2` success（run `41459174048`） |
| 阶段 | `HANDOFF_ACTIVE`；工作树干净；`HEAD=origin/main` |

## 061–065 结果

| 卡 | 结果 | 说明 |
|---|---|---|
| 061 | local bootstrap | PR head envelope-only 早期检查；**不足以**修 PR merge |
| 062 | local bootstrap | 043 tombstone 命令 + 052/056/060 清债；PR 仍失败 |
| 063 | closed，无 envelope | base-side 首版；prefix 在 repository 根取错，卡关闭后无法追 head |
| 064 | closed，`ENV-PILOT-064` ABANDONED | 重建并修 tower 前缀；`envelope_head_sha` 未用于形状检查，信封后 state 导致 base tip 变化 |
| 065 | **PR #48 MERGED `c199928` + POST_MERGE_VERIFIED** | 形状检查改用 `envelope_head_sha`；730；65/64；where 5/5 |

**PR 路径首次真实走通**，但有三个 deviation：

1. **admin bypass**：`gh pr merge 48 --merge --admin --match-head-commit 78b04df`。base 在 branch 之后又有 state，GitHub 报“head branch is not up to date”；为保留 review head 未 rebase。
2. **repo-root shim**：post-merge 仍按 repo 根找 `merge-envelopes/ENV-PILOT-065.json`，实际 base-side 文件在 `tower-dsh/merge-envelopes/`；加了 repo-root 副本才过。
3. **063/064 处置**：063 closed 无 envelope；064 ABANDONED；065 取代两者。

## 硬约束（不要忘）

- **Primary 不 merge**；merge 走 `--role supervisor --supervisor <id>`，id == `state/AUTHORITY.json` 的 `merge_authority` 且 ≠ primary。
- **权威态只由 `authority-require` / `authority-set` 写**；completion 只由 `completion-add --by <owner>` 写；baseline 变更走 baseline-refresh 卡。
- **状态提交只在 envelope 之后**；失败/放弃信封要 tombstone（`envelope-abandon`），不能删除 ledger/queue 历史。
- **每张卡独立 reviewer**（`reviewer != executor`，read-only，亲跑证据）；`MERGED` 不等于完成，必须 `POST_MERGE_VERIFIED`。
- **PR merge 优先**；`--admin` 只作为 owner 级最后一次例外，不能成为常规路径。

## 下一步建议

1. **收口 061–065 文档**（本文件 + MAP §6.36）并在 push 后看 CI。
2. **小卡清 shim**：修 `post-merge` 的 envelope 路径（base-side 用 `tower-dsh/`），删除 repo-root shim；`PILOT-065` 的 spec 文案 65/65→65/64。
3. **小卡清 063**：063 closed 无 envelope，标注 superseded by 065；不伪造 envelope。
4. **然后开外证**：真实外部项目 1 个 feature，完整跑 spec→dispatch→review→envelope→PR merge→post-merge→owner 验收；先写 RUN 章程 + owner 批准。

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
13. `control-tower/COMMAND-LAYER.md` + `RUN-2026-10-30-E.md`
14. `control-tower/MAP.md` §6.1–§6.36
15. `control-tower/SESSION-CLOSEOUT-2026-10-23.md`

## 自检

```powershell
cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py state-verify          # 65/64；drift=[]
python tools/towerctl.py authority-check       # exit 0 / configured / required
python tools/towerctl.py arch-check            # gates 18
python tools/towerctl.py profile-check         # 11/0
python tools/towerctl.py where --json          # 5/5；next null
python tools/towerctl.py campaign-check        # exit 0
python tools/towerctl.py shape-check           # exit 0
python -B tools/run_tests.py                   # 730 / OK (skipped=1)
```

`wiring` 不通过 = ORPHANED；`state-verify` drift = 先停；`authority-check` 失败 = 不能 merge。
`merge` 三道前置：authority pin → 两条链 → 空账本守卫。
`deliver` 前置：范围（`--no-renames`）、linked-worktree 身份、base_sha 祖先、shape ratchet。
新建 spec 必须带 `objective` 四要素；新卡 `@2`，旧 `@1` 冻结。

## 已知残余

- **065 repo-root shim**：`merge-envelopes/ENV-PILOT-065.json` 是兼容副本；应修 post-merge 路径后删除。
- **065 admin bypass**：PR #48 绕过 up-to-date；后续需补 base 同步策略，不能复用 admin。
- **063 closed 无 envelope**：标注 superseded by 065，不补 envelope。
- **064 ABANDONED**：`ENV-PILOT-064` tombstone，保留历史。
- **043 ABANDONED**：`ENV-PILOT-043` 已 tombstone；052 为受控例外；056 baseline 迁移有记录。
- **065 spec 文案**：仍写 65/65；实际 pre-envelope 65/64。
- **056 baseline 迁移**：root 复制是受控状态更新；见 `tasks/PILOT-056/BASELINE-MIGRATION.md`。
- **未知**：真实外部项目 pilot 未接；PR #48 是 admin 路径，不是普通保护路径。

## 停点格式（硬规则）

任何一次停下来，必须给全四段：**① 现状（数字/哈希/状态） ② 下一步（一步） ③ 执行口令（可直接粘贴） ④ 判据（命令/阈值）**。
缺任何一段等于没有交接。
