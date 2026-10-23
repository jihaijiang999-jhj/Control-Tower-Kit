# PILOT-035 — Independent Checkback

- Reviewer: `subagent:rev-035`
- Verdict: **PASS**
- At: 2026-10-23T17:01:32+08:00

## Note

035 PASS。293 tests OK(skipped=1)；独立 11 塔 57/57 断言：真实半写（有 ENVELOPE_NEW、队列在、事件缺失）→ queue-add exit0 repaired=true、恰一条 QUEUE_ADD、队列字节不变、state-verify 不再有 queue_unbacked；缺 baseline 的半写 → exit2 且零写入；正常重复仍 already queued；首次入队无 repaired 键；信封缺失在修复前失败；伪造坏链 QUEUE_ADD 抑制修复但链检查/verify-ledger 拦截；非 WAITING 条目修复时 stdout 报 WAITING 但保留原状态（P5 残余）；反向半写不在范围。旧码对照恰 2 个修复测试失败。9/9 证据哈希与 spec_sha256 匹配；scope 恰两文件；673 文件只读快照一致；真实塔 35/34/drift 0。残余（不阻塞）：修复不造 ENVELOPE_NEW（手写信封修复后仍被 merge 的 envelope_new 检查拦）；非 WAITING 条目状态与 stdout 不一致；坏链行抑制修复；反向半写未处理；重复条目与 task 字段分歧；queue-add 不把信封状态同步为 WAITING（既有）。

## Evidence checked

- `tasks/PILOT-035/evidence/towerctl.py` `7bc2e030eaaa7ac017746350268966d47b578a038140544427b84c15f3c5a2eb`
- `tasks/PILOT-035/evidence/test_envelope_baseline.py` `353c46d0b1f21fe88c106dd3f3f565ca589ac45ac6dbf436834579a7643d204e`
- `tasks/PILOT-035/evidence/test-output.txt` `2ab06bf10a82a365604892b96befaaf4e2b0e44370441305defc0fdd95ecb1d4`
- `tasks/PILOT-035/evidence/repair-probe.txt` `03516ea86fba4e191a765be3437fb96b46ec78ef5df648927fa97ff056acdf02`
- `tasks/PILOT-035/evidence/repair_probe.py` `1f2a6378ae79479580735dfaad945a29ca0978e72f0f33ad6b325448a2f7b3ef`
- `tasks/PILOT-035/evidence/real-run.txt` `713c6fa1bb24662847f47bd846a081465ec471b3467d7eaba76ac482e3f2d217`
- `tasks/PILOT-035/evidence/probe-old-code.txt` `5f494aaa7dd3c58d062b80a1a7ef1cd3dd9228057483c84f148d41984b974fa6`
- `tasks/PILOT-035/evidence/commit.txt` `29f2b34dafe3772c8e23882a8598a42c767344eb14c4d81df18e716425e88bab`
- `tasks/PILOT-035/evidence/diff.txt` `f526d75feaa740ce9a9f85adf968a1494261d3881e157f8a96501cdf3f14f77e`
