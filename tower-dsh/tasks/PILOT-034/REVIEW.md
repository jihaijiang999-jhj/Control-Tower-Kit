# PILOT-034 — Independent Checkback

- Reviewer: `subagent:rev-034`
- Verdict: **PASS**
- At: 2026-10-23T16:34:12+08:00

## Note

034 PASS。291 tests OK(skipped=1)；独立 10/10 探针：伪造 QUEUE_ADD（坏链）→ merge-check exit2 且失败项仅 ledger chain intact（verify-ledger 同红）；只有 QUEUE_ADD 无 ENVELOPE_NEW → envelope_new recorded 失败；复制信封改 id → merge-check 与 merge 均在命令级 identity 失败且无副作用；正常流程四项新检查全 ok；legacy 三项新式检查缺省；伪造 primary 行同样被链检查抓；删除 primary.jsonl 仍显示链 ok（R4）；ledger 不可读会 traceback exit1（R5）。真实塔 34/33/drift 0、verify-ledger 0 error。旧码对照 5 failures/3 errors 恰为新用例。9/9 证据哈希与 spec_sha256 匹配；scope 恰两文件；634 文件只读快照一致。非阻塞：F1 命令级 identity 用 str() 比较（exact check 仍拦），F2 identity 不随 baseline 门（更严）；残余 R1 legacy 降级仍可绕过、R2 链可重算伪造（tamper-evident 非防篡改）、R3 任意坏行阻塞全部门、R4 缺失 ledger 不算错、R5 不可读 ledger 崩溃、R6 O(ledger) 成本、R7 ENVELOPE_NEW 只绑 id。

## Evidence checked

- `tasks/PILOT-034/evidence/towerctl.py` `ef723ebbcd73f7332e8c269ec18b3c70a45db4856f680276a66175d8cbb64f9c`
- `tasks/PILOT-034/evidence/test_envelope_baseline.py` `bd8c4fc1489bae7038e5586cad0f9c32f078a0ce5f825998a2d6d116456641d3`
- `tasks/PILOT-034/evidence/test-output.txt` `c594bd9f07fbcbcefbcf33a24254530c5abdf710c31989cd662e1d5b45c7efa4`
- `tasks/PILOT-034/evidence/merge-gate-probe.txt` `29be52fad4ecc1ce69a925211cc0d1282347c85f596af0d839d7822e11f42761`
- `tasks/PILOT-034/evidence/real-run.txt` `5db65752f5bf1abbcccbd611f9a3a137af453ef1aa4fa9530633aa9b7ad4483d`
- `tasks/PILOT-034/evidence/probe-old-code.txt` `711405277e096f77fa534148d08fc27f4c241711c7dca39475ff11146e914b48`
- `tasks/PILOT-034/evidence/probe_merge_gate.py` `b8c5b54d5d81f75ebfa343410a949b4e7361c843db7c2fb6b5023e3b46b8bd8d`
- `tasks/PILOT-034/evidence/commit.txt` `417752f7505b1979ce33a16013a483b40db2290ab9739ef4fb5e4f0b2e01d671`
- `tasks/PILOT-034/evidence/diff.txt` `64d740536358ff98da78532110cfe9899ca4a6e270cc9c171580ed08c799385b`
