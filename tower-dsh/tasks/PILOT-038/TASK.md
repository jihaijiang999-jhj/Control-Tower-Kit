# PILOT-038 — 授权必需标记：authority_required 持久化，禁止删文件/截账本退回 legacy；authority-set 写账本失败 fail-closed

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-038`

## Scope

- 新增持久必需标记 shared/AUTHORITY_POLICY.json（schema tower/authority-policy@1）：tower_id、require_authority=true、set_by、decision、set_at；它随 git 跟踪、计入 AUTHORITY_STATE_DIRS（未提交即可见），并与 ledger 事件互锚
- 新增 towerctl authority-require --by <name> --decision <D>：--by 必须等于 primary/CURRENT_STATE.json 的 owner.name，否则 exit 2；写 shared/AUTHORITY_POLICY.json 并追加 primary ledger 事件 AUTHORITY_REQUIRED（payload 与文件同构）；已存在且 require_authority=true 时幂等返回 already=true 且不重复追加事件；任何校验失败零写入
- authority_state_check 增加 requirement 维度：required = policy 文件 require_authority=true 或 ledger 存在 AUTHORITY_REQUIRED；required 且（文件与 AUTHORITY_SET 都缺）→ 错误 authority required but not configured（legacy 不再成立）；required 时 policy 与 AUTHORITY_REQUIRED 必须互配（有策略无事件=policy unbacked，有事件无策略=policy missing），否则 exit 2；非 required 的旧塔保持 legacy 兼容
- cmd_merge：authority 校验在 required-but-unconfigured / policy 不一致时 fail closed（exit 2，队列条目保持 WAITING，不写 MERGE_START/MERGING）；其余行为与 037 一致
- cmd_merge_check：required 时增加一条 ok=false 的失败 check（若未配置）或 ok=true 的 requirement pinned check；非 required 的旧塔仍输出 legacy 说明
- cmd_state_verify 增加 drift：authority_policy_missing（事件在、策略文件缺失或 require_authority=false）、authority_policy_unbacked（策略为 true、无 AUTHORITY_REQUIRED 事件）、authority_required_unconfigured（required 但文件与 AUTHORITY_SET 都缺）；legacy（无策略无事件）仍记 skipped
- cmd_authority_set：把 append_ledger 写入包进异常处理（OSError 与 LedgerLockTimeout）→ 单 JSON、exit 2、无 traceback；失败时不得出现“看起来 configured”的状态（文件已写则保持 unbacked，merge 仍 fail closed），重跑可修复
- 新增 tools/tests/test_authority_required.py 覆盖：require 正反/幂等；required 塔删 state 文件 + 截掉尾部 AUTHORITY_SET（前缀合法）→ check/merge fail closed；策略被删但事件在 → 失败；策略在但事件被截 → 失败；append 失败（ledger 为目录）→ 干净 exit 2、无 traceback、不 configured；非 required 旧塔 legacy 兼容
- tools/tests/test_state_verify.py 增加三种新 drift 的用例；不改 037 已建立的 configured 语义与检查名
- 真实塔迁移：用 worktree 的新工具对真实塔执行 authority-require（--by mac --decision D-PILOT-038）与 authority-set（revision 2），随后合并本卡；post-merge 在新代码下必须通过 authority-check（configured + required）
- 不改 legacy（无 baseline）信封语义、envelope-new / queue-add / post-merge 的既有行为；不手写 state/AUTHORITY.json、shared/AUTHORITY_POLICY.json 或 ledger

## Allowed paths

- `pilot/worktrees/PILOT-038/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-038/tower-dsh/tools/tests/test_authority_required.py`
- `pilot/worktrees/PILOT-038/tower-dsh/tools/tests/test_state_verify.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- allowing merge on a required tower whose authority state is missing or unbacked
- making POLICY-only (no ledger event) satisfy the requirement
- changing legacy (no baseline) envelope semantics

## Acceptance

- cd pilot/worktrees/PILOT-038/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 328 + 新增用例数（main 基线 328）
- fixture 上 authority-require --by mac --decision D-X → exit 0；shared/AUTHORITY_POLICY.json 存在且 require_authority=true；primary ledger 恰一条 AUTHORITY_REQUIRED；authority-check exit 0、status=configured、requirement=required
- authority-require --by mallory → exit 2、零写入（无策略文件、事件数不变）
- 重复 authority-require → 幂等：exit 0、already=true、AUTHORITY_REQUIRED 仍恰一条
- required 塔（已 require + 已 authority-set）上：删 state/AUTHORITY.json 并移除尾部唯一 AUTHORITY_SET（保留合法前缀链）→ verify-ledger exit 0，authority-check exit 2 且错误含 required but not configured，state-verify drift 含 authority_required_unconfigured，merge exit 2 且队列仍 WAITING、无 MERGE_START
- required 塔删掉 shared/AUTHORITY_POLICY.json 但 AUTHORITY_REQUIRED 仍在 → authority-check exit 2（policy missing）、state-verify drift 含 authority_policy_missing
- 策略 require_authority=true 但截掉 AUTHORITY_REQUIRED 事件 → authority-check exit 2（policy unbacked）、state-verify drift 含 authority_policy_unbacked
- ledger/primary.jsonl 换成目录后 authority-set → exit 2、单个 JSON、无 traceback、authority-check 不是 configured（unbacked/missing），merge fail closed；ledger 恢复后重跑 authority-set 可修复
- 非 required 旧塔（无策略无事件）：merge-check 仍 exit 0 且含 legacy 说明；037 既有 configured 测试全部保持绿
- 旧码对照：用 git show main:tower-dsh/tools/towerctl.py 落 main 版工具，对同一 required 夹具（删文件 + 截尾）跑 authority-check/merge-check/merge → 旧码按 legacy 放行（或至少不报 required），新码全部拒绝；旧码在 ledger 为目录时 authority-set/写账本 → traceback/exit 1，新码 exit 2 单 JSON。证据写进 scratch/probe-old-code.txt
- 真实塔：authority-require + authority-set（revision 2）后 authority-check exit 0 status=configured；建信封前 state-verify tasks=38/envelopes=37/drift []，建信封后 38/38；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-038 diff --name-only main..HEAD 恰三个 allowed_paths（tower-dsh/tools/towerctl.py、tower-dsh/tools/tests/test_authority_required.py、tower-dsh/tools/tests/test_state_verify.py）
