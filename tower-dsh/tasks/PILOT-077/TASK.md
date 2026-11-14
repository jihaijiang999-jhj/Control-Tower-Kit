# PILOT-077 — post-merge 测试隔离与稳定 MERGED 快照；恢复 076 后 9/9

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-077`

## Scope

- post-merge 测试前 snapshot tower 状态（supervision/envelopes、MERGE_QUEUE、ledger/supervision.jsonl、primary/TASK_BOARD、tasks/<id>/record.json），测试期间不改这些文件
- 测试环境设 TOWER_POST_MERGE=1；root tests/test_tower_gates.py 在该环境只跑本层门，不递归整套；tools/tests 仍全量
- 失败路径：先 restore snapshot，再写 CORRECTION_REQUIRED + POST_MERGE_FAILED；成功路径才写 POST_MERGE_VERIFIED
- 076 恢复：envelope-recover 到 MERGED（0d9cab0），提交稳定快照，再 post-merge 9/9
- 补测试：snapshot/restore 字节一致；失败不污染 envelope/queue；递归被阻断；076 恢复路径
- 不改 074 的 merge_fact_gate、075 的 recover、076 owner/review 语义

## Allowed paths

- `pilot/worktrees/PILOT-077/tower-dsh/tools/tower_post_merge.py`
- `pilot/worktrees/PILOT-077/tower-dsh/tools/tower_cli.py`
- `pilot/worktrees/PILOT-077/tests/test_tower_gates.py`
- `pilot/worktrees/PILOT-077/tower-dsh/tools/tests/test_post_merge_isolation.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- skipping real tests
- weakening 9 checks
- writing verified without tests

## Acceptance

- cd pilot/worktrees/PILOT-077/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 834 + 新增用例数（main 基线 834）
- post-merge 测试期间 ENV 状态字节不变；测试进程看到 MERGED；失败后 restore 再 CORRECTION，snapshot 字节一致
- test_tower_gate_suite 在 TOWER_POST_MERGE=1 下不递归，tools/tests 仍全量
- 076 真实恢复：ENV-PILOT-076 MERGED，post-merge 9/9，drift 0
- 077 自身 PR 审计 admin；真实塔 76/73 drift []；arch 18；profile 11/0；shape 0
