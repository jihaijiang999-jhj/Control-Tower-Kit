# PILOT-027 — 测试运行器收口：TMP 指向仓内沙箱，受限环境可复跑

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-027`

## Scope

- 新增 tower-dsh/tools/run_tests.py：默认在塔根下创建 .test-tmp/run-<时间戳>-<pid>/，把 TMPDIR/TEMP/TMP 指向它，再以 sys.executable -B -m unittest discover -s <suite> -p <pattern> -v 运行；支持 --suite/--pattern/--tmp-root；运行前打印 TOWER_TEST_TMP=<路径>；退出码等于子进程；运行目录保留不自动删除（已在 gitignore）
- post-merge 的塔套件门改用运行器（cwd=塔根，argv=[python,-B,tools/run_tests.py]），仍解析 Ran N tests 并按 tower_tests_baseline 设门；根套件门不变
- 根门禁 tests/test_tower_gates.py 的内层塔套件也改用运行器（cwd=TOWER），保留 returncode==0 与 Ran N>=8 断言
- 仓库 .gitignore 增加 tower-dsh/.test-tmp/；REPRODUCE.md 写清干净环境复跑清单（Python 3.12、命令、TMP 位置、预期 Ran 246+、失败保留现场、清理方式）
- 新增 tools/tests/test_run_tests.py：验证 TMP/TEMP/TMPDIR 指向仓内路径且三个值一致、子进程继承、退出码透传、--suite/--pattern 可指向临时小套件（避免递归）、.test-tmp 被 gitignore、默认路径在塔根内
- 不修改现有测试的 tempfile 用法（运行器通过环境变量全局生效）；不改 post-merge 的计数/证据语义

## Allowed paths

- `pilot/worktrees/PILOT-027/tower-dsh/tools/run_tests.py`
- `pilot/worktrees/PILOT-027/tower-dsh/tools/tests/test_run_tests.py`
- `pilot/worktrees/PILOT-027/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-027/tests/test_tower_gates.py`
- `pilot/worktrees/PILOT-027/.gitignore`
- `pilot/worktrees/PILOT-027/tower-dsh/REPRODUCE.md`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hiding failures by swallowing child exit codes

## Acceptance

- cd pilot/worktrees/PILOT-027/tower-dsh && python -B tools/run_tests.py 全部通过，总数 >= 246（main 基线 246），输出含 TOWER_TEST_TMP= 且路径在塔根内
- 直接 python -B -m unittest discover -s tools/tests -v 仍然通过（向后兼容，不强制运行器）
- test_run_tests.py 覆盖：TMP/TEMP/TMPDIR 三值一致且在塔根内、子进程可见、失败套件退出码非 0 透传、--suite/--pattern 跑临时小套件不递归、.test-tmp 被 gitignore
- post-merge fixture：tower_tests_baseline=1 且塔套件 1 个测试时，检查 detail 仍为 exit 0, ran 1, baseline 1（运行器接入未破坏计数）
- 在真实塔完成本卡 post-merge：6/6，塔套件计数 ran >= 246、baseline 246（本卡信封），review 含 tower_tests_count
- REPRODUCE.md 含可复制命令、预期输出与失败保留现场说明
- python tools/towerctl.py spec-coverage 27/27、spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-027 diff --name-only main..HEAD 恰好六个 allowed_paths 文件
- 原有 post-merge/计数/门禁测试全绿
