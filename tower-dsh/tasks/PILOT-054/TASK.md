# PILOT-054 — 记录层纵深：deliver 反查 completion、state-verify 审计 base_sha 与孤悬 completion

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-054`

## Scope

- deliver：对 diff 实际命中的每条 completion，在 primary ledger 反查匹配的 COMPLETION_ADDED（task+path）；无事件 → exit 2（completion not backed by COMPLETION_ADDED），零写入
- deliver：事件必须与 record.completions 条目逐字段一致（path/by/reason/decision/at；at 同秒可比较或用事件 at），不一致 → exit 2（completion record does not match ledger event），零写入
- deliver：事件 by 必须等于 owner.name；path/by/reason/decision 非空；否则 exit 2（与 completion-add 同信任模型，纵深防御）
- state-verify 新增 dispatch base_sha 审计：record.dispatch.base_sha 非空时必须与对应 DISPATCH payload.base_sha 完全一致，否则 drift dispatch_base_mismatch；事件有 base_sha 而 record 为 null → dispatch_base_missing；两者都空 → 不报（legacy）
- state-verify 新增 completion_orphan：primary ledger 中 COMPLETION_ADDED 的 task 在 replay 与 record 中都不存在 → drift completion_orphan；新增 completion_mismatch：record.completions 条目与对应事件 payload 不一致 → drift completion_mismatch
- state-verify：因 no_lifecycle_events 被 skip 的任务，若 record 有 completions，仍要审计（不得因 skip 而跳过 completion 检查）；无 completions 的 legacy 任务不新增 drift/skip
- 新增 tools/tests/test_record_layer.py：deliver 对 forged record（无事件）→ exit 2 零写入；record 与事件字段不一致 → exit 2；事件 by 非 owner → exit 2；匹配 → 0；state-verify 的 dispatch_base_mismatch/missing、completion_orphan、completion_mismatch；skip 任务的 completions 仍被审计；legacy 无 completions/base_sha 无新增 drift
- tools/tests/test_completion_and_base.py 仅做与新语义冲突的最小调整（042 的“手写 record 无事件 deliver 0”用例必须改为 exit 2）；不得放宽其它断言
- 真实塔验证：worktree 新工具 authority-check/state-verify（configured+required、drift []）；建信封前 tasks=53/envelopes=52，建信封后 53/53；merge 前置链与空账本守卫仍通过
- 不改 036–053 的信任边界/授权/前置链/空账本/范围门/completion 语义（除本条明确收紧）；不手写 ledger；completion 仍不得绕过 merge/authority 等其它门

## Allowed paths

- `pilot/worktrees/PILOT-054/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-054/tower-dsh/tools/tests/test_record_layer.py`
- `pilot/worktrees/PILOT-054/tower-dsh/tools/tests/test_completion_and_base.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- accepting a completion whose backing event is missing or mismatched
- letting a skipped task bypass completion audit
- using base_sha from anywhere other than the matching DISPATCH event

## Acceptance

- cd pilot/worktrees/PILOT-054/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 609 + 新增用例数（main 基线 609）
- deliver：completion 路径已被 completion-add 正常记录 → exit 0、scope_completions 正确；手写 record.completions（无事件）→ exit 2、零写入、无 DELIVER 事件
- deliver：record 条目与事件字段不一致（改 by/reason/decision/at 任一）→ exit 2；事件 by 非 owner → exit 2；path/by/reason/decision 空 → exit 2
- state-verify：record base_sha 被改（与 DISPATCH payload 不一致）→ drift dispatch_base_mismatch；事件有 base_sha 而 record null → dispatch_base_missing；两者一致 → 无 drift
- state-verify：COMPLETION_ADDED 指向不存在的 task → drift completion_orphan；record 条目与事件不一致 → drift completion_mismatch；被 skip(no_lifecycle_events) 的任务有 completions 时仍报 completion_unbacked/mismatch
- legacy：无 completions、无 base_sha 的旧任务不新增 drift/skip；既有 state-verify 用例全绿
- 旧码对照：main 版工具对 forged record delivery exit 0、对篡改 base_sha 的塔 state-verify 0 drift；新码分别 exit 2 与报 drift。证据写进 scratch/probe-old-code.txt
- shape-check 在 worktree exit 0（新增函数 ≤80 行/≤12 分支；既有函数不增长）
- 真实塔：worktree 新工具 authority-check exit 0（configured+required）、state-verify drift []；建信封前 tasks=53/envelopes=52，建信封后 53/53；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-054 diff --name-only main..HEAD 恰三个 allowed_paths
