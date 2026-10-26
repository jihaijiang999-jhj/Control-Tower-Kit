# PILOT-041 — 执行契约 L1：deliver 校验 worktree diff ⊆ allowed_paths；dispatch 记录 kind/model/parent

- Status: `ready`
- Authority: `workspace_write`
- Worktree: `pilot/worktrees/PILOT-041`

## Scope

- cmd_deliver 增加范围校验（在复制证据之前执行，失败则零写入）：若塔根不在 git 仓库内（authority_repo(root) is None，夹具/旧塔）→ 跳过并输出 scope_check="skipped (no git repo)"；若塔根在 git 仓库内 → 对 rec.worktree 执行 git rev-parse --show-toplevel，失败即 exit 2（fail closed）
- 基线与 diff：在 worktree 内用 git merge-base main HEAD 取分支点，git diff --name-only <merge-base>..HEAD 得到 repo 相对改动集；main 缺失或 merge-base 失败即 exit 2
- allowed_paths 映射：allowed 路径是塔根相对（含 pilot/worktrees/<ID>/ 前缀）；映射为 repo 相对——若 A 以 <worktree_rel>/ 开头，则 repo_path = <tower_rel>/<A 去掉 worktree 前缀>，否则 repo_path = <tower_rel>/<A>；<tower_rel> 由 repo_relative(repo, root) 动态计算
- 越界判定：改动集必须是映射后 allowed 集的子集；否则 exit 2，errors 列出每个越界文件；同时要求 git status --porcelain --untracked-files=no 为空（已跟踪文件不得未提交），未跟踪的 scratch/ 允许；deliver 输出增加 scope_check / scope_files / scope_checked 字段（成功时可见）
- cmd_dispatch 增加 --kind（默认 subagent）、--model、--parent 三个可选参数；写入 record.dispatch 与 DISPATCH ledger payload（{executor, worktree, at, kind, model, parent}）；kind 非空字符串校验；缺省保持向后兼容
- 新增 tools/tests/test_deliver_scope.py：git 仓库 + 塔根 + 真实 worktree 的夹具——只改 allowed 文件 → deliver exit 0 且输出 scope_checked=true；多改一个 allowed 外文件 → exit 2、record 仍 dispatched、证据零写入；已跟踪文件未提交 → exit 2；未跟踪 scratch/ → 放行；非 git 夹具塔 → 输出 skipped 且 deliver 照常；dispatch 三个新字段写入 record 与 ledger
- 旧码对照：main 版 towerctl 在同一越界夹具上 deliver exit 0（无范围检查），新码 exit 2；证据写进 scratch/probe-old-code.txt
- 真实塔验证：用 worktree 新工具跑 authority-check/state-verify（configured+required、drift []）；建信封前 tasks=41/envelopes=40，建信封后 41/41
- 不改 036–040 已建立的信任边界/授权/前置链/空账本语义；不改 envelope-new / queue-add / merge / post-merge；不手写 ledger 或允许手改 allowed_paths

## Allowed paths

- `pilot/worktrees/PILOT-041/tower-dsh/tools/towerctl.py`
- `pilot/worktrees/PILOT-041/tower-dsh/tools/tests/test_deliver_scope.py`

## Forbidden

- network
- external dependencies
- changes outside the task worktree
- merge
- production access
- weakening or deleting existing test coverage
- hand-editing state/AUTHORITY.json, shared/AUTHORITY_POLICY.json or ledger/*.jsonl
- silently skipping the scope check when the worktree is a git repository
- treating an uncommitted tracked change as in-scope
- changing legacy (no baseline) envelope semantics

## Acceptance

- cd pilot/worktrees/PILOT-041/tower-dsh && python -B tools/run_tests.py 全部通过，Ran N >= 371 + 新增用例数（main 基线 371）
- git 夹具：只改 allowed 内文件并 commit → deliver exit 0，输出 scope_checked=true、scope_files 含该文件；record 变 delivered
- 同夹具多改一个 allowed 外文件并 commit → deliver exit 2，errors 列出越界文件，record 仍 dispatched、evidence 为空（零写入），无 DELIVER 事件
- 已跟踪文件有未提交改动 → deliver exit 2（tracked dirt），未跟踪 scratch/ 存在不影响
- 非 git 夹具塔（authority_repo 为 None）→ deliver 照常 exit 0，输出 scope_check=skipped (no git repo)
- worktree 是 git 仓库但取不到 merge-base/main → deliver exit 2（fail closed），不静默跳过
- dispatch --kind external --model m1 --parent p1 → record.dispatch 与 DISPATCH ledger payload 均含四个字段；不带新参数时行为与旧版一致（只多默认 kind=subagent 或完全兼容）
- 旧码对照：main 版工具在越界夹具 deliver exit 0，新码 exit 2；证据写进 scratch/probe-old-code.txt
- 真实塔：worktree 新工具 authority-check exit 0（configured+required）、state-verify drift []；建信封前 tasks=41/envelopes=40，建信封后 41/41；verify-ledger 0 error；spec-coverage 27/27；spec-lint --strict 6/6
- git -C pilot/worktrees/PILOT-041 diff --name-only main..HEAD 恰两个 allowed_paths（towerctl.py、test_deliver_scope.py）
