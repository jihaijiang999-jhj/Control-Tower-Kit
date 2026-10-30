# PILOT-051 — depends_on 硬校验：存在、闭合、无环

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-051`

## Scope

- task-new：depends_on 必须是非空字符串列表（可为空列表）；不得自依赖；重复 id 去重后报 duplicate；每个 id 必须能在 board 或 tasks/ 找到；结构校验在写 record/TASK/ledger 之前，失败 exit 2 零写入
- check --phase ready：读取 record.depends_on，每个目标 status 必须为 closed；否则 exit 2，错误点名 depends_on.<id>: <status>（或 missing）
- dispatch：再次校验依赖闭合（不信任 ready 时的状态，可能在等待期间被 VOID/重开）；失败 exit 2 且不写 record/ledger
- 环检测：沿所有 task record 的 depends_on 做 DFS；发现环（含自依赖）→ exit 2，列出环上的 id；无环通过
- specs/WF-TASK.md 增加“卡依赖前置不变量”：结构/闭合/无环三层、错误码、允许先建卡后等依赖
- ARCHITECTURE.md 的契约节补“卡依赖”一行（task-new/ready/dispatch 三处校验点）
- 新增 tools/tests/test_dependencies.py：缺目标/自依赖/重复/未闭合/环/合法 ready/dispatch 零写入/旧卡空 depends_on 通过；全部干净 exit 2 无 Traceback
- 不改 036–050 的信任边界/授权/前置链/范围门/completion/shape/objective/campaign 语义；不新增事件类型；不改 spec@2 字段；不写 primary/supervision/ledger

## Allowed paths

- `pilot/worktrees/PILOT-051/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-051/tower-dsh/tools/tests/test_dependencies.py`
- `pilot/worktrees/PILOT-051/tower-dsh/specs/WF-TASK.md`
- `pilot/worktrees/PILOT-051/tower-dsh/ARCHITECTURE.md`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening existing gates
- new ledger event types
- changing tower/spec@2 fields
- requiring dependencies to be closed at task-new time
- touching TOWER.md (L0)

## Acceptance

- cd pilot/worktrees/PILOT-051/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 569 + 新增用例数（main 基线 569）
- task-new：自依赖/重复/指向不存在卡 → exit 2 单 JSON，tasks/<id>/ 与 ledger 不变；空 depends_on 与合法依赖通过；依赖目标处于 ready 时允许多建卡（不要求闭合）
- check --phase ready：依赖未闭合 → exit 2 点名 depends_on.<id>；全部 closed → exit 0；缺失目标 → exit 2
- dispatch：依赖未闭合 → exit 2 且 record/ledger 零写入；闭合 → 正常派发
- 环：A→B→A（或自依赖）→ exit 2 列出环；无环通过；错误无 Traceback
- specs/WF-TASK.md 含依赖不变量节且 spec-lint 6/6；ARCHITECTURE.md 契约节含卡依赖一行；arch-check exit 0
- 旧码对照：main 对未闭合依赖 ready/dispatch 均放行；新码 ready/dispatch 拒绝。证据写进 scratch/probe-old-code.txt
- shape-check 在 worktree exit 0（新增函数 ≤80 行/≤12 分支；既有函数不增长）
- 真实塔：worktree 新工具 campaign-check/arch-check/authority-check exit 0、state-verify drift []；建信封前 tasks=51/envelopes=49，建信封后 51/50；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-051 diff --name-only main..HEAD 恰四个 allowed_paths
