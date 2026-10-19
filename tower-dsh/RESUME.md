# Resume tower-dsh

当前状态：`HANDOFF_ACTIVE`，active controller 是 `ctl-phase3-receiver-001`。

## 新会话接续

1. 在 DSH 新建会话，选择同一 workspace：`C:\Users\mac\Documents\deepseek-harness\default-workspace`
2. 打开 `handoffs/HANDOFF-PILOT-001/RESUME-PROMPT.md`
3. 把其中的代码块整段粘贴为第一条消息
4. 新会话只做只读自检；报结果后等 owner 口令

## 当前锚点

- main：`9fb5ba243f5cf03f7ccafb0eb381793770835db2`
- worktree：`ed28ac618f524db7d5db426db3839cd185a6da11`
- queue：`POST_MERGE_VERIFIED`
- task：`PILOT-001` closed
- package：`HANDOFF-PILOT-001` ACTIVE
- source：`ctl-8cd51ef9-2972-415a-b1db-d8d37afdde82`
- receiver：`ctl-phase3-receiver-001`

## 不要做

- 不要重复 claim/accept/activate；
- 不要 merge/生产/外部调用；
- 不要手改 `primary/`、`supervision/`、`ledger/`。
