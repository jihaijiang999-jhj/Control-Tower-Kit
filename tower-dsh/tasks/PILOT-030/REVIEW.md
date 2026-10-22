# PILOT-030 — Independent Checkback

- Reviewer: `subagent:rev-run-c-030`
- Verdict: **PASS**
- At: 2026-10-23T01:56:40+08:00

## Note

RUN-C 卡 1/3 PASS。271 tests OK(skipped=1)；独立探针：手写信封缺任一 baseline → exit2、错误点名两字段、queue/ledger/record/envelope 列表字节不变、0 QUEUE_ADD；10 组非法值（0/-1/true/字符串2/1.0 × 两字段）均 exit2 无副作用；合法 1/1 → 1 WAITING + 1 QUEUE_ADD；envelope-new 生成的信封可入队；重复入队仍 already queued 且先于 baseline 校验。校验在第一次写之前，merge-check/post-merge/envelope-new 未动。旧码对照恰 2 个新拒绝测试失败。8/8 证据哈希与 spec_sha256 匹配；scope 恰两文件；563 文件只读快照一致；真实塔 30/29/drift 0。残余（不阻塞）：直接手改 MERGE_QUEUE.json 仍可绕过（merge/merge-check 无 baseline 校验）；029 之前未入队的 legacy 信封不再能入队（有意收紧，无迁移路径）；校验逻辑在 envelope-new/queue-add 重复；测试未钉死非法值/重复优先级。

## Evidence checked

- `tasks/PILOT-030/evidence/towerctl.py` `7700334c03806b38a448cc938f4e6bad8c4ef4022f7afa7eef1c9f21b084e204`
- `tasks/PILOT-030/evidence/test_envelope_baseline.py` `476596e8028af8ce5a6cfbdaaae3c88c2a240586b6fb1c6873df43d749426e42`
- `tasks/PILOT-030/evidence/test-output.txt` `679eaab3f53796ba58f176d7c5b4c3960c93cafbe66a6ac4a7f02b4037df5fb2`
- `tasks/PILOT-030/evidence/queue-probe.txt` `c8a91dbec5a98c085cc91c6fecc4dad5a64d311b59e548f02c35cb24c3ed3e48`
- `tasks/PILOT-030/evidence/real-run.txt` `f74e885d2329a3ea2f1767a35b90249b2d631759ed8440fd6c31240cb40dec7a`
- `tasks/PILOT-030/evidence/probe-old-code.txt` `d12de485c495c7eb20a4472cf42c8f3ae11a8a55a1011382bf826f02e11958df`
- `tasks/PILOT-030/evidence/commit.txt` `d88c5f8c18cf4ec7d15a92325fa493959843748f6008be96b10d53c987df49aa`
- `tasks/PILOT-030/evidence/diff.txt` `b19850e2c686c52a692e5421b4db79b50e30026f7a17ed1809202749f7a35065`
