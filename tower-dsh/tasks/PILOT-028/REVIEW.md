# PILOT-028 — Independent Checkback

- Reviewer: `subagent:rev-run-b-028`
- Verdict: **PASS**
- At: 2026-10-22T20:11:12+08:00

## Note

RUN-B 卡 2/3 PASS。261 tests OK(skipped=1)；独立 15 项临时塔探针全过：TASK_NEW→CLOSEOUT、ACCEPT 无 CHECKBACK、MERGE 无 MERGE_START、PMV 来自 WAITING 均 exit2 且 drift 仅 {kind,target,event,expected,actual}（无 path）；重建 TASK_NEW、重投递 DELIVER、CORRECTION_REQUIRED 重试路径均合法；未知事件忽略；同一实体多条非法保持 ledger 顺序。独立重导出现实迁移：10 任务对/8 信封对，全部在表内，常量与卡表一致；真实塔 exit0、tasks=28/envelopes=27/drift=[]、evidence_checked=200（旧码输出逐字节相同）。旧码对照恰 4 个新迁移测试失败。11/11 证据哈希与 spec_sha256 匹配；scope 恰两文件；530 文件只读快照一致；既有 drift/计数字节级不变。残余（不阻塞）：TASK_NEW 允许任意来源（重建先例，但重复 TASK_NEW 可静默重置已关闭卡，后续可加显式 rebuild 标记）；未来新增生命周期事件缺表项会默认放行（建议补表-折叠完整性测试）；POST_MERGE_FAILED 来自 MERGING 按表判红（暂无先例，可能是未来误报）；信封合法性使用独立 MERGING 通道需与状态同步；'真实塔 0 drift' 以实跑而非单测覆盖。

## Evidence checked

- `tasks/PILOT-028/evidence/towerctl.py` `b42f557ce98f7a877459805789c54c9af8578ffcc3f46455ddf41e780acc679f`
- `tasks/PILOT-028/evidence/test_state_verify.py` `9a870daf4a02b943c01493c76b89bb7f173284410988196a685dbc36dcde696f`
- `tasks/PILOT-028/evidence/test-output.txt` `9cf0c218387fb97a92ff5882200a416dd06fc970157ea2d0379198e41103013b`
- `tasks/PILOT-028/evidence/real-run.txt` `3b4cce9e33191f9306183124b9e8839d38b5105866d9d28f37dee243fd8028d5`
- `tasks/PILOT-028/evidence/illegal-probe.txt` `8c4a468480026ee2bfd200177376088e4d5d78dff50e15a210f947c2bf1776f2`
- `tasks/PILOT-028/evidence/real-transitions.txt` `4a63a2db681e793ed63101c51d58222f85b32aefd5f02937198ae28df54c9a4f`
- `tasks/PILOT-028/evidence/probe-old-code.txt` `7e641e5d817b49745beebc6951e2872d450d4cb24280f3af9fb98e35f93f0ce7`
- `tasks/PILOT-028/evidence/probe_transitions.py` `548301b954f7d6ab3e1ce7ca2952842145bfdf9fb0bff8219c9964f3c9412149`
- `tasks/PILOT-028/evidence/illegal_probe.py` `77b52c6bcf233e45f8a481d7bab41cc1825ca6918dd87e45bcd1f1e19a14a304`
- `tasks/PILOT-028/evidence/commit.txt` `93c6a813a8f76b5381985a9eb950921f92e4cba03a660cc2f12232eea2ee9ca9`
- `tasks/PILOT-028/evidence/diff.txt` `2f9ba91e3bf91a9d7d5c7b0a838bd9b645d4c142270ee12815d54b907e8d4b3d`
