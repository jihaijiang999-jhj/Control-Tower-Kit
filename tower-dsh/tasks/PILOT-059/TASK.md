# PILOT-059 — 每卡 ACCEPTANCE.md：自动/人工分项

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-059`

## Scope

- task-new：为新卡写 tasks/<id>/ACCEPTANCE.json（schema tower/acceptance@1，items:[{id:'A-01',kind:'auto',status:'pending',note:''}]）和 ACCEPTANCE.md（表格：ID/kind/status/note）
- 新增 towerctl acceptance-add --task --id --kind auto|manual --status pending|passed|failed --note [--replace]：id 唯一；auto/manual 不可改；写 JSON 并重渲染 MD；未知 task exit 2 零写入
- accept --task --decision：读 ACCEPTANCE.json；任何 auto 不是 passed → exit 2；任何 item failed → exit 2；manual pending 且未传 --allow-manual-pending → exit 2；传了则每项 pending 必须有非空 note；全通过才写 ACCEPT
- checkback 不强制 ACCEPTANCE（review 与 acceptance 分离）；deliver/close 不改验收状态
- 旧卡（001–058）无 ACCEPTANCE.json 保持兼容，不回溯、不因缺失失败；059 及以后 task-new 必须生成
- 测试：task-new 生成；add auto passed/manual passed；auto pending 拒绝；failed 拒绝；manual pending 无 flag 拒绝；有 flag 且 note 通过；MD 渲染与 JSON 一致
- 不改 036–058 的授权/账本/双塔/信封/合并/记录层/ID/review 语义；只加验收分项

## Allowed paths

- `pilot/worktrees/PILOT-059/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-059/tower-dsh/tools/tests/test_acceptance.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- accepting with a pending auto item
- treating a real failure as manual pending
- weakening owner gates

## Acceptance

- cd pilot/worktrees/PILOT-059/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 646 + 新增用例数（main 基线 646）
- task-new 生成 ACCEPTANCE.json（A-01 auto pending）与 ACCEPTANCE.md；JSON/MD 一致
- acceptance-add 增 A-02 auto passed、M-01 manual passed 成功；重复 id 不加 --replace → exit 2；未知 task → exit 2 零写入
- accept：A-01 pending → exit 2；A-01 passed 但 M-01 pending 且无 --allow-manual-pending → exit 2；带 flag 且 note 空 → exit 2；带 flag 且 note 非空 → 0 并写 ACCEPT；任何 failed → exit 2
- 真实塔 state-verify drift []；真塔 tasks=58/envelopes=57（059 建卡后），建信封后 58/58
- git -C pilot/worktrees/PILOT-059 diff --name-only main..HEAD 恰 2 个 allowed_paths
