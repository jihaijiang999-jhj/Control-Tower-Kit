# PILOT-030 — queue-add 也强制 baseline：堵住手写信封入队旁路

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-030`

## Scope

- cmd_queue_add 在把信封加入 MERGE_QUEUE 之前，重新校验 envelope.tests_baseline 与 envelope.tower_tests_baseline：都必须是 int（非 bool）且 >= 1；否则 exit 2，错误同时点名两字段
- 校验失败不得修改 MERGE_QUEUE.json、不得追加 QUEUE_ADD 事件、不得改任何任务状态；成功路径行为不变
- 已存在队列条目不受影响（queue-add 对重复入队仍直接报错）；legacy 已入队信封不回查
- 扩展 tools/tests/test_envelope_baseline.py：手写信封缺 baseline → queue-add exit 2 且 queue/ledger 不变；手写信封带合法 baseline → queue-add 成功；envelope-new 生成的信封 → queue-add 成功；重复入队仍报错
- 不修改 merge-check、post-merge、envelope-new 的行为

## Allowed paths

- `pilot/worktrees/PILOT-030/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-030/tower-dsh/tools/tests/test_envelope_baseline.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- allowing an envelope without both baselines into the queue

## Acceptance

- cd pilot/worktrees/PILOT-030/tower-dsh && python -B tools/run_tests.py 全部通过，总数 >= 266（main 基线 266）
- 手写 supervision/envelopes/<id>.json（无 tests_baseline 或 tower_tests_baseline）后 queue-add → exit 2，错误含两字段名，MERGE_QUEUE.json 与 supervision ledger 字节不变
- 手写信封带合法 1/1 → queue-add exit 0，队列出现 WAITING，QUEUE_ADD 事件恰一条
- envelope-new 正常生成的信封 → queue-add exit 0（回归）
- 同一信封重复 queue-add → 仍 exit 2（already queued）
- 既有 envelope-new / merge-check / post-merge 测试全绿
- python tools/towerctl.py spec-coverage 27/27、spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-030 diff --name-only main..HEAD 恰好两个 allowed_paths 文件
