# PILOT-057 — Task ID 注册表：ID 永不复用

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-057`

## Scope

- 新增 state/TASK_IDS.json（schema tower/task-ids@1）：{ids: {PILOT-xxx: {title,status,spec_path,created_at,updated_at}}, next?: null}；status ∈ reserved/active/closed/void
- 新增 towerctl task-ids-init：扫描 tasks/PILOT-*（含 PILOT-*-VOID、PILOT-*-VOID2）去重，按 record.status 与目录名推导 closed/void/active，写注册表；已存在注册表时只在缺失 ID 上补齐，不覆盖现有条目
- 新增 towerctl task-ids-reserve --id --title [--spec]：为未建卡草稿占号（如 056）；已存在 ID exit 2
- task-new：写卡前检查 id；active/closed/void 已存在 → exit 2 零写入；reserved 可被本命令消费为 active（激活草稿占号），写卡后登记 active
- close：成功后把对应 ID 置 closed；task-ids-init 对 `-VOID` 目录置 void；不删除条目
- check --phase spec：校验 ID 在注册表且 title 与 spec 一致；缺失/不一致 exit 2
- 真实塔：init 后 001–055 全部登记（043/055 为 void/closed），056 可 reserve；task-new 057 成功；再用 057/055/043 建卡均 exit 2 零写入
- 不改 036–056 的授权/账本/双塔/信封/合并/记录层语义；注册表只做 ID 占用，不做调度
- reserved 生命周期：task-ids-reserve 占号；task-new 只能消费 reserved（不能消费 active/closed/void）；消费后变 active，再次 task-new 拒绝

## Allowed paths

- `pilot/worktrees/PILOT-057/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-057/tower-dsh/tools/tests/test_task_registry.py`
- `pilot/worktrees/PILOT-057/tower-dsh/state/TASK_IDS.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- reusing/reserving an existing ID
- deleting registry entries
- weakening task-new/close/check gates

## Acceptance

- cd pilot/worktrees/PILOT-057/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 638 + 新增用例数（main 基线 638）
- task-ids-init 在真实塔写出 55 个 ID；001–055 每个恰一条；043/055 状态为 void/closed；重复运行字节稳定或仅补缺失，不覆盖
- task-new 057 成功并登记 active；再用 057、055、043 分别 task-new → exit 2 且 tasks/ / board / ledger 零写入
- task-ids-reserve 056 成功；task-new 056 成功并置 active；再次 task-new 056 拒绝；active/closed/void 仍零写入拒绝；close 057 后注册表 status=closed
- check --phase spec 对缺失/标题不一致注册表 exit 2；正常卡 exit 0
- 真实塔 state-verify drift []；真塔 tasks=56/envelopes=55（057 建卡后），建信封后 56/56
- git -C pilot/worktrees/PILOT-057 diff --name-only main..HEAD 恰 3 个 allowed_paths
- reserve 056 后 task-new 056 成功并置 active；再次 task-new 056 拒绝；active/closed/void 仍零写入拒绝
