# PILOT-026 — 塔套件计数入闸：post-merge 直接跑 tools/tests 并按 tower_tests_baseline 设门

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-026`

## Scope

- 把 cmd_post_merge 里的子进程调用抽成只读辅助 run_test_suite(argv, cwd)：复制环境、注入 PYTHONIOENCODING=utf-8 与 PYTHONDONTWRITEBYTECODE=1、以 UTF-8 + errors=replace 捕获输出；根套件行为与现有 tests_baseline 语义保持不变
- 当 envelope 带合法 tower_tests_baseline（int >= 1，且非 bool）时，post-merge 在塔根（root）直接运行 python -B -m unittest discover -s tools/tests -v，解析其 Ran N tests，并新增一项检查 tower tests count >= baseline：ok = 子进程 exit 0 且 tests_count 可解析且 >= baseline，detail 为 exit X, ran N, baseline B；目录缺失/跑不出计数即失败
- envelope 不带 tower_tests_baseline 时完全不跑塔套件、不新增检查，保持旧信封兼容
- 成功/失败路径都把 tower_tests_count 写进 envelope；review 文件新增 tower_tests_count 与 tower_tests_baseline 两行；POST_MERGE_VERIFIED / POST_MERGE_FAILED 的 ledger payload 都带 tower_tests_count
- write_task_merge_record 的 docstring 不再写死 4/4，改为 success 时记录全部检查数（避免检查数变化后文档过期）
- 同步更新 tests/test_hardening2.py 中 Post-merge checks: 5/5 断言为 6/6（只改这一行，检查总数从 5 变 6）
- 更新 tests/test_post_merge.py：fixture 支持 tower_tests_baseline 参数与可配置的极小塔套件，新增塔套件达标/低于基线/目录缺失/无 baseline 不跑/塔套件自身失败五类用例；不删除既有断言
- 不修改 tests/test_tower_gates.py、不改 CI workflow、不改状态文件格式

## Allowed paths

- `pilot/worktrees/PILOT-026/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-026/tower-dsh/tools/tests/test_post_merge.py`
- `pilot/worktrees/PILOT-026/tower-dsh/tools/tests/test_hardening2.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage

## Acceptance

- cd pilot/worktrees/PILOT-026/tower-dsh && python -B -m unittest discover -s tools/tests -v 全部通过，总数 >= 246（main 基线 241），且覆盖塔套件达标/低于基线/目录缺失/无 baseline/塔套件失败五类场景
- fixture：tower_tests_baseline=1 且塔套件 1 个测试 → post-merge PASS，checks 含 tower tests count >= baseline 且 detail 为 exit 0, ran 1, baseline 1，envelope.tower_tests_count=1，review 含 tower_tests_count/tower_tests_baseline 两行
- 同一 fixture 把 tower_tests_baseline 设为 2 → 判红（exit 2），envelope/queue 转 CORRECTION_REQUIRED，该检查 ok=false，且不产生 POST_MERGE_VERIFIED
- envelope 带 tower_tests_baseline 但塔根没有 tools/tests（或跑不出 Ran N）→ 该检查失败，post-merge 判红
- envelope 不带 tower_tests_baseline → 不运行塔套件、checks 中不出现 tower tests count >= baseline，既有测试行为不变
- 塔套件本身有失败测试（exit != 0）且计数达标 → 该检查仍失败
- test_hardening2.py 的 MERGE.md 断言更新为 6/6，该文件其余断言未改动
- 在真实塔上完成本卡自己的 post-merge：6/6，且 tower tests count >= baseline 为 exit 0、ran >= 241、baseline 241；review 如实记录
- python tools/towerctl.py spec-coverage 为 27/27 且 tool_gaps 为空；python tools/towerctl.py spec-lint --strict 为 6/6
- git -C pilot/worktrees/PILOT-026 diff --name-only main..HEAD 恰好三个 allowed_paths 文件
- 既有 post-merge 行为不回归：FAIL 可重试、review 先于写文件、tool-owned 忽略、clean 检查、状态守卫、根套件计数门原测试全绿
