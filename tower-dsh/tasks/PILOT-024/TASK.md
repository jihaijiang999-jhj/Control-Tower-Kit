# PILOT-024 — post-merge 门禁解码：子进程非 UTF-8 输出不再让门禁误判红

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-024`

## Scope

- 根目录 tests/test_tower_gates.py 中启动塔套件的子进程调用统一走一个捕获辅助函数：显式向子进程注入 PYTHONIOENCODING=utf-8，并以 UTF-8 + errors=replace 解码 stdout/stderr（或等价健壮策略）
- 任何子进程输出中的非 UTF-8 字节不得抛出 UnicodeDecodeError，也不得让 captured stdout/stderr 变成 None 而导致二次异常（TypeError）
- 保留原有门禁语义与断言：塔套件 returncode 必须为 0、stderr 必须匹配 Ran N test、N >= 8；本卡只修解码健壮性，不改变跑什么套件
- 新增回归测试：用同一捕获辅助函数运行一个故意向 sys.stdout.buffer 写 b\xbf 的子进程，断言不抛异常、stdout/stderr 为 str、returncode 可读
- 旧码对照证据：在 main 版 test_tower_gates 的解码策略下，同一非 UTF-8 子进程会抛 UnicodeDecodeError；修复版通过
- 不修改 tower-dsh 内任何文件、不修改 .github workflow、不改测试断言阈值

## Allowed paths

- `pilot/worktrees/PILOT-024/tests/test_tower_gates.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening existing gate assertions
- changing what the gate suite runs

## Acceptance

- cd pilot/worktrees/PILOT-024 && python -B -m unittest discover -s tests -v 全部通过（>= 2 tests），且塔套件子测试仍跑满全量（Ran 236 tests）并 >= 8
- 新增的坏字节子进程回归测试通过：不抛 UnicodeDecodeError/TypeError，stdout/stderr 均为 str，returncode 可读
- 旧码对照证据：main 版解码策略（text=True, encoding=utf-8, 不设 errors）对同一坏字节子进程抛 UnicodeDecodeError，已捕获记录
- 在真实塔根运行修复后的 gate 套件：python -B -m unittest discover -s tests -v 通过，不再因非 UTF-8 输出崩溃
- git -C pilot/worktrees/PILOT-024 diff --name-only main..HEAD 恰好一个 allowed_paths 文件
- 在 tower-dsh 下 python tools/towerctl.py spec-lint --strict 为 6/6、spec-coverage 为 27/27（本卡不触碰规范文件）
