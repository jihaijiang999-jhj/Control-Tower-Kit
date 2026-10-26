# PILOT-042 — 授权完成清单（completion list）+ dispatch 锚定 base_sha 作为 deliver 基线

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-042`

## Scope

- 新增 towerctl completion-add --task <id> --path <tower-root-relative> --by <name> --reason <text> --decision <id>：--by 必须等于 primary/CURRENT_STATE.json 的 owner.name；--reason/--decision 非空；task 状态必须在 ready/dispatched/delivered/rework，否则 exit 2；path 必须非空、非绝对、不含 ..、在塔根内（词法校验，允许尚不存在）
- completion-add 写入：primary ledger 事件 COMPLETION_ADDED（payload {task, path, by, reason, decision, at}）+ record.completions 列表（同构条目）；幂等（两侧都在 → already=true，不重复事件）；半写修复（有事件无记录 → 只补记录 repaired=true；有记录无事件 → 只补事件 repaired=true）；任何校验失败零写入
- deliver 范围门扩展：允许集 = 映射后的 allowed_paths ∪ 映射后的 record.completions（同一套 worktree 前缀映射规则）；成功输出增加 scope_completions（本次实际用到的 completion 路径，映射后）；越界仍 exit 2 且零写入
- dispatch 增加 base_sha：在 record.dispatch 与 DISPATCH payload 写入 {base_sha: git -C repo rev-parse main 的结果}；取不到 main 时 base_sha=null（不阻塞 dispatch，但 deliver 走旧回退）
- deliver 基线：若 record.dispatch.base_sha 非空 → 校验 git merge-base --is-ancestor <base_sha> HEAD（不是祖先即 exit 2），并用 git diff --no-renames <base_sha>..HEAD；base_sha 为空（旧 record）→ 回退 merge-base main HEAD（041 行为）；两条路径都必须保留 --no-renames 与 linked-worktree 身份检查
- state-verify 增加 completion 审计：record.completions 里每个 path 必须有对应 COMPLETION_ADDED 事件，否则 drift completion_unbacked（target=task，expected=path）；ledger 有 COMPLETION_ADDED 但 record 缺该 path → drift completion_missing；completions 条目字段类型（path/by/reason/decision 非空 str）非法 → drift completion_invalid；legacy 无 completions 的任务不产生新跳过/漂移
- 新增 tools/tests/test_completion_and_base.py：completion-add 正反/幂等/双向半写修复；deliver 接受 completion 路径并在 scope_completions 中体现；不在 allowed 也不在 completion 的路径仍拒；path 越界（.. / 绝对路径）拒；state-verify 三种 completion drift；base_sha：dispatch 记录、改写本地 main ref 后 deliver 仍按 base_sha 拒绝越界（旧行为会因 diff 为空放行）、base_sha 非祖先 exit 2、旧 record 无 base_sha 回退 merge-base
- tools/tests/test_deliver_scope.py 与 test_state_verify.py 仅在新增字段/新 drift 导致既有断言冲突时做最小调整（不得放宽断言）；不改其它测试文件
- 真实塔验证：用 worktree 新工具跑 authority-check/state-verify（configured+required、drift []）；建信封前 tasks=42/envelopes=41，建信封后 42/42；merge 前置链与空账本守卫仍通过
- 不改 036–041 的信任边界/授权/前置链/空账本/范围门语义（除本条明确扩展）；不手写 ledger；completion 不得用于绕过 merge/authority 等其它门

## Allowed paths

- `pilot/worktrees/PILOT-042/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-042/tower-dsh/tools/tests/test_completion_and_base.py`
- `pilot/worktrees/PILOT-042/tower-dsh/tools/tests/test_deliver_scope.py`
- `pilot/worktrees/PILOT-042/tower-dsh/tools/tests/test_state_verify.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- allowing a completion to bypass merge, authority, chain or empty-ledger gates
- accepting a completion path outside the tower root or containing '..'
- using the local main ref as the deliver baseline when base_sha is recorded

## Acceptance

- cd pilot/worktrees/PILOT-042/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 387 + 新增用例数（main 基线 387）
- completion-add 正常：record.completions 出现条目、primary ledger 恰一条 COMPLETION_ADDED、字段与 payload 同构；重复调用 already=true 且事件仍 1 条
- completion-add --by 非 owner / --reason 空 / --decision 空 / path 含 ..（或绝对路径）→ exit 2、零写入
- 半写修复：有事件无记录 → 只补记录（repaired=true，事件数不变）；有记录无事件 → 只补事件（repaired=true）
- deliver：分支改动含 completion 路径 → exit 0，scope_completions 含该映射路径；不在 allowed 也不在 completion 的越界文件仍 exit 2 且零写入
- state-verify：record completion 无事件 → drift completion_unbacked；事件无 record → drift completion_missing；条目字段非法 → drift completion_invalid；无 completions 的任务无新增 drift
- base_sha：dispatch 记录 base_sha（record.dispatch 与 DISPATCH payload 一致）；在 worktree 内 update-ref refs/heads/main HEAD 后，deliver 仍以 base_sha 为基线并拒绝越界改动（旧行为 diff 为空会放行）；base_sha 非 HEAD 祖先 → exit 2
- 旧 record（dispatch 无 base_sha）→ deliver 回退 merge-base main HEAD，行为与 041 一致（既有 deliver 测试全绿）
- 旧码对照：main 版工具在“有 completion 路径但不在 allowed”与“改写 main ref 后越界”两夹具上——前者 deliver exit 2（无 completion 概念）、后者 exit 0（diff 为空）；新码前者 0、后者 2。证据写进 scratch/probe-old-code.txt
- 真实塔：worktree 新工具 authority-check exit 0（configured+required）、state-verify drift []；建信封前 tasks=42/envelopes=41，建信封后 42/42；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-042 diff --name-only main..HEAD 恰四个 allowed_paths（towerctl.py、test_completion_and_base.py、test_deliver_scope.py、test_state_verify.py）
