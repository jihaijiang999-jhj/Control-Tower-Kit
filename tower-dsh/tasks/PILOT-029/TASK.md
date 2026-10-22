# PILOT-029 — baseline 必填：新信封必须声明 tests_baseline 与 tower_tests_baseline

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-029`

## Scope

- cmd_envelope_new 在写 DRAFT 前校验 envelope.tests_baseline 与 envelope.tower_tests_baseline：都必须是 int（非 bool）且 >= 1，否则 exit 2，错误信息同时点名两个字段与合法取值
- 校验失败不得产生 supervision/envelopes 文件、不得追加 ENVELOPE_NEW 事件、不得改任务状态
- 旧信封（已存在、无 baseline）不受影响：post-merge 的 legacy 路径与 merge-check 行为保持不变
- 更新现有 envelope-new 调用点的 fixture（tools/tests/test_coverage.py、tools/tests/test_hardening2.py）补上 tests_baseline 与 tower_tests_baseline
- 新增 tools/tests/test_envelope_baseline.py：缺 tests_baseline、缺 tower_tests_baseline、0、-1、True、"2"、1.0 各自 exit 2 且无副作用；两字段合法时成功建 DRAFT 且事件已追加；旧信封仍可 merge-check
- 不修改 post-merge 计数语义、不改 merge-check 对旧信封的兼容、不改状态 schema

## Allowed paths

- `pilot/worktrees/PILOT-029/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-029/tower-dsh/tools/tests/test_coverage.py`
- `pilot/worktrees/PILOT-029/tower-dsh/tools/tests/test_hardening2.py`
- `pilot/worktrees/PILOT-029/tower-dsh/tools/tests/test_envelope_baseline.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- allowing an envelope without both baselines to be created

## Acceptance

- cd pilot/worktrees/PILOT-029/tower-dsh && python -B -m unittest discover -s tools/tests -v 全部通过，总数 >= 250（main 基线 246 + 029 新增 >= 4），新增用例覆盖缺失/类型错误/合法三类
- 缺少任一 baseline 或取值非法（0/-1/True/"2"/1.0）→ exit 2，错误信息同时包含 tests_baseline 与 tower_tests_baseline，且 supervision/envelopes 下无新文件、ledger 无 ENVELOPE_NEW、record 状态不变
- 两字段合法（均为 int>=1）→ 建 DRAFT 成功、ENVELOPE_NEW 已追加、后续 queue-add/merge-check 正常
- 旧信封（无 baseline）仍能通过 merge-check，post-merge legacy 行为不变
- 在真实塔完成本卡 post-merge：6/6，且本卡信封由新校验放行（tests_baseline=2、tower_tests_baseline=冻结时主分支塔套件实测数）
- python tools/towerctl.py state-verify 真实塔 drift=[]（本卡未交付信封前 tasks=29、envelopes=28，skipped 仅 PILOT-025-VOID）
- python tools/towerctl.py spec-coverage 27/27、spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-029 diff --name-only main..HEAD 恰好四个 allowed_paths 文件
