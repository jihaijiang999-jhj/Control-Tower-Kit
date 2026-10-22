# PILOT-027 — Independent Checkback

- Reviewer: `subagent:rev-run-b-027`
- Verdict: **PASS**
- At: 2026-10-22T19:40:04+08:00

## Note

RUN-B 卡 1/3 PASS。252 tests OK(skipped=1)；runner 两次不同 TMP、banner 首行、--suite/--pattern 精确选择、失败码透传；TMP/TEMP/TMPDIR 一致且指向塔内；.test-tmp 已 gitignore。三处偏差均判 ACCEPT：①runner 缺失时窄回退（fixture 只 vendor tools/tests；真实塔必走 runner，reviewer 另用 runner 分支探针 17/17 绿）；②run 目录写一行 .git gitfile 做仓库隔离（无它则 authority_drift 2 失败、handoff_generic 1 失败；仅 gitignore 范围、无 tracked 写入）；③Windows 下经 GIT_CONFIG_* 注入 core.longpaths（仅子进程、保留已有项；关闭则 20 failures+2 errors 全 Filename too long）。证据 12/12 哈希匹配；spec_sha256=9eb37e2...匹配；scope 恰六文件；502 文件只读快照一致；state-verify 27/26/drift 0/189。残余（不阻塞）：.git 假哨兵语义、longpaths 继承、fixture 只覆盖回退路径、.test-tmp 不自动清理（已文档化）。AC5 真实塔 post-merge 留待 supervision。

## Evidence checked

- `tasks/PILOT-027/evidence/test-output.txt` `09adfbc3037fafe1a20970154ed84a41680a2011bcd32359ce5639aa962a3a7d`
- `tasks/PILOT-027/evidence/direct-discovery.txt` `94d946f8e045f3cfb7c9816f505bfec370d3087c83fbdda99747b9b7f2a1e254`
- `tasks/PILOT-027/evidence/real-run.txt` `0b80f9a01aa73f46fe979437144c66c0bfab6060d59ec9a5c34654e9769dd032`
- `tasks/PILOT-027/evidence/probe-old-code.txt` `30ed6882db9d194530f2634c4f80078555153899e1786c9145623e2a2fdcb298`
- `tasks/PILOT-027/evidence/commit.txt` `492964c92717cfe0371aa03da5e3da89d362c4ccde6041aca1d34d5f80e10afa`
- `tasks/PILOT-027/evidence/diff.txt` `598504f5a5b08c172c62466834f5031255529de3ac71f40666f2b2c1a34ae256`
- `tasks/PILOT-027/evidence/gitignore.txt` `318493ab76cf99415bb2220450c1b247845f7ab27677aaea2b6d54263e970e95`
- `tasks/PILOT-027/evidence/run_tests.py` `d0bcfe6ad685f19f7c65b0fc0ccbdc8e00575a30bd485916a9d78f1b58a2f091`
- `tasks/PILOT-027/evidence/test_run_tests.py` `36fc77fff0caf5df7e36e32eb0139acd7342223beedcb3c278928b8d5d677e1b`
- `tasks/PILOT-027/evidence/towerctl.py` `51b4936b02809c9e56ddb9cd550d45426b6c12b9743e2266deef4791c6831ccb`
- `tasks/PILOT-027/evidence/REPRODUCE.md` `46f2d04a8341293f48e234f770a6230526af5d5c41312e277b42cad169d583cc`
- `tasks/PILOT-027/evidence/test_tower_gates.py` `81cdb2f6e6f5e0daa0e3c401eeb0386c37a11c11794af3d6cc00329d6ccfd5f8`
