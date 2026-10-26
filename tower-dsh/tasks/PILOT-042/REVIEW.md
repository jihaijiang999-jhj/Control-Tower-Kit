# PILOT-042 — Independent Checkback

- Reviewer: `subagent:457986b8-942e-4c38-a696-aa6649938d3b`
- Verdict: **PASS**
- At: 2026-10-26T22:41:54+08:00

## Note

042 PASS（无阻塞）。completion 与 base_sha 两条实际路径都关上了：completion-add 正常（record + 恰一条 COMPLETION_ADDED、字段同构、重复 already、双向半写 repaired）；非 owner/空 reason/空 decision/path .. /绝对路径/空 path 共 12 例全部 exit 2 零写入；closed 任务拒绝；deliver 允许集 = allowed ∪ completions，completion 路径 0 且 scope_completions 精确（只列实际改动项），越界仍 2 且零写入，非 git 塔仍 skipped；旧码 A（completion 路径不在 allowed）2 / 新码 0，旧码 B（worktree 内 update-ref main 后越界）0 / 新码 2；dispatch 写入 base_sha（record 与 DISPATCH payload 一致，无 main 则 null），base_sha 非祖先 exit 2，旧 record 回退 merge-base（041 行为全绿）；state-verify 三种 drift（completion_unbacked/missing/invalid）精确，无 completions 任务零新增。证据 9/9 SHA-256+字节数一致、evidence/towerctl.py 与 worktree 字节相同、diff.txt 与现场 diff 逐字节相同、spec 哈希一致；scope 2 文件（towerctl.py + 新测试 919 行/32 tests），spec allowed_paths 列 4 但两个既有测试零断言冲突故未改——复核判可接受，acceptance #11“恰四个”属 spec 文字缺陷（allowed_paths 是上限、diff 为真子集、无越界），closeout 记录。亲跑 Ran 419 tests / OK(skipped=1)，新模块 32 OK，041/037–040 定向模块全绿。真实塔只读：state-verify 42/41 drift []（skipped 3 个既有 VOID，evidence 336）、authority-check configured+required（13/13）、verify-ledger 0 error、coverage 27/27、lint 6/6、21 份关键文件哈希前后不变。残余（非阻塞）：①孤悬 COMPLETION_ADDED（task 不存在）被 state-verify 忽略，“有 record 无 lifecycle 事件”的任务 completions 也不审计；②deliver 只信 record.completions，不反查 owner 字段与 backing 事件（手写 record 可 0 通过，state-verify 才报）；③state-verify 不审计 base_sha（把 record.base_sha 改成 HEAD 即可空 diff 放行，需控制面写权限）；④已在 allowed_paths 的 path 仍可冗余 add（无害但文案误导）；⑤新测试文件少量 mojibake；⑥completion 路径仅词法校验（spec 明确 lexical）。结论：剩余风险不是门被外部绕过，而是记录层被篡改时的纵深防御缺口，可由后续卡补齐。

## Evidence checked

- `tasks/PILOT-042/evidence/towerctl.py` `795975323594bf2cb6f1000f419ff6fb0a9b3b5f1591aeec4001670ca59d940f`
- `tasks/PILOT-042/evidence/test_completion_and_base.py` `af4a20d43cd773d245ba112eb88c20497c9e7d76a7bd2671957dcccf426d946f`
- `tasks/PILOT-042/evidence/test-output.txt` `2b2d347c48e8fd80739a075c8408ab4ba2426e6531b95fa02a2afe91061a1bf8`
- `tasks/PILOT-042/evidence/completion_base_probe.py` `04321964a0f2a72ce0aed78de789f9d60076537e37e24b18f95543cbe8abbb27`
- `tasks/PILOT-042/evidence/probe.txt` `41f233848dae50a2b49c2ca476398759eb3a6d6ad693c6fd73890f7455f47054`
- `tasks/PILOT-042/evidence/probe-old-code.txt` `ae4ed928c49a093170fa49c8f4989052bbaf877aeea5a456d7248e3ef089b61a`
- `tasks/PILOT-042/evidence/commit.txt` `bd91fe35307ce2be9d87a3c9038655a656b713f2c1d2f83dfefd011b71a06593`
- `tasks/PILOT-042/evidence/diff.txt` `ecd7ef16b7ef1929c8da4cce57dfa36de50545d534739ee924f80c13d7c9ad8f`
- `tasks/PILOT-042/evidence/real-tower-readonly.txt` `259bc0d1a579c8371a016f6ca0d9ebf808eadd156015901e4d933df692638806`
