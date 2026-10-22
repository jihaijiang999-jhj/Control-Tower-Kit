# PILOT-031 — Independent Checkback

- Reviewer: `subagent:rev-run-c-031`
- Verdict: **PASS**
- At: 2026-10-23T02:24:41+08:00

## Note

RUN-C 卡 2/3 PASS。277 tests OK(skipped=1)；独立 11 项 anchor 矩阵：anchor10/baseline5 判红且 detail 精确、无新 VERIFIED；10 与 12 通过；无事件时检查缺省；[7,10,3] 取 max=10；true/字符串/null 被忽略；POST_MERGE_FAILED 不抬锚；字符串/缺失 baseline 时两道塔门均缺省；无 ledger 时 anchor None。真实 anchor 独立解析=271（246/252/261/266/271，25 条无计数的 legacy 事件忽略）；真实塔 31/30/drift 0。旧码对照恰 6 个新测试失败、16 个旧测试绿。9/9 证据哈希与 spec_sha256 匹配；scope 恰两文件；594 文件只读快照一致。残余（不阻塞）：opt-in 缺省可绕过塔门；伪造/错误 verified 事件可抬高锚（fail-closed DoS）；非追溯；锚只增不减，旧基线信封需重冻结；无锁读尾可能瞬时少计（fail-open）；只校数量不校质量。证据小瑕疵（不影响验收）：E-008 两个列表段为字面 System.Object[]、E-003 含 PowerShell 噪声，但恰含一条 Ran 277/OK。

## Evidence checked

- `tasks/PILOT-031/evidence/towerctl.py` `57468519f6a768e0a4c8a4ef6802037c03bd8434e7e28745632dfc80f7be8000`
- `tasks/PILOT-031/evidence/test_post_merge.py` `a42a9e617a7cd666a58f200b3f9f0eb26993c2c100188525dd5141a294e43d17`
- `tasks/PILOT-031/evidence/test-output.txt` `99272e4215e8ad7a50d75961fe68a199ed582cddd3cc82c9daf9fc6ae38f5342`
- `tasks/PILOT-031/evidence/anchor-probe.txt` `0d6ee72745fafc8e8dd6b642d9519f82c4ab24aea329aa483bb9fae229d076ba`
- `tasks/PILOT-031/evidence/anchor_probe.py` `943b65af187017ad268807617828a53c23efc0a82d27c8bb5ae79e06fbb27940`
- `tasks/PILOT-031/evidence/real-run.txt` `7e5a3173ea517a21a79e989b6bb8d64d7fad12592f7b38ae864fc58ddb96c3df`
- `tasks/PILOT-031/evidence/probe-old-code.txt` `1102d47aa815fe5c14f29e56553782797e1e71e2fc9803c1dfa368eed8469173`
- `tasks/PILOT-031/evidence/commit.txt` `e6a6bbd2329b308af1d87f849316c3c57eb7d9914719d627707cebe74172b862`
- `tasks/PILOT-031/evidence/diff.txt` `bc5474e0ea1ae7c8e4bc6f555d311e0fee940957bafdd4d2b4102cf8dd5dabc1`
