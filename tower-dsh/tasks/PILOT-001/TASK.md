# PILOT-001 — Ledger SHA-256 哈希链模块与篡改检测

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-001`

## Scope

- 实现 ledger_chain.py：append_event 追加事件并维护 prev_hash/hash 链
- 实现 verify_chain：校验 seq、prev_hash、hash、JSON 结构
- 为内容篡改、prev_hash 篡改、seq 篡改、hash 篡改编写测试
- 提供 README 说明运行命令

## Allowed paths

- `pilot/worktrees/PILOT-001/ledger_chain.py`
- `pilot/worktrees/PILOT-001/tests/test_ledger_chain.py`
- `pilot/worktrees/PILOT-001/README.md`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- append_event 生成 prev_hash/hash 链
- verify_chain 对合法链返回 ok=true
- 内容篡改、prev_hash 篡改、seq 篡改、hash 篡改均被检测为失败
- python -m unittest discover -s tests -v 全部通过
- README 给出运行命令
