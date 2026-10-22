# PILOT-026 — Independent Checkback

- Reviewer: `subagent:rev-pilot-026`
- Verdict: **PASS**
- At: 2026-10-22T15:31:00+08:00

## Note

AC-1..AC-11 PASS（AC-8 实跑留待 supervision post-merge）。246 tests OK(skipped=1)；独立 15 次 post-merge fixture：baseline1 通过(exit 0, ran 1, baseline 1，6/6)、baseline2 判红并转 CORRECTION_REQUIRED、无 tools/tests 判红(envelope null)、无 baseline 不跑且无检查(sentinel 证明未执行)、塔套件自身失败仍判红；原 11 个 post-merge 测试全绿，check 顺序正确。旧码对照 17 tests/6 failures。10/10 证据哈希与 spec_sha256 匹配；scope 恰三文件；526 文件只读快照一致。hardening2 偏差（多 13 行 fixture 以让 6/6 成立）经复核判定 ACCEPT：AC-7 要求 6/6 而 opt-in 设计下该 fixture 原为 5/5，两者只能靠 fixture opt-in 同时成立，未削弱任何断言；建议在记录中更正 '只改这一行' 的措辞。残余（不阻塞）：tower_count 为 0 时 detail 显示 ran unknown（仅措辞）；非法 tower_tests_baseline 静默跳过；tower_tests_count 有 null/absent 两态；根/塔门禁相互独立会重复跑套件；字段需信封作者填写，否则静默降级 5 检查。

## Evidence checked

- `tasks/PILOT-026/evidence/towerctl.py` `fcb6e0b691384c1cd67d3794d190cb54ac98926acd6a2d1341dc45b6e03b9bc2`
- `tasks/PILOT-026/evidence/test_post_merge.py` `a5f2f5a35b26ebefb4f3054dc83138f54e3379af1f6c0109400050b292dc84ed`
- `tasks/PILOT-026/evidence/test_hardening2.py` `d866cfbd08b1e9c2a29e254db77c6cee09987d13edd1c5e0c5cda043e72c907e`
- `tasks/PILOT-026/evidence/test-output.txt` `ee8f1ff9d1efdf4bfcbb436de32a70523656f95c8a0a72cc8f8923ddcb04fbd5`
- `tasks/PILOT-026/evidence/post-merge-checks.txt` `56c6f0af6d3dc7d230addf2c5af635a1f7c4ec0a3c21304f0fb557f19d199077`
- `tasks/PILOT-026/evidence/probe-old-code.txt` `ee60cddfa34cbc46dc039380de6344bb84e80cad5c1ddf9fd8017d444a9b991c`
- `tasks/PILOT-026/evidence/real-run.txt` `cd14078bcf08b49cec99ddf10242beee9dd094c7c8fde9773b74b8f32ec56f21`
- `tasks/PILOT-026/evidence/deviation-6of6-premise.txt` `1abc62b359687f43ad46180e930b72b4211f1021f44915aedd9d402a6fd33471`
- `tasks/PILOT-026/evidence/commit.txt` `5d935b92a3a9c3e1ba87c802ed265974725eedec0335488ec3ff9716ee0028e8`
- `tasks/PILOT-026/evidence/diff.txt` `525f4395680d8ab5f5f155c99830616f65e4829f4883958793be92d16c134709`
