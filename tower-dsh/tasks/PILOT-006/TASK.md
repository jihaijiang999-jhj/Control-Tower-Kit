# PILOT-006 — ledger 锁 Windows 竞态修复：PermissionError 视作锁竞争 + 并发压测

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-006`

## Scope

- Windows 上 O_CREAT|O_EXCL 返回 ERROR_ACCESS_DENIED(13) 时按“锁已被占用”处理并重试，而不是抛错
- 仅 Windows 生效；POSIX 上 PermissionError 仍视为真实错误
- _release_lock_file 的 stat/unlink 容忍 OSError（含 PermissionError）
- ledger_lock 取锁后 stat 失败时 identity=None，不崩溃
- _clear_stale_lock 的 os.replace 容忍 PermissionError 并返回 False
- 新增 tools/tests/test_ledger_lock_windows.py：8 线程×5 连续 20 轮 0 失败；8 线程×20 共 160 条 seq 连续；超时与陈旧锁行为不回归

## Allowed paths

- `pilot/worktrees/PILOT-006/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-006/tower-dsh/tools/tests/test_ledger_lock_windows.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access

## Acceptance

- python -B -m unittest discover -s tools/tests -v 全部通过，总用例数 >= 54
- 并发用例连续 20 轮（8 线程×5）零失败
- 8 线程×20 次 append 产生 160 条事件，seq 1..160 连续且链可验证
- 持锁超时仍 exit 2 / 抛 LedgerLockTimeout；陈旧锁仍可清理
- 既有 51 个用例全部仍通过
- startup / wiring / handoff-check 不回归
