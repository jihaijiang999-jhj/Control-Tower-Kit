# PILOT-041 — Independent Checkback

- Reviewer: `subagent:7d878b41-c0f6-4ddb-9a04-c1ca69ffb904`
- Verdict: **PASS**
- At: 2026-10-26T18:52:15+08:00

## Note

041 PASS（第二轮）。上轮唯一阻塞（rename 漏检）已修：`git diff --name-only --no-renames` 让 `git mv 外部 tracked 文件 → allowed 路径` 同时列出旧/新路径，deliver exit 2、errors 点名旧路径、record 仍 dispatched、证据零写入；反向 rename 仍拒；两侧都在 allowed 的 rename 放行（无过度误伤）；旧码同夹具 exit 0。同轮加固 toplevel/git-dir 身份检查：纯子目录、嵌套 git 仓库、foreign .git、同仓库 main gitdir、独立 clone 均 exit 2 且零写入，真实 linked worktree（含 --relative-paths）不被误伤。回归全绿：上轮 6 场景、dispatch 四字段/默认/空值拒绝、§6.11 断言；独立复核夹具 95 PASS/0 FAIL；亲跑 Ran 387 tests / OK(skipped=1)。证据 10/10 SHA-256+字节数一致、evidence/diff.txt 与 live diff 字节相同、spec 哈希一致；scope 3 文件（2 allowed + test_deliver_ids.py 的 §6.11 3/2 单点，本轮未再动）。真实塔只读：state-verify 41/40 drift []（skipped 3 VOID）、authority-check configured+required（13/13）、verify-ledger 0 error（primary 377/supervision 208）、coverage 27/27、lint 6/6、9 个关键文件哈希前后不变。bootstrap 判定：本卡交付仍用 main 版 pre-gate 工具（分支 3 文件 vs spec allowed 2；新门无法验证引入它自己的 commit），复核判为**一次性、有条件的例外**——closeout 记录、不追认不回填、后续卡必须走新门、尽快开 completion-list 机制卡；副作用：本卡 dispatch 仍旧三字段、DISPATCH seq 374 无 kind/model/parent、DELIVERY.md 无 scope 字段，均如实记录。残余（非阻塞）：①本地 main ref 可 update-ref 改写使 diff 为空仍能过门（已延期另卡，建议 dispatch 锚定 base_sha）；②独立 clone 被身份检查拒绝（兼容注记）；③塔仓本身是 linked worktree 时会被误拒（当前主 checkout 无影响，替代方向=common-dir/已注册 worktree 判定）；④identity 是路径前缀不是密码学边界；⑤rename 需两侧都在 allowed（保守）；⑥--absolute-git-dir 需 git>=2.13；⑦§6.11 subset 断言可再收紧为精确 7 键；⑧卡面 acceptance 仍写"恰两个 allowed_paths"（§6.11 stale，commit body 已记）。

## Evidence checked

- `tasks/PILOT-041/evidence/towerctl.py` `47527ca27d275bacb31e627b7c85d3d7d7c9e46dc0fb9d9b8380e3b6644a7cc3`
- `tasks/PILOT-041/evidence/test_deliver_scope.py` `4875ed6deaf2b8eba6412363edebe86dfdf631428a3a2fbb19bb8b3759ef3bb9`
- `tasks/PILOT-041/evidence/test_deliver_ids.py` `d162f988576fa7a0d40185bc82f33c97c4c657f3bcbc115cea65d70a8ea32e3e`
- `tasks/PILOT-041/evidence/test-output.txt` `baa14097ab4e0c28ec01d31dedace354a5cce56c0f80300f125b53a7a52e0d79`
- `tasks/PILOT-041/evidence/deliver_scope_probe.py` `053f144c1c056cf901799824e4f9307158b3cea75b7a50e9b667f665d0719078`
- `tasks/PILOT-041/evidence/probe.txt` `08833cce013fdd7ab8bd5118726c3997dd9ddd9fd04e92835b20f6fb1e89fee6`
- `tasks/PILOT-041/evidence/probe-old-code.txt` `23ba8ad9abe978cea6ebc3edebb5c02c488e54f79898b8f7901f5b565c12efd2`
- `tasks/PILOT-041/evidence/commit.txt` `b89d5bf3c540a796993e3384393f8e5d0891802d66f175fa6861bf41a5e6b345`
- `tasks/PILOT-041/evidence/diff.txt` `655881d04709a5d32376de375addd6c8e8dc40ab2b4e62dd1ab4c08b0acb414c`
- `tasks/PILOT-041/evidence/real-tower-scope-simulation.txt` `27364db4a88ccc3ea96ebcd7e82cc0dc0274e8063860bcd96f25b2895c50a14b`
