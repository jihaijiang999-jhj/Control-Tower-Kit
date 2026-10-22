# PILOT-033 — Independent Checkback

- Reviewer: `subagent:rev-033`
- Verdict: **PASS**
- At: 2026-10-23T07:31:58+08:00

## Note

033 PASS。287 tests OK(skipped=1)；独立探针：手写信封+手写队列无事件 → state-verify exit2 且 drift 同时含 queue_unbacked/envelope_unbacked（字段与 spec 逐字一致）；同一塔带 1/1 → merge-check exit2 且唯一失败项 queue entry backed by ledger；补 ENVELOPE_NEW+QUEUE_ADD 后 ok=true；正常 envelope-new+queue-add 通过；legacy 无 baseline 检查缺省；无事件任务仍 skipped；干净塔无 unbacked。真实塔 33/32/drift 0（evidence_checked 246）。旧码对照 72 tests/4 failures/2 errors，恰为新用例。9/9 证据哈希与 spec_sha256 匹配；scope 恰三文件；615 文件只读快照一致。残余（不阻塞，建议下一卡）：R1 merge-check 不验 ledger 哈希链，伪造 QUEUE_ADD 行可通过（verify-ledger 能抓）；R2 只要求 QUEUE_ADD，未要求 ENVELOPE_NEW；R3 envelope 身份用文件内容而非请求 id，复制已有信封改 id 可通过；R4 envelope-new/queue-add 先写文件后写事件，半途失败留下持久 drift 且不可重试。

## Evidence checked

- `tasks/PILOT-033/evidence/towerctl.py` `7776346e21f38aed450930f2a75ee64d66d91a06457c70711b9d8fc7bd3f83e2`
- `tasks/PILOT-033/evidence/test_state_verify.py` `2f6a22d29caf6ddfc70108c4cf36d564aed62a10541935cde36b83cd4eac67e8`
- `tasks/PILOT-033/evidence/test_envelope_baseline.py` `427a627b71c8d8e9f7b7c693376a7426f89475cbcde59ec9ea8504acaf337aa3`
- `tasks/PILOT-033/evidence/test-output.txt` `f5a1b7cb435b19663cbe719294682c19a724d3c90ba86b175ebb8bd05b6eb631`
- `tasks/PILOT-033/evidence/unbacked-probe.txt` `d03eb8e7abe5d78c57cdbd82c7685e1bd175f5a5625a7a6076db976300f33ddd`
- `tasks/PILOT-033/evidence/real-run.txt` `74399ffcc45d80b810be95d543f42131732baf49d723e1c0260596e3cb0a7f39`
- `tasks/PILOT-033/evidence/probe-old-code.txt` `9c7ae2ba5961345b2788e878d0e61a802b759fbbc3591ce28d55a735ac8bd61e`
- `tasks/PILOT-033/evidence/commit.txt` `b69b1dc89c08efd518331d2701f6e464ab43838eca8f95d58acb892d2eaf989f`
- `tasks/PILOT-033/evidence/diff.txt` `fd5964b90809350d40aceb711991a0a24245a382d1c95f921fb702890e4bbbea`
