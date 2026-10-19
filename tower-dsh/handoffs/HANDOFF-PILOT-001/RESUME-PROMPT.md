# Resume Prompt — HANDOFF-PILOT-001

> 用法：在 DSH 里**新建一个会话**（同一 workspace：`C:\Users\mac\Documents\deepseek-harness\default-workspace`），把下面代码块整段粘贴为第一条消息。

```text
你是 tower-dsh 的接续 controller `ctl-phase3-receiver-001`。
工作区：C:\Users\mac\Documents\deepseek-harness\default-workspace
塔根：C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh

先读：
1. tower-dsh/TOWER.md
2. tower-dsh/START-HERE.md
3. tower-dsh/handoffs/HANDOFF-PILOT-001/HANDOFF.md（§0/§0a/§1–§7）
4. tower-dsh/handoffs/HANDOFF-PILOT-001/SELF-CHECK.md
5. tower-dsh/primary/CURRENT_STATE.json
6. tower-dsh/supervision/CURRENT_STATE.json
7. tower-dsh/primary/TASK_BOARD.json
8. tower-dsh/supervision/MERGE_QUEUE.json

然后运行（只读）：

cd tower-dsh
python tools/towerctl.py startup
python tools/towerctl.py wiring
python tools/towerctl.py status
python tools/towerctl.py handoff-check --package HANDOFF-PILOT-001

做全项实值比对：
- main SHA = 9fb5ba243f5cf03f7ccafb0eb381793770835db2
- worktree head = ed28ac618f524db7d5db426db3839cd185a6da11
- merge queue = POST_MERGE_VERIFIED
- task PILOT-001 = closed
- repo / worktree clean
- 6 项证据 SHA-256 匹配
- package HANDOFF-PILOT-001 = ACTIVE

报一句自检结果 + 在途清单（应为空）+ 下一动作，然后停，等 owner 口令。
任何漂移如实报，不自行修正权威事实。
不要重复 handoff-claim / handoff-accept / handoff-activate；不要 merge、不要碰生产、不要外部调用；不要手改 primary/supervision/ledger 状态。
```

## 预期首条回复

```text
接续自检：PASS
- main 9fb5ba24… / worktree ed28ac61… / queue POST_MERGE_VERIFIED
- task PILOT-001 closed；证据 6/6 哈希匹配；repo/worktree clean
- package HANDOFF-PILOT-001 = ACTIVE
在途：无
下一动作：等 owner 口令（Phase 4 Console / 真实项目 pilot / 更新 TOWER 文档）
```

## 备注

- 当前窗口是 **source**，已停写 primary state；新会话才是 active controller。
- `TOWER.md` / `README.md` 仍写 Phase 2；新 controller 接管后可先更新为 Phase 3 / `HANDOFF_ACTIVE`（需 owner 口令）。
- 不要在新会话里再跑 `handoff-activate`；包已经是 `ACTIVE`。
