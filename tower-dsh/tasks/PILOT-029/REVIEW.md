# PILOT-029 — Independent Checkback

- Reviewer: `subagent:rev-run-b-029`
- Verdict: **PASS**
- At: 2026-10-22T20:34:59+08:00

## Note

RUN-B 卡 3/3 PASS。266 tests OK(skipped=1)；15/15 独立探针：两字段缺失、各自 0/-1/true/字符串2/1.0 共 12 种拒绝全部 exit2、错误同时点名两字段、无 envelope 文件/无 ENVELOPE_NEW/record+queue+ledger 快照不变；合法 1/1 与 3/5 均建 DRAFT 且保留值、ENVELOPE_NEW 恰 1 条；手写 legacy 信封仍可 queue-add/merge-check（旧路径未变）。校验位于 load_record 与任何写之前，merge-check/post-merge 未动。旧码对照 12 failures 恰为 12 个拒绝断言。11/11 证据哈希与 spec_sha256 匹配；scope 恰四文件；551 文件只读快照一致；真实塔 29/28/drift 0。残余（不阻塞）：校验仅在 cmd_envelope_new，手写信封+queue-add 仍是旁路；baseline 只校验存在/类型/>=1，低值或过期值不会被拒（post-merge 只做 >= 比较）；外部旧工具不再能省略字段；布尔/浮点已正确拒绝。另：卡面 main baseline 246 已过期，实际冻结基线 261。

## Evidence checked

- `tasks/PILOT-029/evidence/towerctl.py` `9f17da6b4f3d505bd83547fbe9b3310018499bf018ab3c61da7779ccf102c22e`
- `tasks/PILOT-029/evidence/test_coverage.py` `8e105724dd67e804808cb8a357bb96736ed141e63b401d38595f2a13df4ee895`
- `tasks/PILOT-029/evidence/test_hardening2.py` `0edfb4c708a14bff7a7f90ae40823b2b42cff0fa8a71bdb513ee14fee9f70d87`
- `tasks/PILOT-029/evidence/test_envelope_baseline.py` `3053ec8f8d939678058e89f1533f362b1903a4b2f8f2ec7875ad7b60efc8658b`
- `tasks/PILOT-029/evidence/test-output.txt` `41204363f7f51efe738a03d976156eb1cbd262fe3237b3faddbeb52846e520c2`
- `tasks/PILOT-029/evidence/real-run.txt` `fcfaf3465877d320495da59c3e2564eeb41f9e4bd00ba9389761c764fab79917`
- `tasks/PILOT-029/evidence/baseline-probe.txt` `3ac15f0e93b0c6388e6fcad7bc8c411f665a09f39753fa7fb0bdb4b9d1446596`
- `tasks/PILOT-029/evidence/probe-old-code.txt` `81f8d993ebca5f699272b8fc0a5394715dd5c810a4313678f621aa55d2cd6ce4`
- `tasks/PILOT-029/evidence/probe_envelope_baseline.py` `d9988ec24ea95a7d94c864437f9f8d05951d52cc544eb71d77dbdc2d371e402a`
- `tasks/PILOT-029/evidence/commit.txt` `e339fec9a2ab8d3c70dc6998597cc39f2512bfb74bbfaf734c3bb6c6193d558a`
- `tasks/PILOT-029/evidence/diff.txt` `51aa337114e7d76a89d63b97abfc98aa7cd069695cc026535accd0f5dd1cf85d`
