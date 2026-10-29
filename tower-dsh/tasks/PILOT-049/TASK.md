# PILOT-049 — objective 硬门：spec@2 四要素 + task-new/spec-lint 双层拒绝

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-049`

## Scope

- templates/task.spec.json 升级为 tower/spec@2，带 objective 四字段的真实示例（非占位符），并保留其余字段
- task-new：接受 tower/spec@1 与 tower/spec@2；对所有新 spec 校验 objective（对象存在、四字段齐全、均为非空 str、trim 后 ≥8、不含 __FILL__、不是 <...> 占位）；校验在创建 tasks/<id>/、写 record/TASK、append TASK_NEW 之前，失败零写入
- task-new：校验失败 exit 2 单 JSON（ok:false, errors:[...]），不产生半截任务卡；错误文案点名 objective.<field>
- spec-lint：扫描 pilot/*.spec.json；对 schema=tower/spec@2 强制 objective（同上规则），对 tower/spec@1 跳过（冻结旧卡，不回溯、不改哈希）；失败 exit 2 单 JSON、无 Traceback；不改变现有 6 份 policy/spec 文档的校验
- specs/WF-TASK.md 增加“施工目标前置不变量”一节：objective 四字段语义、task-new 零写入、spec-lint @2 强制、旧 @1 冻结、reviewer 仍需审真实性与 AC 对齐
- arch/GATES.json 增加 GATE-SPEC-OBJECTIVE（command=task-new、phase=spec、test 指向 test_objective 里的拒绝用例、blocks=无 objective/占位/过短）
- 新增 tools/tests/test_objective.py：正例 @2；缺 objective/逐字段缺/非字符串/空串/<8/__FILL__/<...> 全部 exit 2 且零写入；@1 旧 spec 在 spec-lint 下 exit 0；@2 坏 spec spec-lint exit 2；task-new 失败后 tasks/<id>/ 不存在、ledger 无 TASK_NEW；模板 @2 可被 task-new 接受（用临时 id）
- 不改 TOWER.md（L0，由 owner 单独提交一行不变量）；不改 044–048 的冻结 spec；不引依赖、不联网

## Allowed paths

- `pilot/worktrees/PILOT-049/tower-dsh/templates/task.spec.json`
- `pilot/worktrees/PILOT-049/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-049/tower-dsh/tools/spec_lint.py`
- `pilot/worktrees/PILOT-049/tower-dsh/tools/tests/test_objective.py`
- `pilot/worktrees/PILOT-049/tower-dsh/specs/WF-TASK.md`
- `pilot/worktrees/PILOT-049/tower-dsh/arch/GATES.json`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- rewriting frozen task specs (044-048)
- weakening existing gates
- changing TOWER.md in this card (L0; owner commits separately)
- accepting a spec with missing/placeholder objective

## Acceptance

- cd pilot/worktrees/PILOT-049/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 536 + 新增用例数（main 基线 536）
- task-new 对 @2 spec：缺 objective、逐字段缺、非字符串、空串、<8、__FILL__、<...> 全部 exit 2 单 JSON，且 tasks/<id>/ 不存在、ledger 无 TASK_NEW（零写入）；完整 @2 可通过
- task-new 对 @1 spec（含 objective 的 049 bootstrap）可通过；@1 无 objective 不在本卡回归范围（旧卡不重发）
- spec-lint：@2 坏 spec exit 2 单 JSON 无 Traceback；@1 旧 spec（无 objective）exit 0；现有 6 份 policy/spec 文档校验不变
- templates/task.spec.json 的 schema=tower/spec@2 且 objective 四字段为非占位示例；用临时 id/真实 worktree 可被 task-new 接受
- specs/WF-TASK.md 含 objective 前置不变量；arch/GATES.json 含 GATE-SPEC-OBJECTIVE 且 test 真实存在；arch-check 在 worktree exit 0
- 旧码对照：main 版 task-new 接受无 objective 的 spec、spec-lint 不扫 pilot/*.spec.json；新码拒绝。证据写进 scratch/probe-old-code.txt
- shape-check 在 worktree exit 0（新增函数全部 ≤80 行/≤12 分支）
- 真实塔：worktree 新工具 campaign-check/arch-check/authority-check exit 0、state-verify drift []；建信封前 tasks=49/envelopes=47，建信封后 49/48；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-049 diff --name-only main..HEAD 恰六个 allowed_paths
