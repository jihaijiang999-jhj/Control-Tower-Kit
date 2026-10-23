# PILOT-036 — Independent Checkback

- Reviewer: `subagent:ca85fa50-d817-4714-a0b7-563237d90ba8`
- Verdict: **PASS**
- At: 2026-10-23T18:26:59+08:00

## Note

036 PASS。独立复核自建 %TEMP% 塔（非复用执行者 probe）：Ran 305 tests / OK(skipped=1，平台 symlink)；10/10 证据 SHA-256+字节数与 record 一致、evidence/towerctl.py 与 worktree 字节相同、spec_sha256 匹配；scope 恰 4 文件（+640/-26），既有两个测试仅各 +6 行夹具/注释、0 删改断言。逐条复现：缺失 supervision → verify-ledger exit2 单 JSON errors=[supervision: ledger missing]、merge-check 唯一失败 ledger chain intact / state-verify exit2 ledger_errors；primary 目录化 → exit2 单 JSON ledger unreadable 无 traceback；touch 空账本 → exit0 ok；envelope_id=42 vs '42' → merge-check/merge 命令级 list[str] 拒绝且队列留 WAITING；ENVELOPE_NEW 错 head/task → merge-check 失败、merge 置 CORRECTION_REQUIRED 无 MERGE_START；合法塔 15 check 全绿且 detail 恰为 ok / ENVELOPE_NEW event present。旧码对照独立复现 4/4：缺账本 exit0、目录账本 traceback、整数 id 命令级放行、错 head 的旧 merge 真的 MERGED。对抗：可读坏链不会触发 supervision_available 跳过（坏链+错绑定同时报 2 条）；envelope_head_sha 两边同时缺失时 None==None 可过绑定检查，但 git 检查（branch head==envelope head、b^）仍拦 merge，非旁路。真实塔：state-verify exit0 drift[] 36/35、verify-ledger 321/183 0 error、spec-coverage 27/27、spec-lint --strict 6/6；新工具对真实塔复跑同样全绿。残余（不阻塞）：无密钥链可被「追加一行正确 prev_hash/hash 的 ENVELOPE_NEW」伪造（比重算整链更弱，宪法禁止 executor 写 ledger）；legacy 无 baseline 路径不查链/绑定（spec 显式保留）；建议后续把 head 缺失、supervision_available 前提写成不变量测试。

## Evidence checked

- `tasks/PILOT-036/evidence/towerctl.py` `209d7782f9c5b22685bf9ec3f537eecb27c2d3a32a4daf34fd787801f53b6ffa`
- `tasks/PILOT-036/evidence/test_trust_boundary.py` `52e2a8482a4429a916af8ca848bb974a77c83554e83934019bda6cafc5f3ba5b`
- `tasks/PILOT-036/evidence/test_ledger_chain.py` `e62a3c401121a371bd676f1148c018c43e4d9898a942d6ad429eb06ee83482f5`
- `tasks/PILOT-036/evidence/test_ledger_lock_windows.py` `ae53b19d1a7a00216432eec3896d3bdfbf96c46480633e2f20cd5aae3e61992b`
- `tasks/PILOT-036/evidence/test-output.txt` `761dd478b2fdaba1d19dddbca400c55f5fadfbc2f035a45039b791e43a647019`
- `tasks/PILOT-036/evidence/trust_probe.py` `a827dd00eedf6440433226df2d4cb75f95c68bbceb8db928ce4fb356ace615b4`
- `tasks/PILOT-036/evidence/probe.txt` `a1a0381efe595d4138c19c2f46376b0b9bbb01794b762ed0abd64ce9f8a459e9`
- `tasks/PILOT-036/evidence/probe-old-code.txt` `b907f3660faf63f18bdda7ed4d6b38aa54ffa7a245c67cbd7d0e04d79ad23ecd`
- `tasks/PILOT-036/evidence/commit.txt` `c6c70b3566b98f409682678b856dbfe6fdc222693bc4951c255a792456a3b490`
- `tasks/PILOT-036/evidence/diff.txt` `454a3c0a4a09d38248fa2569cc37e4ae2ef86ef28a298488939af28f8711721e`
