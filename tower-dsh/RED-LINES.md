# 红线清单 — tower-dsh（触碰即停）

> 性质：L0 级文档。任何角色（含 controller）触碰即停，不得自行修复、不得重试、不得“先做了再报”。
> 唯一合法动作：**停下 → 记录到 ledger（若有权）→ 报告 owner → 等口令**。
> 来源：`TOWER.md` 四闸 + `shared/AUTHORITY_MODEL.json` + AUDIT-2026-10-19。

## 1. 四闸（永远归 owner `mac`）

| 闸 | 含义 | 谁能开 |
|---|---|---|
| merge | 合并任何分支到 base（含 `git merge`、`push --force`、改远端 main） | 仅 owner 逐次授权；Phase 2 起由 supervision 执行 |
| external_call | 任何离开本机的调用（网络、第三方 API、生产接口、上传） | 仅 owner 逐次授权 |
| deploy_prod | 部署、发布、生产数据读写、迁移、退役 | 仅 owner 逐次授权；默认 `no_access` |
| l0_main | 写 L0 文档到 main（见 `CHANGE-LEVELS.md`） | 仅 owner 逐次授权 |

## 2. 红线（硬停，无例外）

1. **未授权 merge / 强推 / 改远端分支。**
2. **未授权外部调用**（含把本地内容上传到未批准的服务）。
3. **部署、生产读写、数据迁移、退役**——本塔一律 `no_access`。
4. **手改** `primary/CURRENT_STATE.json`、`primary/TASK_BOARD.json`、`supervision/*.json`、`ledger/*.jsonl`、`tasks/*/record.json`。
5. **伪造证据**：改证据文件、补造 ledger 事件、用“文件存在”代替“检查通过”。
6. **executor 写 `allowed_paths` 之外的文件**；**reviewer 改工作树**。
7. **自审自批**：executor = reviewer；primary = merge 批准者；作者 = 验收者。
8. **读取或回显凭据**（token、私钥、密码、cookie）。
9. **把聊天记录当状态**，或在没有证据时声明“完成”。
10. **跳过闸点**：在 `spec_gate != PASS` 时 dispatch；在未 queued 时 merge；在未 `POST_MERGE_VERIFIED` 时宣布完成。

## 3. 触碰后的处置

```text
STOP
  → 不修、不重试、不掩盖
  → 记录：什么、何时、哪条红线、影响面
  → 报告 owner（附证据）
  → 等 owner 口令
```

若已产生副作用：**保留现场**（不清理、不回滚），由 owner 决定处置。

## 4. 与变更分级的关系

每条红线对应 `CHANGE-LEVELS.md` 的 L0/L1 动作；分级只决定“走哪条审批链”，**不豁免红线**。
判级有争议时就高不就低。
